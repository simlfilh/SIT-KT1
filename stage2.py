import time
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from bs4 import BeautifulSoup

import parser as p

st.title("👤 Этап 2 — Сравнение студента с однокурсником")


# ============================================================
# ГОДЫ
# ============================================================
YEARS = {
    "2026 (1 курс)": "2026",
    "2025 (2 курс)": "2025",
    "2024 (3 курс)": "2024",
    "2023 (4 курс)": "2023",
}
# ============================================================


# ------------------------------------------------------------
# Утилиты
# ------------------------------------------------------------
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
    html, used = try_fetch([params])
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
    html, used = try_fetch([
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
def load_group_html(up_id: str, year: str, g_id: str, s_id: str):
    params = {
        "up": up_id, "y": year, "k": "1", "f": "1",
        "g": g_id, "s": s_id,
        "upp": "all", "sort": "fio", "ball": "hide",
    }
    return p.fetch(params)


def parse_group(up_id, year, g_id, s_id, group_name):
    """Скачивает и парсит группу в семестре. Возвращает df + meta предметов."""
    html = load_group_html(up_id, year, g_id, s_id)
    meta = p.parse_subjects(html)
    rows = p.parse_students(html, group_name=group_name)
    df = pd.DataFrame(rows)
    return df, meta


# ------------------------------------------------------------
# 1. Выбор курса и направления
# ------------------------------------------------------------
col1, col2 = st.columns(2)

with col1:
    year_label = st.selectbox("Курс", list(YEARS.keys()), key="s2_year")
    year = YEARS[year_label]

with col2:
    directions = load_directions_for_year(year)
    if not directions:
        st.warning("Не удалось получить направления.")
        st.stop()
    dir_labels = [o.label for o in directions]
    direction_label = st.selectbox("Направление", dir_labels, key="s2_dir")
    direction_opt = directions[dir_labels.index(direction_label)]
    up_id = direction_opt.params["up"]


# ------------------------------------------------------------
# 2. Группы и семестры направления
# ------------------------------------------------------------
html_dir, groups, sems = load_groups_and_sems(up_id, year)

if not groups:
    st.warning("Для выбранного направления и года нет групп.")
    st.stop()

if not sems:
    st.warning("Сайт не вернул список семестров для направления.")
    st.stop()

group_options = {o.label: o for o in groups}
group_names = list(group_options.keys())
sem_options = {o.label: o for o in sems}
sem_labels = list(sem_options.keys())
current_sem = p.get_selected_text(html_dir, "Семестр")
default_sem_idx = sem_labels.index(current_sem) if current_sem in sem_labels else len(sem_labels) - 1


# ------------------------------------------------------------
# 3. Выбор семестра для сравнения
# ------------------------------------------------------------
sem_label = st.selectbox(
    "Семестр для сравнения",
    options=sem_labels,
    index=default_sem_idx,
    key="s2_sem",
)
s_id = sem_options[sem_label].params.get("s")


# ------------------------------------------------------------
# 4. Выбор «Я» — группа + студент
# ------------------------------------------------------------
st.markdown("### 👤 Я")

col_my_grp, col_me = st.columns(2)

with col_my_grp:
    my_group = st.selectbox("Моя группа", group_names, key="s2_my_group")

with col_me:
    # Загружаем данные моей группы, чтобы получить список студентов
    my_g_id = group_options[my_group].params.get("g")
    with st.spinner("Загружаем мою группу…"):
        df_my, meta_my = parse_group(up_id, year, my_g_id, s_id, my_group)

    my_students = df_my["ФИО"].dropna().tolist()
    if not my_students:
        st.error("В моей группе нет студентов.")
        st.stop()
    me_name = st.selectbox("Я", my_students, key="s2_me")


# ------------------------------------------------------------
# 5. Выбор «Другой» — группа + студент
# ------------------------------------------------------------
st.markdown("### 🧑‍🎓 С кем сравнить")

col_other_grp, col_other = st.columns(2)

with col_other_grp:
    other_group = st.selectbox(
        "Группа однокурсника",
        group_names,
        index=(group_names.index(my_group) + 1) % len(group_names) if len(group_names) > 1 else 0,
        key="s2_other_group",
    )

with col_other:
    other_g_id = group_options[other_group].params.get("g")
    if other_g_id == my_g_id:
        df_other, meta_other = df_my, meta_my
    else:
        with st.spinner("Загружаем группу однокурсника…"):
            df_other, meta_other = parse_group(
                up_id, year, other_g_id, s_id, other_group
            )

    other_students = df_other["ФИО"].dropna().tolist()
    if not other_students:
        st.error("В группе однокурсника нет студентов.")
        st.stop()
    # По умолчанию — первый, кто не «я»
    other_default = next((s for s in other_students if s != me_name), other_students[0])
    other_default_idx = other_students.index(other_default)
    other_name = st.selectbox(
        "Студент", other_students, index=other_default_idx, key="s2_other",
    )


# ------------------------------------------------------------
# 6. Готовим данные для сравнения
# ------------------------------------------------------------
# Все предметы из обеих групп (объединение)
subject_shorts = sorted(set([s["short"] for s in meta_my] + [s["short"] for s in meta_other]))
meta_by_short = {}
for s in meta_my + meta_other:
    meta_by_short.setdefault(s["short"], s["full"])

# Приводим баллы к числам во всех df
SERVICE_COLS = {"Группа", "№", "ФИО", "stud_id", "Сумма", "Семестр"}


def normalize(df):
    df = df.copy()
    for c in df.columns:
        if c not in SERVICE_COLS:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


df_my = normalize(df_my)
df_other = normalize(df_other)

# Строки двух студентов
row_me = df_my[df_my["ФИО"] == me_name].iloc[0]
row_other = df_other[df_other["ФИО"] == other_name].iloc[0]

# Для каждого предмета вытаскиваем баллы
comparison_rows = []
for subj in subject_shorts:
    my_val = row_me.get(subj, pd.NA)
    ot_val = row_other.get(subj, pd.NA)
    my_val = float(my_val) if pd.notna(my_val) else None
    ot_val = float(ot_val) if pd.notna(ot_val) else None

    diff = None
    who = "—"
    if my_val is not None and ot_val is not None:
        diff = round(my_val - ot_val, 2)
        who = "Я" if diff > 0 else ("Он/Она" if diff < 0 else "=")
    comparison_rows.append({
        "Предмет": subj,
        "Расшифровка": meta_by_short.get(subj, ""),
        "Мой балл": my_val,
        "Его балл": ot_val,
        "Разница": diff,
        "Кто выше": who,
    })

cmp_df = pd.DataFrame(comparison_rows)


# ------------------------------------------------------------
# 7. Сводные метрики
# ------------------------------------------------------------
st.subheader("Сводка")

my_sum = row_me.get("Сумма", pd.NA)
ot_sum = row_other.get("Сумма", pd.NA)
my_sum = float(my_sum) if pd.notna(my_sum) else 0.0
ot_sum = float(ot_sum) if pd.notna(ot_sum) else 0.0

# Средний по предметам, где оба имеют балл
common = cmp_df.dropna(subset=["Мой балл", "Его балл"])
my_avg = common["Мой балл"].mean() if len(common) else 0.0
ot_avg = common["Его балл"].mean() if len(common) else 0.0

c1, c2, c3, c4 = st.columns(4)
c1.metric("Мой суммарный балл", f"{my_sum:.2f}")
c2.metric("Его суммарный балл", f"{ot_sum:.2f}", delta=f"{my_sum - ot_sum:+.2f} (я − он)")
c3.metric("Мой средний по общим", f"{my_avg:.2f}")
c4.metric("Его средний по общим", f"{ot_avg:.2f}", delta=f"{my_avg - ot_avg:+.2f}")


# ------------------------------------------------------------
# 8. Таблица по предметам
# ------------------------------------------------------------
st.subheader("Сравнение по предметам")
st.dataframe(
    cmp_df.style.apply(
        lambda row: [
            "background-color: #d4edda" if row["Кто выше"] == "Я"
            else ("background-color: #f8d7da" if row["Кто выше"] == "Он/Она" else "")
            for _ in row
        ],
        axis=1,
    ),
    use_container_width=True,
    hide_index=True,
)


# ------------------------------------------------------------
# 9. Место в группе
# ------------------------------------------------------------
st.subheader("Место в группе")

# По сумме баллов в текущем семестре
def place_in(df_local, name):
    tmp = df_local.dropna(subset=["Сумма"]).copy()
    tmp["Сумма"] = pd.to_numeric(tmp["Сумма"], errors="coerce")
    tmp = tmp.dropna(subset=["Сумма"]).sort_values("Сумма", ascending=False).reset_index(drop=True)
    if name not in tmp["ФИО"].values:
        return None, None
    pos = tmp.index[tmp["ФИО"] == name][0] + 1
    return pos, len(tmp)

pos_me, total_my = place_in(df_my, me_name)
pos_ot, total_ot = place_in(df_other, other_name)

c1, c2 = st.columns(2)
with c1:
    if pos_me:
        st.metric(f"Я в группе «{my_group}»", f"{pos_me} / {total_my}",
                  delta=f"из {total_my} студентов")
with c2:
    if pos_ot:
        st.metric(f"Он/Она в группе «{other_group}»", f"{pos_ot} / {total_ot}",
                  delta=f"из {total_ot} студентов")


# ------------------------------------------------------------
# 10. Графики
# ------------------------------------------------------------
st.subheader("Графики сравнения")

# 10.1 Столбики: я / он / средний по группе
avg_my = df_my.groupby("Группа")[subject_shorts].mean().mean().round(2) \
    if not df_my.empty else pd.Series()
avg_ot = df_other.groupby("Группа")[subject_shorts].mean().mean().round(2) \
    if not df_other.empty else pd.Series()
avg_by_subj_my = df_my[subject_shorts].mean().round(2)
avg_by_subj_ot = df_other[subject_shorts].mean().round(2)

fig_bar = go.Figure()
fig_bar.add_trace(go.Bar(
    name="Я", x=subject_shorts,
    y=[row_me.get(s, None) if pd.notna(row_me.get(s, None)) else 0 for s in subject_shorts],
    marker_color="#2E86DE",
))
fig_bar.add_trace(go.Bar(
    name="Он/Она", x=subject_shorts,
    y=[row_other.get(s, None) if pd.notna(row_other.get(s, None)) else 0 for s in subject_shorts],
    marker_color="#EE5A24",
))
fig_bar.add_trace(go.Bar(
    name=f"Средний по «{my_group}»", x=subject_shorts,
    y=[avg_by_subj_my.get(s, 0) for s in subject_shorts],
    marker_color="#BDC3C7", opacity=0.5,
))
fig_bar.add_trace(go.Bar(
    name=f"Средний по «{other_group}»", x=subject_shorts,
    y=[avg_by_subj_ot.get(s, 0) for s in subject_shorts],
    marker_color="#95A5A6", opacity=0.5,
))
fig_bar.update_layout(
    barmode="group", height=520,
    title=f"Баллы по предметам — {sem_label}",
    legend=dict(orientation="h", y=-0.15),
)
st.plotly_chart(fig_bar, use_container_width=True)


# 10.2 Radar
fig_radar = go.Figure()
fig_radar.add_trace(go.Scatterpolar(
    r=[row_me.get(s, 0) or 0 for s in subject_shorts],
    theta=subject_shorts,
    fill="toself", name="Я",
    line_color="#2E86DE",
))
fig_radar.add_trace(go.Scatterpolar(
    r=[row_other.get(s, 0) or 0 for s in subject_shorts],
    theta=subject_shorts,
    fill="toself", name="Он/Она",
    line_color="#EE5A24",
))
fig_radar.update_layout(
    polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
    showlegend=True, height=520,
    title="Профиль успеваемости (радар)",
)
st.plotly_chart(fig_radar, use_container_width=True)

# ------------------------------------------------------------
# 12. Экспорт
# ------------------------------------------------------------
st.subheader("Экспорт")

csv_bytes = cmp_df.to_csv(index=False, sep=";", encoding="utf-8-sig").encode("utf-8-sig")
st.download_button(
    "⬇️ Скачать сравнение (CSV)",
    data=csv_bytes,
    file_name=f"compare_{me_name}_vs_{other_name}.csv".replace(" ", "_"),
    mime="text/csv",
)


# ------------------------------------------------------------
# 13. Отладка
# ------------------------------------------------------------
with st.expander("🔍 Отладка"):
    st.write("up:", up_id, "| year:", year, "| semester:", s_id)
    st.write("Моя группа:", my_group, "| g_id:", my_g_id)
    st.write("Группа однокурсника:", other_group, "| g_id:", other_g_id)
    st.write("Все предметы (объединение):", subject_shorts)
    st.write("Строк в сравнении:", len(cmp_df))
