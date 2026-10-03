import io
import re
import time
import requests
import streamlit as st
import pandas as pd
import plotly.express as px
from bs4 import BeautifulSoup

import parser as p

# ============================================================
# НАСТРОЙКИ
# ============================================================
DEFAULT_DIRECTION_SUBSTR = "прикладная математика"
DEFAULT_GROUPS_COUNT = 2

# Текущий учебный год — от него считаем «курс»
CURRENT_ACADEMIC_YEAR = 2026
# ============================================================

st.set_page_config(page_title="БРС СПбГЭУ — сравнение групп", layout="wide")
st.title("📊 Сравнение успеваемости групп — БРС СПбГЭУ")


# ------------------------------------------------------------
# Утилиты
# ------------------------------------------------------------
def collect_filters(html: str):
    soup = BeautifulSoup(html, "html.parser")
    return [li.find("b").get_text(strip=True)
            for li in soup.select("div.filter > ul > li")
            if li.find("b")]


def fetch_with_fallback(params_dict):
    """Пробуем с g=all, потом без g. Возвращаем (html, рабочие_params)."""
    for variant in (params_dict,
                    {k: v for k, v in params_dict.items() if k != "g"}):
        try:
            html = p.fetch(variant)
        except Exception:
            continue
        if "Группа" in collect_filters(html):
            return html, variant
    return None, None


def course_from_group(group_name: str):
    """ПМ-2301 → 4 (если сейчас 2026/2027). None, если не распарсилось."""
    m = re.match(r"[A-Za-zА-Яа-я]+-(\d{2})\d{2}", group_name)
    if not m:
        return None
    year_short = int(m.group(1))
    year = 2000 + year_short
    course = CURRENT_ACADEMIC_YEAR - year + 1
    return course if 1 <= course <= 6 else None


def normalize_direction_name(label: str) -> str:
    """Убираем год и форму, чтобы сгруппировать направления одного типа."""
    s = label
    s = re.sub(r"\s*\(\s*(очная|очно-заочная|заочная)\s*\)", "", s, flags=re.I)
    s = re.sub(r"\s*\b20\d{2}\b\s*$", "", s)
    return s.strip()


# ------------------------------------------------------------
# 1. Базовая страница — список направлений
# ------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def load_base_html():
    return p.fetch({})


base_html = load_base_html()
all_directions = p.get_filter_options(base_html, "Направление")
all_directions = [o for o in all_directions if "up" in o.params]

if not all_directions:
    st.error("Сайт не вернул список направлений. Попробуйте позже.")
    st.stop()

# Группируем по «нормализованному» имени — под одним именем все up-ы
directions_grouped: dict[str, list] = {}
for o in all_directions:
    key = normalize_direction_name(o.label)
    directions_grouped.setdefault(key, []).append(o)

direction_names = list(directions_grouped.keys())


# ------------------------------------------------------------
# 2. Селектбокс «Направление»
# ------------------------------------------------------------
default_dir_idx = 0
for i, name in enumerate(direction_names):
    if DEFAULT_DIRECTION_SUBSTR in name.lower():
        default_dir_idx = i
        break

direction_label = st.selectbox(
    "Направление", direction_names, index=default_dir_idx,
)
direction_variants = directions_grouped[direction_label]

with st.expander("🔍 Отладка: up-ы выбранного направления"):
    for o in direction_variants:
        st.write(
            f"up=`{o.params.get('up','?')}` "
            f"y=`{o.params.get('y','?')}` "
            f"k=`{o.params.get('k','?')}` "
            f"f=`{o.params.get('f','?')}` — {o.label}"
        )


# ------------------------------------------------------------
# 3. Универсальный сбор групп по одному up
# ------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_groups_for_up(up_id: str, year, k: str, f: str):
    """
    Пробуем много вариантов запроса. Возвращаем:
      (html, used_params, filters_list, groups_list)
    """
    base = {
        "up":   up_id,
        "k":    k or "1",
        "f":    f or "1",
        "upp":  "all",
        "sort": "fio",
        "ball": "hide",
    }

    variants = []

    # 1) с y + g=all
    if year:
        v = dict(base); v["y"] = year; v["g"] = "all"; variants.append(v)
        # 2) с y без g
        variants.append(dict(base, y=year))
    # 3) без y + g=all
    v = dict(base); v["g"] = "all"; variants.append(v)
    # 4) без y без g
    variants.append(dict(base))
    # 5) с y + s=1..8 + g=all
    if year:
        for s in ("1", "2", "3", "4", "5", "6", "7", "8"):
            variants.append(dict(base, y=year, s=s, g="all"))
    # 6) без y + s=1..8 + g=all
    for s in ("1", "2", "3", "4", "5", "6", "7", "8"):
        variants.append(dict(base, s=s, g="all"))

    for v in variants:
        try:
            html = p.fetch(v)
        except Exception:
            continue
        filters = collect_filters(html)
        if "Группа" in filters:
            groups = [
                o.label for o in p.get_filter_options(html, "Группа")
                if o.label not in ("Не выбрано", "Все группы")
            ]
            if groups:
                return html, v, filters, groups

    # Ничего не сработало — вернём последний ответ для диагностики
    try:
        html = p.fetch(variants[-1])
        filters = collect_filters(html)
    except Exception:
        html, filters = None, []
    return None, None, filters, []


# Собираем группы по всем up-ам направления
all_groups: dict[str, dict] = {}
group_debug = []

progress = st.progress(0.0, text="Собираем группы по всем годам…")
for i, up_opt in enumerate(direction_variants):
    up_id = up_opt.params.get("up")
    year = up_opt.params.get("y")
    if not year:
        m = re.search(r"\b(20\d{2})\b", up_opt.label)
        if m:
            year = m.group(1)
    k = up_opt.params.get("k", "1")
    f = up_opt.params.get("f", "1")

    progress.progress((i + 1) / len(direction_variants),
                      text=f"up={up_id}…")

    html_up, used_up, filters, names = fetch_groups_for_up(up_id, year, k, f)

    url = None
    if used_up:
        url = requests.Request("GET", p.BASE, params=used_up).prepare().url

    group_debug.append({
        "up": up_id,
        "year": year,
        "url": url,
        "filters": filters,
        "groups": names,
    })

    if not names:
        continue

    for name in names:
        # найдём опцию, чтобы взять её g
        opt = next(
            (o for o in p.get_filter_options(html_up, "Группа") if o.label == name),
            None,
        )
        if opt is None:
            continue
        all_groups.setdefault(name, {
            "g":  opt.params.get("g"),
            "up": up_id,
            "y":  year,
            "k":  k,
            "f":  f,
        })

    time.sleep(0.3)

progress.empty()

with st.expander("🔍 Отладка: что вернул каждый up", expanded=True):
    for info in group_debug:
        st.markdown(f"**up={info['up']}** (year={info['year']})")
        if info["url"]:
            st.code(info["url"], language="text")
        st.write("Фильтры:", info["filters"])
        st.write("Группы:", info["groups"] or "—")

if not all_groups:
    st.error(
        "Не удалось собрать ни одной группы. Смотрите отладочную панель — "
        "там видно, какие фильтры и URL вернул сайт для каждого up."
    )
    st.stop()


# ------------------------------------------------------------
# 4. Мультиселект групп
# ------------------------------------------------------------
def sort_key(name):
    course = course_from_group(name) or 99
    return (-course, name)


group_names_all = sorted(all_groups.keys(), key=sort_key)

st.success(
    f"Найдено групп: **{len(group_names_all)}** — "
    f"{', '.join(group_names_all)}"
)

selected_groups = st.multiselect(
    "Группы для сравнения",
    options=group_names_all,
    default=group_names_all[:DEFAULT_GROUPS_COUNT],
)

if not selected_groups:
    st.warning("Выберите хотя бы одну группу.")
    st.stop()

courses_info = []
for gname in selected_groups:
    c = course_from_group(gname)
    courses_info.append(f"{gname} → {c} курс" if c else f"{gname} → курс не определён")
st.caption(" | ".join(courses_info))


# ------------------------------------------------------------
# 5. Семестры: берём из ответа по первой выбранной группе
# ------------------------------------------------------------
first_group = selected_groups[0]
fg = all_groups[first_group]

params_for_sem = {
    "up":   fg["up"],
    "y":    fg["y"],
    "k":    fg["k"],
    "f":    fg["f"],
    "g":    fg["g"],
    "upp":  "all",
    "sort": "fio",
    "ball": "hide",
}

html_sem, used_sem = fetch_with_fallback(params_for_sem)
if html_sem is None:
    st.error(f"Не удалось получить страницу для группы {first_group}.")
    st.stop()

semester_options = p.get_filter_options(html_sem, "Семестр")
current_sem = p.get_selected_text(html_sem, "Семестр")

with st.expander("🔍 Отладка: семестры выбранной группы", expanded=False):
    st.write("Параметры:", used_sem)
    st.write("Фильтры:", collect_filters(html_sem))
    st.write("Доступные семестры:", [o.label for o in semester_options])
    st.write("Текущий:", current_sem)

sem_labels = [o.label for o in semester_options]
default_sem = [current_sem] if current_sem in sem_labels else (sem_labels[-1:] if sem_labels else [])

selected_sems = st.multiselect(
    "Семестры",
    options=sem_labels,
    default=default_sem,
    help="Список семестров определяется первой выбранной группой.",
)

if not selected_sems:
    st.warning("Выберите хотя бы один семестр.")
    st.stop()


# ------------------------------------------------------------
# 6. Скачиваем данные: группы × семестры
# ------------------------------------------------------------
total = len(selected_groups) * len(selected_sems)
progress = st.progress(0.0, text="Загружаем данные…")
step = 0

all_rows = []
subject_meta = None

for gname in selected_groups:
    ginfo = all_groups[gname]
    for sem_label in selected_sems:
        step += 1
        progress.progress(step / total, text=f"{gname} / {sem_label}")

        # семестр: id берём из опции, если она есть,
        # но у разных групп нумерация семестров совпадает
        sem_opt = next((o for o in semester_options if o.label == sem_label), None)
        if not sem_opt:
            continue
        s_id = sem_opt.params.get("s")

        params_g = {
            "up":   ginfo["up"],
            "y":    ginfo["y"],
            "k":    ginfo["k"],
            "f":    ginfo["f"],
            "g":    ginfo["g"],
            "s":    s_id,
            "upp":  "all",
            "sort": "fio",
            "ball": "hide",
        }

        try:
            html_g = p.fetch(params_g)
        except Exception as e:
            st.warning(f"{gname} / {sem_label}: {e}")
            continue

        if subject_meta is None:
            subject_meta = p.parse_subjects(html_g)

        rows = p.parse_students(html_g, group_name=gname)
        for r in rows:
            r["Семестр"] = sem_label
        all_rows.extend(rows)
        time.sleep(0.3)

progress.empty()

if not all_rows or subject_meta is None:
    st.error("Данные не получены.")
    st.stop()

df = pd.DataFrame(all_rows)
subject_shorts = [s["short"] for s in subject_meta]
for col in subject_shorts + ["Сумма"]:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col].replace("", pd.NA), errors="coerce")


# ------------------------------------------------------------
# 7. Сводка
# ------------------------------------------------------------
st.subheader("Сводка по группам и семестрам")

summary = (
    df.groupby(["Семестр", "Группа"])
    .agg(
        Студентов=("ФИО", "count"),
        Средний_балл=("Сумма", "mean"),
        Медиана=("Сумма", "median"),
        Макс=("Сумма", "max"),
        Мин=("Сумма", "min"),
    )
    .round(2)
    .reset_index()
)
st.dataframe(summary, use_container_width=True)


# ------------------------------------------------------------
# 8. Графики
# ------------------------------------------------------------
st.subheader("Средний суммарный балл: группы × семестры")
fig1 = px.bar(
    summary, x="Группа", y="Средний_балл", color="Семестр",
    barmode="group", text="Средний_балл",
)
fig1.update_traces(textposition="outside")
fig1.update_layout(height=500)
st.plotly_chart(fig1, use_container_width=True)

if len(selected_sems) > 1:
    st.subheader("Динамика по семестрам")
    fig2 = px.line(
        summary, x="Семестр", y="Средний_балл", color="Группа",
        markers=True,
    )
    fig2.update_layout(height=450)
    st.plotly_chart(fig2, use_container_width=True)


# ------------------------------------------------------------
# 9. По предметам
# ------------------------------------------------------------
st.subheader("Средний балл по предметам")
sem_for_subjects = st.selectbox(
    "Семестр для сравнения по предметам",
    options=selected_sems,
    index=len(selected_sems) - 1,
)
df_sem = df[df["Семестр"] == sem_for_subjects]
subj_means = df_sem.groupby("Группа")[subject_shorts].mean().round(2).reset_index()
fig3 = px.bar(
    subj_means.melt(id_vars="Группа", var_name="Предмет", value_name="Средний балл"),
    x="Предмет", y="Средний балл", color="Группа", barmode="group",
    title=f"Средний балл по предметам — {sem_for_subjects}",
)
fig3.update_layout(height=500)
st.plotly_chart(fig3, use_container_width=True)
st.dataframe(subj_means, use_container_width=True)


# ------------------------------------------------------------
# 10. Полная таблица и экспорт
# ------------------------------------------------------------
with st.expander("📋 Полная таблица студентов"):
    st.dataframe(df, use_container_width=True)

st.subheader("Экспорт")
col_x, col_y = st.columns(2)
with col_x:
    csv_bytes = df.to_csv(index=False, sep=";", encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button("⬇️ Скачать CSV", data=csv_bytes,
                       file_name="students_compare.csv", mime="text/csv")
with col_y:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Студенты", index=False)
        summary.to_excel(writer, sheet_name="Сводка", index=False)
        subj_means.to_excel(writer, sheet_name="По предметам", index=False)
    st.download_button("⬇️ Скачать Excel", data=buf.getvalue(),
                       file_name="students_compare.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
