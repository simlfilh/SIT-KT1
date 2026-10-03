import io
import time
import requests
import streamlit as st
import pandas as pd
import plotly.express as px
from bs4 import BeautifulSoup

import parser as p

# ============================================================
# НАСТРОЙКИ ПО УМОЛЧАНИЮ
# ============================================================
DEFAULT_COURSE      = "4 курс"
DEFAULT_GROUPS_COUNT = 2

# «Затравка» — рабочий up, чтобы получить HTML с фильтрами
# ВАЖНО: здесь НЕ фиксируем s и uy — их подставит сайт сам
SEED_PARAMS = {
    "up":   "13613",
    "y":    "2023",
    "k":    "1",
    "f":    "1",
    "g":    "all",
    "upp":  "all",
    "sort": "fio",
    "ball": "hide",
}
# ============================================================

st.set_page_config(page_title="БРС СПбГЭУ — сравнение групп", layout="wide")
st.title("📊 Сравнение успеваемости групп — БРС СПбГЭУ")


# ------------------------------------------------------------
# Вспомогательные функции
# ------------------------------------------------------------
def find_index(labels, target, default=0):
    try:
        return labels.index(target)
    except ValueError:
        return default


def collect_filters(html: str):
    soup = BeautifulSoup(html, "html.parser")
    return [li.find("b").get_text(strip=True)
            for li in soup.select("div.filter > ul > li")
            if li.find("b")]


def fetch_with_fallback(params_dict):
    """Пробуем с g=all, потом без g. Возвращаем HTML и рабочие params."""
    for variant in (params_dict,
                    {k: v for k, v in params_dict.items() if k != "g"}):
        try:
            html = p.fetch(variant)
        except Exception:
            continue
        if "Группа" in collect_filters(html):
            return html, variant
    return None, None


# ------------------------------------------------------------
# 1. Затравка: получаем HTML для фильтра «Направление»
# ------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def load_seed_html():
    return p.fetch(SEED_PARAMS)


@st.cache_data(ttl=3600, show_spinner=False)
def load_base_html():
    return p.fetch({})


try:
    seed_html = load_seed_html()
except Exception as e:
    st.error(f"Не удалось загрузить сайт: {e}")
    st.stop()

directions = p.get_filter_options(seed_html, "Направление")
if not directions:
    directions = p.get_filter_options(load_base_html(), "Направление")
directions = [o for o in directions if "up" in o.params]

if not directions:
    st.error("Сайт не вернул список направлений.")
    st.stop()

courses = p.get_filter_options(seed_html, "Курс")


# ------------------------------------------------------------
# 2. Селектбоксы: направление и курс
# ------------------------------------------------------------
col1, col2 = st.columns(2)

with col1:
    dir_labels = [o.label for o in directions]
    default_dir_idx = 0
    for i, lbl in enumerate(dir_labels):
        if "прикладная математика" in lbl.lower():
            default_dir_idx = i
            break
    direction_label = st.selectbox("Направление", dir_labels, index=default_dir_idx)
    direction_opt = directions[dir_labels.index(direction_label)]

with col2:
    course_labels = [o.label for o in courses] or [DEFAULT_COURSE]
    course_label = st.selectbox(
        "Курс", course_labels,
        index=find_index(course_labels, DEFAULT_COURSE),
    )
    course_opt = next((o for o in courses if o.label == course_label), None)


# ------------------------------------------------------------
# 3. Собираем параметры «направление + курс» и делаем
#    промежуточный запрос — чтобы узнать доступные семестры
#    ИМЕННО для этого курса.
# ------------------------------------------------------------
params_for_course = dict(direction_opt.params)
params_for_course["upp"]  = "all"
params_for_course["sort"] = "fio"
params_for_course["ball"] = "hide"

if course_opt and "y" in course_opt.params:
    params_for_course["y"] = course_opt.params["y"]

# g=all может не сработать — используем fallback
html_course, used_params_course = fetch_with_fallback(params_for_course)

if html_course is None:
    st.warning(
        "Сайт не вернул страницу с фильтром «Группа» для выбранного "
        "направления и курса. Попробуйте другое направление."
    )
    st.stop()

# Достаём список семестров для этого курса
semester_options = p.get_filter_options(html_course, "Семестр")
# Определяем текущий (выбранный) семестр
current_sem = p.get_selected_text(html_course, "Семестр")

with st.expander("🔍 Отладка: что вернул сайт для выбранного курса", expanded=False):
    st.write("Параметры запроса:", used_params_course)
    st.write("Фильтры:", collect_filters(html_course))
    st.write(f"Доступные семестры ({len(semester_options)}):",
             [o.label for o in semester_options])
    st.write(f"Текущий семестр на странице: {current_sem!r}")


# ------------------------------------------------------------
# 4. Выбор семестров (мультивыбор)
# ------------------------------------------------------------
sem_labels = [o.label for o in semester_options]

# По умолчанию — текущий семестр, если он есть в списке
default_sem = []
if current_sem and current_sem in sem_labels:
    default_sem = [current_sem]
elif sem_labels:
    default_sem = [sem_labels[-1]]

selected_sems = st.multiselect(
    "Семестры (можно выбрать несколько)",
    options=sem_labels,
    default=default_sem,
    help="Для выбранного курса сайт показывает только доступные семестры. "
         "Обычно это 2 семестра (например, 5 и 6 для 3 курса).",
)

if not selected_sems:
    st.warning("Выберите хотя бы один семестр.")
    st.stop()


# ------------------------------------------------------------
# 5. Достаём группы (из ответа для первого выбранного семестра)
# ------------------------------------------------------------
# Нам нужен HTML с группами для конкретного семестра
sem_opt_first = next(
    (o for o in semester_options if o.label == selected_sems[0]),
    None,
)
params_first = dict(used_params_course)
if sem_opt_first and "s" in sem_opt_first.params:
    params_first["s"] = sem_opt_first.params["s"]

html_first, used_params_first = fetch_with_fallback(params_first)
if html_first is None:
    st.warning("Сайт не вернул страницу с группами.")
    st.stop()

group_options = {o.label: o for o in p.get_filter_options(html_first, "Группа")}
group_names = [n for n in group_options if n not in ("Не выбрано", "Все группы")]

if not group_names:
    st.warning("Список групп пуст.")
    st.stop()

st.info(f"Найдено групп: **{len(group_names)}** — {', '.join(group_names)}")

selected_groups = st.multiselect(
    "Группы для сравнения",
    options=group_names,
    default=group_names[:DEFAULT_GROUPS_COUNT],
)
if not selected_groups:
    st.warning("Выберите хотя бы одну группу.")
    st.stop()


# ------------------------------------------------------------
# 6. Скачиваем данные: для каждого семестра × каждой группы
# ------------------------------------------------------------
total_steps = len(selected_sems) * len(selected_groups)
progress = st.progress(0.0, text="Загружаем данные…")

all_rows = []
subject_meta = None
step = 0

for sem_label in selected_sems:
    sem_opt = next((o for o in semester_options if o.label == sem_label), None)
    if not sem_opt:
        continue
    s_id = sem_opt.params.get("s")

    for gname in selected_groups:
        step += 1
        progress.progress(step / total_steps,
                          text=f"Семестр {sem_label} — группа {gname}")

        gopt = group_options.get(gname)
        if not gopt:
            continue

        # Базовые параметры + s + g
        params_g = dict(direction_opt.params)     # up, y, k, f, uy
        params_g["s"]    = s_id
        params_g["g"]    = gopt.params.get("g")
        params_g["upp"]  = "all"
        params_g["sort"] = "fio"
        params_g["ball"] = "hide"
        # курс мог поменять y
        if course_opt and "y" in course_opt.params:
            params_g["y"] = course_opt.params["y"]

        try:
            html_g = p.fetch(params_g)
        except Exception as e:
            st.warning(f"{sem_label} / {gname}: {e}")
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
# 7. Сводка: средний балл по (семестр, группа)
# ------------------------------------------------------------
st.subheader("Сводка по семестрам и группам")

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
# 8. Графики: средний балл по группам в каждом семестре
# ------------------------------------------------------------
st.subheader("Средний суммарный балл: группы × семестры")

fig1 = px.bar(
    summary, x="Группа", y="Средний_балл", color="Семестр",
    barmode="group",
    text="Средний_балл",
    title="Средний суммарный балл по группам и семестрам",
)
fig1.update_traces(textposition="outside")
fig1.update_layout(height=500)
st.plotly_chart(fig1, use_container_width=True)


# ------------------------------------------------------------
# 9. Динамика по семестрам (линия)
# ------------------------------------------------------------
if len(selected_sems) > 1:
    st.subheader("Динамика среднего балла по семестрам")
    fig2 = px.line(
        summary, x="Семестр", y="Средний_балл", color="Группа",
        markers=True,
        title="Как менялся средний балл группы от семестра к семестру",
    )
    fig2.update_layout(height=450)
    st.plotly_chart(fig2, use_container_width=True)


# ------------------------------------------------------------
# 10. Сравнение по предметам (с учётом семестра)
# ------------------------------------------------------------
st.subheader("Средний балл по предметам")

# Выбор семестра для графика по предметам
sem_for_subjects = st.selectbox(
    "Семестр для сравнения по предметам",
    options=selected_sems,
    index=len(selected_sems) - 1,
)
df_sem = df[df["Семестр"] == sem_for_subjects]

subj_means = (
    df_sem.groupby("Группа")[subject_shorts].mean().round(2).reset_index()
)
fig3 = px.bar(
    subj_means.melt(id_vars="Группа", var_name="Предмет", value_name="Средний балл"),
    x="Предмет", y="Средний балл", color="Группа", barmode="group",
    title=f"Средний балл по предметам — {sem_for_subjects}",
)
fig3.update_layout(height=500)
st.plotly_chart(fig3, use_container_width=True)
st.dataframe(subj_means, use_container_width=True)


# ------------------------------------------------------------
# 11. Полная таблица и экспорт
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
