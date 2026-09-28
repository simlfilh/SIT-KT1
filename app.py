import io
import time
import requests
import streamlit as st
import pandas as pd
import plotly.express as px
from bs4 import BeautifulSoup

import parser as p

# ============================================================
# НАСТРОЙКИ ПО УМОЛЧАНИЮ — меняйте здесь под себя
# ============================================================
DEFAULT_DIRECTION_SUBSTR = "Прикладная математика"
DEFAULT_COURSE           = "4 курс"
DEFAULT_SEMESTER         = "6 семестр"
DEFAULT_GROUPS_COUNT     = 2   # сколько групп выбрать по умолчанию
# ============================================================

st.set_page_config(page_title="БРС СПбГЭУ — сравнение групп", layout="wide")

st.title("📊 Сравнение успеваемости групп — БРС СПбГЭУ")


# ------------------------------------------------------------
# Утилиты для дефолтных значений
# ------------------------------------------------------------
def find_default_index(labels, target):
    try:
        return labels.index(target)
    except ValueError:
        return 0


def find_default_index_by_substr(labels, substr):
    for i, lbl in enumerate(labels):
        if substr.lower() in lbl.lower():
            return i
    return 0


# ------------------------------------------------------------
# 1. Загрузка базовой страницы и фильтров
# ------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def load_base_html():
    return p.fetch({})


try:
    base_html = load_base_html()
except Exception as e:
    st.error(f"Не удалось загрузить сайт: {e}")
    st.stop()

directions = p.get_filter_options(base_html, "Направление")
with st.expander("🔍 Все направления (для отладки)"):
    for i, o in enumerate(directions):
        up_id = o.params.get("up", "?")
        st.write(f"{i}: up={up_id} — {o.label}")
semesters  = p.get_filter_options(base_html, "Семестр")
courses    = p.get_filter_options(base_html, "Курс")

if not directions:
    st.error("Не удалось получить список направлений. Проверьте доступность сайта.")
    st.stop()


# ------------------------------------------------------------
# 2. Выбор параметров
# ------------------------------------------------------------
col1, col2, col3 = st.columns(3)

with col1:
    direction_labels = [o.label for o in directions]
    default_dir_idx = find_default_index_by_substr(direction_labels, DEFAULT_DIRECTION_SUBSTR)
    direction_label = st.selectbox("Направление", direction_labels, index=default_dir_idx)
    direction_opt = directions[direction_labels.index(direction_label)]

with col2:
    course_labels = [o.label for o in courses] or [DEFAULT_COURSE]
    default_course_idx = find_default_index(course_labels, DEFAULT_COURSE)
    course_label = st.selectbox("Курс", course_labels, index=default_course_idx)
    course_opt = next((o for o in courses if o.label == course_label), None)

with col3:
    sem_labels = [o.label for o in semesters] or [DEFAULT_SEMESTER]
    default_sem_idx = find_default_index(sem_labels, DEFAULT_SEMESTER)
    sem_label = st.selectbox("Семестр", sem_labels, index=default_sem_idx)
    sem_opt = next((o for o in semesters if o.label == sem_label), None)


# ------------------------------------------------------------
# 3. Собираем параметры «базового» запроса (направление + курс)
# ------------------------------------------------------------
# Берём значения из опций, но с явными дефолтами
def _pick(opt, key, default=None):
    if opt and opt.params and key in opt.params:
        return opt.params[key]
    return default

# Направление: up — обязательно
up_id = _pick(direction_opt, "up")
if not up_id:
    st.error("Не удалось определить ID направления. Выберите другое направление.")
    st.stop()

# Год: сначала из опции курса, потом из направления
year = _pick(course_opt, "y") or _pick(direction_opt, "y", "2023")

# Семестр: по умолчанию 6 (для 4 курса, как в вашем HTML).
# Если выбрали другой семестр — попробуем взять его из href.
sem_id = _pick(sem_opt, "s", "6")

# uy: «уровень/курс» — берём из направления, иначе 4
uy_id = _pick(direction_opt, "uy", "4")

params_base = {
    "y":    year,
    "k":    "1",
    "f":    "1",
    "up":   up_id,
    "s":    sem_id,
    "uy":   uy_id,
    "g":    "all",       # сначала пробуем «все группы»
    "upp":  "all",
    "sort": "fio",
    "ball": "hide",
}

with st.expander("🔍 Отладочная информация — базовый запрос"):
    st.json(params_base)
    prepared = requests.Request("GET", p.BASE, params=params_base).prepare()
    st.code(prepared.url, language="text")

try:
    html_all = p.fetch(params_base)
except Exception as e:
    st.error(f"Ошибка загрузки страницы: {e}")
    st.stop()


# ------------------------------------------------------------
# 4. Достаём список групп из фильтра
# ------------------------------------------------------------
group_options = {o.label: o for o in p.get_filter_options(html_all, "Группа")}
group_names = [name for name in group_options
               if name not in ("Не выбрано", "Все группы")]

# Если групп нет — попробуем взять их, отправив запрос без g
# (некоторые конфигурации сайта так делают)
if not group_names:
    params_no_g = {k: v for k, v in params_base.items() if k != "g"}
    with st.expander("⚠️ g=all не вернул групп — пробуем без g"):
        prepared = requests.Request("GET", p.BASE, params=params_no_g).prepare()
        st.code(prepared.url, language="text")
        try:
            html_all = p.fetch(params_no_g)
            group_options = {o.label: o for o in p.get_filter_options(html_all, "Группа")}
            group_names = [name for name in group_options
                           if name not in ("Не выбрано", "Все группы")]
        except Exception as e:
            st.warning(f"Не удалось: {e}")

if not group_names:
    st.warning("В выбранном направлении не найдено ни одной группы.")
    st.info(
        "Проверьте отладочную панель: URL должен содержать up, y, k, f, s, uy. "
        "Если какого-то параметра нет — скажите, добавим."
    )
    # Показываем список фильтров, которые реально есть в HTML
    soup_dbg = BeautifulSoup(html_all, "html.parser")
    st.write("Фильтры в HTML:", [li.find("b").get_text(strip=True)
                                 for li in soup_dbg.select("div.filter > ul > li")
                                 if li.find("b")])
    st.stop()

st.info(f"Найдено групп: **{len(group_names)}** — {', '.join(group_names)}")


# ------------------------------------------------------------
# 5. Мультивыбор групп
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
# 6. Скачиваем данные по каждой группе
#    (каждый раз обновляем params_base параметрами из ссылки группы —
#     там лежат её g, uy, s, up, y)
# ------------------------------------------------------------
progress = st.progress(0.0, text="Загружаем данные групп...")
all_rows = []
subject_meta = None

for i, gname in enumerate(selected_groups):
    gopt = group_options.get(gname)
    if not gopt:
        st.warning(f"Не найдены параметры для группы {gname}")
        continue

    # Начинаем с базовых параметров и накладываем на них параметры из ссылки группы
    params_g = dict(params_base)
    params_g.update(gopt.params)

    # Гарантируем нужные значения, чтобы не проскочили «Не выбрано» и т.п.
    params_g["g"]    = gopt.params.get("g", params_g.get("g"))
    params_g["uy"]   = gopt.params.get("uy", params_g.get("uy"))
    params_g["s"]    = gopt.params.get("s",  params_g.get("s"))
    params_g["up"]   = gopt.params.get("up", params_g.get("up"))
    params_g["y"]    = gopt.params.get("y",  params_g.get("y"))
    params_g["k"]    = gopt.params.get("k",  params_g.get("k", "1"))
    params_g["f"]    = gopt.params.get("f",  params_g.get("f", "1"))
    params_g["upp"]  = "all"
    params_g["sort"] = "fio"
    params_g["ball"] = "hide"

    try:
        html_g = p.fetch(params_g)
    except Exception as e:
        st.warning(f"Не удалось загрузить группу {gname}: {e}")
        continue

    if subject_meta is None:
        subject_meta = p.parse_subjects(html_g)

    rows = p.parse_students(html_g, group_name=gname)
    all_rows.extend(rows)
    progress.progress((i + 1) / len(selected_groups), text=f"Загружено: {gname}")
    time.sleep(0.3)

progress.empty()
# ------------------------------------------------------------
# 7. Преобразование баллов в числа
# ------------------------------------------------------------
for col in subject_shorts + ["Сумма"]:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col].replace("", pd.NA), errors="coerce")


# ------------------------------------------------------------
# 8. Сводка по группам
# ------------------------------------------------------------
st.subheader("Сводка по группам")

summary = []
for gname, gdf in df.groupby("Группа"):
    summary.append({
        "Группа": gname,
        "Студентов": len(gdf),
        "Средний суммарный балл": round(gdf["Сумма"].mean(), 2),
        "Медиана суммарного балла": round(gdf["Сумма"].median(), 2),
        "Макс. балл": round(gdf["Сумма"].max(), 2),
        "Мин. балл": round(gdf["Сумма"].min(), 2),
        "Пустых оценок": int(gdf[subject_shorts].isna().sum().sum()),
    })

summary_df = pd.DataFrame(summary).sort_values("Средний суммарный балл", ascending=False)
st.dataframe(summary_df, use_container_width=True)


# ------------------------------------------------------------
# 9. Графики
# ------------------------------------------------------------
col_a, col_b = st.columns(2)

with col_a:
    fig1 = px.bar(
        summary_df, x="Группа", y="Средний суммарный балл",
        text="Средний суммарный балл",
        title="Средний суммарный балл по группам",
        color="Группа",
    )
    fig1.update_traces(textposition="outside")
    fig1.update_layout(showlegend=False, height=420)
    st.plotly_chart(fig1, use_container_width=True)

with col_b:
    fig2 = px.box(
        df, x="Группа", y="Сумма", color="Группа", points="all",
        title="Распределение суммарного балла",
    )
    fig2.update_layout(showlegend=False, height=420)
    st.plotly_chart(fig2, use_container_width=True)


# ------------------------------------------------------------
# 10. Сравнение по предметам
# ------------------------------------------------------------
st.subheader("Средний балл по предметам")

subj_means = (
    df.groupby("Группа")[subject_shorts]
    .mean()
    .round(2)
    .reset_index()
)

fig3 = px.bar(
    subj_means.melt(id_vars="Группа", var_name="Предмет", value_name="Средний балл"),
    x="Предмет", y="Средний балл", color="Группа", barmode="group",
    title="Средний балл по предметам в разрезе групп",
)
fig3.update_layout(height=500)
st.plotly_chart(fig3, use_container_width=True)

st.dataframe(subj_means, use_container_width=True)


# ------------------------------------------------------------
# 11. Полная таблица
# ------------------------------------------------------------
with st.expander("📋 Полная таблица студентов"):
    st.dataframe(df, use_container_width=True)


# ------------------------------------------------------------
# 12. Экспорт
# ------------------------------------------------------------
st.subheader("Экспорт")

col_x, col_y = st.columns(2)

with col_x:
    csv_bytes = df.to_csv(index=False, sep=";", encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button(
        "⬇️ Скачать студентов (CSV)",
        data=csv_bytes,
        file_name="students_compare.csv",
        mime="text/csv",
    )

with col_y:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Студенты", index=False)
        summary_df.to_excel(writer, sheet_name="Сводка", index=False)
        subj_means.to_excel(writer, sheet_name="По предметам", index=False)
    st.download_button(
        "⬇️ Скачать Excel (3 листа)",
        data=buf.getvalue(),
        file_name="students_compare.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
