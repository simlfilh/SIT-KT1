import re
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from rapidfuzz import fuzz

import parser as p

st.title("📊 Этап 3 — Сравнение с другими направлениями")

YEARS = {
    "2026 (1 курс)": "2026",
    "2025 (2 курс)": "2025",
    "2024 (3 курс)": "2024",
    "2023 (4 курс)": "2023",
}
FUZZY_THRESHOLD = 85  # порог схожести названий предметов
SERVICE_COLS = {"Группа", "№", "ФИО", "stud_id", "Сумма", "Семестр"}


# Утилиты
def try_fetch(params_list):
    for params in params_list:
        try:
            html = p.fetch(params)
        except Exception:
            continue
        return html, params
    return None, None


@st.cache_data(ttl=3600, show_spinner=False)
def load_directions_for_year(year: str):
    params = {
        "up": "none", "y": year,
        "k": "1", "f": "1",
        "upp": "all", "sort": "fio", "ball": "hide",
    }
    html, _ = try_fetch([params])
    if html is None:
        return []
    return [o for o in p.get_filter_options(html, "Направление")
            if o.label not in ("Не выбрано",) and "up" in o.params]


@st.cache_data(ttl=1800, show_spinner=False)
def load_groups_and_sems(up_id: str, year: str):
    params = {
        "up": up_id, "y": year,
        "k": "1", "f": "1",
        "g": "all", "upp": "all", "sort": "fio", "ball": "hide",
    }
    html, _ = try_fetch([
        params,
        {k: v for k, v in params.items() if k != "g"},
    ])
    if html is None:
        return None, [], []
    groups = [o for o in p.get_filter_options(html, "Группа")
              if o.label not in ("Не выбрано", "Все группы")]
    sems = p.get_filter_options(html, "Семестр")
    return html, groups, sems


@st.cache_data(ttl=600, show_spinner=False)
def load_group_html(up_id, year, g_id, s_id):
    return p.fetch({
        "up": up_id, "y": year, "k": "1", "f": "1",
        "g": g_id, "s": s_id,
        "upp": "all", "sort": "fio", "ball": "hide",
    })


def parse_group(up_id, year, g_id, s_id, group_name):
    html = load_group_html(up_id, year, g_id, s_id)
    meta = p.parse_subjects(html)
    rows = p.parse_students(html, group_name=group_name)
    df = pd.DataFrame(rows)
    for c in df.columns:
        if c not in SERVICE_COLS:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df, meta


def normalize_name(name: str) -> str:
    """Нормализация названия предмета для сопоставления."""
    if not name:
        return ""
    s = name.lower()
    # убираем скобки с видом контроля: (экзамен), (зачет), (дифф.зач.) и т.п.
    s = re.sub(r"\([^)]*(экзамен|зач[её]т|дифф|контроль|без контроля)[^)]*\)", "", s)
    # убираем пунктуацию и лишние пробелы
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def match_subjects(meta_a, meta_b, extra_pairs=None):
    """
    Сопоставляет предметы двух наборов.
    Возвращает список пар (short_a, full_a, short_b, full_b, score, source),
    где source = 'exact' | 'fuzzy' | 'manual'.
    Если для предмета нет пары — он не попадает в результат.
    """
    # Словарь: normal -> short/full для a
    a_list = [(m["short"], m["full"] or m["short"], normalize_name(m["full"] or m["short"]))
              for m in meta_a]
    b_list = [(m["short"], m["full"] or m["short"], normalize_name(m["full"] or m["short"]))
              for m in meta_b]

    used_a = set()
    used_b = set()
    pairs = []

    # 1) ручные сопоставления
    if extra_pairs:
        for a_short, b_short in extra_pairs:
            a_item = next((x for x in a_list if x[0] == a_short), None)
            b_item = next((x for x in b_list if x[0] == b_short), None)
            if a_item and b_item and a_item[0] not in used_a and b_item[0] not in used_b:
                pairs.append((a_item[0], a_item[1], b_item[0], b_item[1], 100, "manual"))
                used_a.add(a_item[0])
                used_b.add(b_item[0])

    # 2) точные совпадения
    for i, a in enumerate(a_list):
        if a[0] in used_a:
            continue
        for j, b in enumerate(b_list):
            if b[0] in used_b:
                continue
            if a[2] == b[2] and a[2]:
                pairs.append((a[0], a[1], b[0], b[1], 100, "exact"))
                used_a.add(a[0])
                used_b.add(b[0])
                break

    # 3) fuzzy-совпадения
    for i, a in enumerate(a_list):
        if a[0] in used_a:
            continue
        best = None
        best_score = 0
        for j, b in enumerate(b_list):
            if b[0] in used_b:
                continue
            score = fuzz.token_set_ratio(a[2], b[2])
            if score > best_score:
                best_score = score
                best = b
        if best is not None and best_score >= FUZZY_THRESHOLD:
            pairs.append((a[0], a[1], best[0], best[1], best_score, "fuzzy"))
            used_a.add(a[0])
            used_b.add(best[0])

    return pairs


# 1. Выбор «Студента №1»
# ------------------------------------------------------------
st.markdown("🧑‍🎓 Студент №1")

col1, col2, col3 = st.columns(3)

with col1:
    my_year_label = st.selectbox("Курс (студент №1)", list(YEARS.keys()), key="s3_my_year")
    my_year = YEARS[my_year_label]

with col2:
    my_dirs = load_directions_for_year(my_year)
    my_dir_labels = [o.label for o in my_dirs]
    my_dir_label = st.selectbox("Направление (студент №1)", my_dir_labels, key="s3_my_dir")
    my_dir_opt = my_dirs[my_dir_labels.index(my_dir_label)]
    my_up = my_dir_opt.params["up"]

with col3:
    _, my_groups, my_sems = load_groups_and_sems(my_up, my_year)
    my_group_names = [o.label for o in my_groups]
    my_group_label = st.selectbox("Группа (Студент №1)", my_group_names, key="s3_my_group")

my_group_opt = next(o for o in my_groups if o.label == my_group_label)
my_sem_labels = [o.label for o in my_sems]
my_sem_label = st.selectbox("Семестр (Студент №1)", my_sem_labels,
                            index=len(my_sem_labels) - 1, key="s3_my_sem")
my_sem_opt = next(o for o in my_sems if o.label == my_sem_label)

with st.spinner("Загружаем мои данные…"):
    df_my, meta_my = parse_group(
        my_up, my_year, my_group_opt.params["g"], my_sem_opt.params["s"], my_group_label
    )

my_students = df_my["ФИО"].dropna().tolist()
me_name = st.selectbox("Студент №1", my_students, key="s3_me")
row_me = df_my[df_my["ФИО"] == me_name].iloc[0]


# 2. Выбор для студента №1 — любой курс, направление, семестр
st.markdown("👤 Студент №2")

col1, col2, col3 = st.columns(3)

with col1:
    ot_year_label = st.selectbox("Курс (Студент №2)", list(YEARS.keys()), key="s3_ot_year")
    ot_year = YEARS[ot_year_label]

with col2:
    ot_dirs = load_directions_for_year(ot_year)
    ot_dir_labels = [o.label for o in ot_dirs]
    ot_dir_label = st.selectbox("Направление (Студент №2)", ot_dir_labels, key="s3_ot_dir")
    ot_dir_opt = ot_dirs[ot_dir_labels.index(ot_dir_label)]
    ot_up = ot_dir_opt.params["up"]

with col3:
    _, ot_groups, ot_sems = load_groups_and_sems(ot_up, ot_year)
    ot_group_names = [o.label for o in ot_groups]
    ot_group_label = st.selectbox("Группа (Студент №2)", ot_group_names, key="s3_ot_group")

ot_group_opt = next(o for o in ot_groups if o.label == ot_group_label)
ot_sem_labels = [o.label for o in ot_sems]
ot_sem_label = st.selectbox("Семестр (Студент №2)", ot_sem_labels,
                            index=len(ot_sem_labels) - 1, key="s3_ot_sem")
ot_sem_opt = next(o for o in ot_sems if o.label == ot_sem_label)

with st.spinner("Загружаем данные однокурсника…"):
    df_ot, meta_ot = parse_group(
        ot_up, ot_year, ot_group_opt.params["g"], ot_sem_opt.params["s"], ot_group_label
    )

ot_students = df_ot["ФИО"].dropna().tolist()
ot_default = next((s for s in ot_students if s != me_name), ot_students[0])
ot_name = st.selectbox("Студент №2", ot_students,
                       index=ot_students.index(ot_default), key="s3_ot")
row_ot = df_ot[df_ot["ФИО"] == ot_name].iloc[0]


# Сопоставление предметов
pairs = match_subjects(meta_my, meta_ot)
matched_a = {x[0] for x in pairs}
matched_b = {x[2] for x in pairs}

unmatched_a = [(m["short"], m["full"]) for m in meta_my if m["short"] not in matched_a]
unmatched_b = [(m["short"], m["full"]) for m in meta_ot if m["short"] not in matched_b]

# Ручное переопределение 
st.markdown("🔧 Ручное сопоставление (если автоматика ошиблась)")

manual_pairs = []
with st.expander("Добавить пару вручную", expanded=False):
    all_a = [m["short"] for m in meta_my]
    all_b = [m["short"] for m in meta_ot]
    if all_a and all_b:
        col_a, col_b = st.columns(2)
        with col_a:
            man_a = st.selectbox("Предмет студента №1", all_a, key="s3_man_a")
        with col_b:
            man_b = st.selectbox("Предмет студента №2", all_b, key="s3_man_b")
        if st.button("Добавить сопоставление"):
            st.session_state.setdefault("s3_manual", [])
            pair = (man_a, man_b)
            if pair not in st.session_state["s3_manual"]:
                st.session_state["s3_manual"].append(pair)
                st.success("Добавлено.")

    manual_pairs = st.session_state.get("s3_manual", [])
    if manual_pairs:
        st.write("Текущие ручные сопоставления:")
        for i, (a, b) in enumerate(manual_pairs):
            col1, col2 = st.columns([4, 1])
            col1.write(f"{a} ↔ {b}")
            if col2.button("Удалить", key=f"s3_del_{i}"):
                st.session_state["s3_manual"].pop(i)
                st.rerun()

# Пересчитываем с учётом ручных
if manual_pairs:
    pairs = match_subjects(meta_my, meta_ot, extra_pairs=manual_pairs)


# Таблица сравнения
comparison_rows = []
for a_short, a_full, b_short, b_full, score, source in pairs:
    my_val = row_me.get(a_short, pd.NA)
    ot_val = row_ot.get(b_short, pd.NA)
    my_val = float(my_val) if pd.notna(my_val) else None
    ot_val = float(ot_val) if pd.notna(ot_val) else None

    diff = None
    who = "—"
    if my_val is not None and ot_val is not None:
        diff = round(my_val - ot_val, 2)
        who = "Студент №1" if diff > 0 else ("Студент №2" if diff < 0 else "=")

    comparison_rows.append({
        "Предмет (Студент №1)": a_full or a_short,
        "Предмет (Студент №2)": b_full or b_short,
        "Студент №1": my_val,
        "Студент №2": ot_val,
        "Разница": diff,
        "Кто выше": who,
        "Метод": source,
        "Схожесть": score,
    })

cmp_df = pd.DataFrame(comparison_rows)

if cmp_df.empty:
    st.warning("Не удалось сопоставить ни одного предмета. Добавьте пары вручную выше.")
    st.stop()


# Сводные метрики для оценки успеваемости
st.subheader("Сводка")

common = cmp_df.dropna(subset=["Балл студента №1", "Балл студента №2"])
my_avg = common["Балл студента №1"].mean() if len(common) else 0
ot_avg = common["Балл студента №2"].mean() if len(common) else 0

c1, c2, c3, c4 = st.columns(4)
c1.metric("Сопоставлено предметов", len(cmp_df))
c2.metric("Студент №1: Средний по общим", f"{my_avg:.2f}")
c3.metric("Студент №2: Средний по общим", f"{ot_avg:.2f}",
          delta=f"{my_avg - ot_avg:+.2f} (Студент №1 − Студент №2)")
c4.metric("Студент №1: успеваемость выше / успеваемость ниже",
          f"{(cmp_df['Кто выше'] == 'Студент №1').sum()} / {(cmp_df['Кто выше'] == 'Студент №2').sum()}")


# Таблица по предметам
st.subheader("Сравнение по предметам")

def highlight_row(row):
    if row["Успеваемость выше"] == "Студент №1":
        return ["background-color: #d4edda"] * len(row)
    if row["Успеваемость выше"] == "Студент №2":
        return ["background-color: #f8d7da"] * len(row)
    return [""] * len(row)

st.dataframe(
    cmp_df.style.apply(highlight_row, axis=1),
    use_container_width=True, hide_index=True,
)


# График по предметам
st.subheader("Баллы по сопоставленным предметам")

labels = cmp_df["Предмет (Студент №1)"].fillna(cmp_df["Предмет (Студент №2)"]).tolist()

fig_bar = go.Figure()
fig_bar.add_trace(go.Bar(
    name="Студент №1", x=labels,
    y=cmp_df["Балл студента №1"].fillna(0).tolist(),
    marker_color="#2E86DE",
))
fig_bar.add_trace(go.Bar(
    name="Студент №2", x=labels,
    y=cmp_df["Балл студента №2"].fillna(0).tolist(),
    marker_color="#EE5A24",
))
fig_bar.update_layout(
    barmode="group", height=520,
    title=f"{me_name} vs {ot_name} — {my_sem_label} / {ot_sem_label}",
)
st.plotly_chart(fig_bar, use_container_width=True)


# Radar
fig_radar = go.Figure()
fig_radar.add_trace(go.Scatterpolar(
    r=cmp_df["Балл студента №1"].fillna(0).tolist(),
    theta=labels, fill="toself", name="Студент №1", line_color="#2E86DE",
))
fig_radar.add_trace(go.Scatterpolar(
    r=cmp_df["Балл студента №2"].fillna(0).tolist(),
    theta=labels, fill="toself", name="Студент №2", line_color="#EE5A24",
))
fig_radar.update_layout(
    polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
    height=520, title="Профиль успеваемости",
)
st.plotly_chart(fig_radar, use_container_width=True)


# Отладка
with st.expander("🔍 Отладка"):
    st.write("Студент №1:", me_name, "| группа:", my_group_label, "| семестр:", my_sem_label)
    st.write("Студент №2:", ot_name, "| группа:", ot_group_label, "| семестр:", ot_sem_label)
    st.write(f"Предметы студента №1 ({len(meta_my)}):", [m["short"] for m in meta_my])
    st.write(f"Предметы студента №2 ({len(meta_ot)}):", [m["short"] for m in meta_ot])
    st.write(f"Сопоставлено: {len(cmp_df)} пар")
    st.write("Несопоставленные у студента №1:", unmatched_a)
    st.write("Несопоставленные у студента №2:", unmatched_b)
