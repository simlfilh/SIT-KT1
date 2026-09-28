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
DEFAULT_COURSE        = "4 курс"
DEFAULT_SEMESTER      = "6 семестр"
DEFAULT_GROUPS_COUNT  = 2

# «Затравка» — известный рабочий up, чтобы получить полный HTML
# с фильтрами «Семестр», «Группа» и т.д.
SEED_PARAMS = {
    "up":   "13613",   # Прикладная математика и информатика, 2023
    "y":    "2023",
    "k":    "1",
    "f":    "1",
    "s":    "6",
    "uy":   "4",
    "g":    "13511",   # ПМ-2301
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


# ------------------------------------------------------------
# 1. Затравка: получаем HTML, из которого можно взять
#    полноценный список направлений (с up, y, uy, s)
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
    st.error("Сайт не вернул список направлений. Попробуйте позже.")
    st.stop()

with st.expander("🔍 Отладка: направления (из затравки)", expanded=False):
    for i, o in enumerate(directions):
        st.write(
            f"{i}: up=`{o.params.get('up','?')}` "
            f"y=`{o.params.get('y','?')}` "
            f"uy=`{o.params.get('uy','?')}` "
            f"s=`{o.params.get('s','?')}` — {o.label}"
        )


# ------------------------------------------------------------
# 2. Выбор направления / курса / семестра
# ------------------------------------------------------------
courses   = p.get_filter_options(seed_html, "Курс")
semesters = p.get_filter_options(seed_html, "Семестр")

col1, col2, col3 = st.columns(3)

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

with col3:
    sem_labels = [o.label for o in semesters] or [DEFAULT_SEMESTER]
    sem_label = st.selectbox(
        "Семестр", sem_labels,
        index=find_index(sem_labels, DEFAULT_SEMESTER),
    )
    sem_opt = next((o for o in semesters if o.label == sem_label), None)


# ------------------------------------------------------------
# 3. Собираем рабочие параметры из выбранного направления
# ------------------------------------------------------------
params = dict(direction_opt.params)     # здесь уже есть up, y, k, f, s, uy
params["g"]    = "all"
params["upp"]  = "all"
params["sort"] = "fio"
params["ball"] = "hide"

# Накладываем выбранный курс (может поменять y) и семестр (поменяет s)
if course_opt and "y" in course_opt.params:
    params["y"] = course_opt.params["y"]
if sem_opt and "s" in sem_opt.params:
    params["s"] = sem_opt.params["s"]

with st.expander("🔍 Отладка: параметры запроса", expanded=True):
    st.json(params)
    prepared = requests.Request("GET", p.BASE, params=params).prepare()
    st.code(prepared.url, language="text")


# ------------------------------------------------------------
# 4. Запрос — пробуем g=all, если не выйдет — без g
# ------------------------------------------------------------
def fetch_with_fallback(params_dict):
    for variant in (params_dict,
                    {k: v for k, v in params_dict.items() if k != "g"}):
        try:
            html = p.fetch(variant)
        except Exception:
            continue
        if "Группа" in collect_filters(html):
            return html, variant
    return None, None


html_all, used_params = fetch_with_fallback(params)

with st.expander("🔍 Отладка: фильтры в ответе", expanded=True):
    if html_all:
        st.write(collect_filters(html_all))
    else:
        st.error("Сайт не вернул страницу с фильтром «Группа».")

if html_all is None:
    st.warning(
        "Для выбранного направления/курса/семестра сайт не отдаёт список групп. "
        "Попробуйте другое направление в селектбоксе."
    )
    st.stop()


# ------------------------------------------------------------
# 5. Достаём группы
# ------------------------------------------------------------
group_options = {o.label: o for o in p.get_filter_options(html_all, "Группа")}
group_names = [n for n in group_options if n not in ("Не выбрано", "Все группы")]

if not group_names:
    st.warning("Фильтр «Группа» есть, но список групп пуст.")
    st.stop()

st.info(f"Найдено групп: **{len(group_names)}** — {', '.join(group_names)}")


# ------------------------------------------------------------
# 6. Мультивыбор групп
# ------------------------------------------------------------
selected_groups = st.multiselect(
    "Группы для сравнения",
    options=group_names,
    default=group_names[:DEFAULT_GROUPS_COUNT],
)
if not selected_groups:
    st.warning("Выберите хотя бы одну группу.")
    st.stop()


# ------------------------------------------------------------
# 7. Скачиваем данные по каждой группе
# ------------------------------------------------------------
progress = st.progress(0.0, text="Загружаем данные групп…")
all_rows = []
subject_meta = None

for i, gname in enumerate(selected_groups):
    gopt = group_options.get(gname)
    if not gopt:
        continue
    params_g = dict(used_params)
    params_g.update(gopt.params)
    params_g["upp"]  = "all"
    params_g["sort"] = "fio"
    params_g["ball"] = "hide"

    try:
        html_g = p.fetch(params_g)
    except Exception as e:
        st.warning(f"Не удалось загрузить {gname}: {e}")
        continue

    if subject_meta is None:
        subject_meta = p.parse_subjects(html_g)

    all_rows.extend(p.parse_students(html_g, group_name=gname))
    progress.progress((i + 1) / len(selected_groups), text=f"Загружено: {gname}")
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
# 8. Сводка по группам
# ------------------------------------------------------------
st.subheader("Сводка по группам")

summary_rows = []
for gname, gdf in df.groupby("Группа"):
    summary_rows.append({
        "Группа": gname,
        "Студентов": len(gdf),
        "Средний суммарный балл": round(gdf["Сумма"].mean(), 2),
        "Медиана": round(gdf["Сумма"].median(), 2),
        "Макс.": round(gdf["Сумма"].max(), 2),
        "Мин.": round(gdf["Сумма"].min(), 2),
    })

summary_df = pd.DataFrame(summary_rows).sort_values(
    "Средний суммарный балл", ascending=False
)
st.dataframe(summary_df, use_container_width=True)


# ------------------------------------------------------------
# 9. Графики
# ------------------------------------------------------------
col_a, col_b = st.columns(2)

with col_a:
    fig1 = px.bar(summary_df, x="Группа", y="Средний суммарный балл",
                  text="Средний суммарный балл", color="Группа",
                  title="Средний суммарный балл по группам")
    fig1.update_traces(textposition="outside")
    fig1.update_layout(showlegend=False, height=420)
    st.plotly_chart(fig1, use_container_width=True)

with col_b:
    fig2 = px.box(df, x="Группа", y="Сумма", color="Группа", points="all",
                  title="Распределение суммарного балла")
    fig2.update_layout(showlegend=False, height=420)
    st.plotly_chart(fig2, use_container_width=True)


st.subheader("Средний балл по предметам")
subj_means = df.groupby("Группа")[subject_shorts].mean().round(2).reset_index()
fig3 = px.bar(
    subj_means.melt(id_vars="Группа", var_name="Предмет", value_name="Средний балл"),
    x="Предмет", y="Средний балл", color="Группа", barmode="group",
    title="Средний балл по предметам",
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
        summary_df.to_excel(writer, sheet_name="Сводка", index=False)
        subj_means.to_excel(writer, sheet_name="По предметам", index=False)
    st.download_button("⬇️ Скачать Excel", data=buf.getvalue(),
                       file_name="students_compare.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
