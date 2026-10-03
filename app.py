import streamlit as st
import pandas as pd

import parser as p

st.set_page_config(page_title="БРС СПбГЭУ — группы и баллы", layout="wide")
st.title("📋 Группы и баллы по предметам")


# ------------------------------------------------------------
# Утилиты
# ------------------------------------------------------------
def filters_of(html: str):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    return [li.find("b").get_text(strip=True)
            for li in soup.select("div.filter > ul > li")
            if li.find("b")]


def try_fetch(params_list):
    """Возвращает первый HTML, в котором есть фильтр «Группа»."""
    for params in params_list:
        try:
            html = p.fetch(params)
        except Exception:
            continue
        if "Группа" in filters_of(html):
            return html, params
    return None, None


# ------------------------------------------------------------
# 1. Список направлений
# ------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def load_base_html():
    return p.fetch({})


base_html = load_base_html()
directions = [o for o in p.get_filter_options(base_html, "Направление")
              if "up" in o.params]

if not directions:
    st.error("Сайт не вернул список направлений. Попробуйте позже.")
    st.stop()


# ------------------------------------------------------------
# 2. Селектбокс «Направление»
# ------------------------------------------------------------
dir_labels = [o.label for o in directions]
direction_label = st.selectbox("Направление", dir_labels)
direction_opt = directions[dir_labels.index(direction_label)]
up_id = direction_opt.params["up"]


# ------------------------------------------------------------
# 3. Список годов / курсов для выбранного направления
# ------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def load_courses_for_up(up_id: str):
    """Делаем запрос по up с g=all и достаём фильтр «Курс»."""
    html, used = try_fetch([
        {"up": up_id, "g": "all", "upp": "all", "sort": "fio", "ball": "hide"},
        {"up": up_id, "upp": "all", "sort": "fio", "ball": "hide"},
    ])
    if html is None:
        return None, None, []
    courses = p.get_filter_options(html, "Курс")
    return html, used, courses


with st.spinner("Загружаем список курсов…"):
    html_dir, used_dir, courses = load_courses_for_up(up_id)

if html_dir is None:
    st.error(
        f"Сайт не отдал страницу для направления «{direction_label}». "
        f"Возможно, рейтинг для него сейчас не ведётся."
    )
    st.stop()

if not courses:
    st.warning("Для этого направления не нашлось доступных курсов.")
    st.stop()

course_labels = [o.label for o in courses]
course_label = st.selectbox("Год поступления / курс", course_labels)
course_opt = courses[course_labels.index(course_label)]

with st.expander("🔍 Отладка: направление → курсы"):
    st.write("up:", up_id)
    st.write("Сработавшие параметры:", used_dir)
    st.write("Все курсы:", course_labels)
    st.write("Параметры выбранного курса:", course_opt.params)


# ------------------------------------------------------------
# 4. Список групп для выбранного курса
# ------------------------------------------------------------
# Параметры: up + y (из course_opt) + g=all
course_params = dict(course_opt.params)
course_params["up"] = up_id
course_params["upp"] = "all"
course_params["sort"] = "fio"
course_params["ball"] = "hide"

@st.cache_data(ttl=1800, show_spinner=False)
def load_groups_for_course(params_tuple):
    params = dict(params_tuple)
    html, used = try_fetch([
        {**params, "g": "all"},
        params,
    ])
    if html is None:
        return None, None, []
    groups = [o for o in p.get_filter_options(html, "Группа")
              if o.label not in ("Не выбрано", "Все группы")]
    return html, used, groups


with st.spinner("Загружаем список групп…"):
    html_c, used_c, groups = load_groups_for_course(
        tuple(sorted(course_params.items()))
    )

if html_c is None or not groups:
    st.warning(
        "Для выбранного курса сайт не вернул список групп. "
        "Попробуйте другой курс."
    )
    st.stop()

group_labels = [o.label for o in groups]
group_label = st.selectbox("Группа", group_labels)
group_opt = groups[group_labels.index(group_label)]

with st.expander("🔍 Отладка: курс → группы"):
    st.write("Параметры курса:", course_params)
    st.write("Все группы:", group_labels)
    st.write("Параметры выбранной группы:", group_opt.params)


# ------------------------------------------------------------
# 5. Загружаем данные группы
# ------------------------------------------------------------
# Собираем финальные параметры: up, y, g + сортировка/отображение
final_params = dict(course_params)
final_params.update(group_opt.params)   # здесь будет правильный g
final_params["up"]   = up_id
final_params["upp"]  = "all"
final_params["sort"] = "fio"
final_params["ball"] = "hide"

@st.cache_data(ttl=600, show_spinner=False)
def load_group_html(params_tuple):
    return p.fetch(dict(params_tuple))


with st.spinner(f"Загружаем данные {group_label}…"):
    try:
        html_g = load_group_html(tuple(sorted(final_params.items())))
    except Exception as e:
        st.error(f"Ошибка загрузки: {e}")
        st.stop()


# ------------------------------------------------------------
# 6. Парсим студентов и баллы
# ------------------------------------------------------------
subjects = p.parse_subjects(html_g)
subject_shorts = [s["short"] for s in subjects]

rows = p.parse_students(html_g, group_name=group_label)
if not rows:
    st.warning("Сайт вернул пустую таблицу. Возможно, для группы нет данных.")
    st.stop()

df = pd.DataFrame(rows)

for col in subject_shorts + ["Сумма"]:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col].replace("", pd.NA), errors="coerce")


# ------------------------------------------------------------
# 7. Показываем
# ------------------------------------------------------------
st.subheader(f"Группа {group_label}")
st.caption(
    f"Направление: {direction_label} | "
    f"Курс: {course_label} | "
    f"Предметов: {len(subject_shorts)} | "
    f"Студентов: {len(df)}"
)

keep = ["№", "ФИО"] + subject_shorts + ["Сумма"]
keep = [c for c in keep if c in df.columns]
st.dataframe(df[keep], use_container_width=True, hide_index=True)

with st.expander("ℹ️ Расшифровка предметов"):
    for s in subjects:
        st.write(f"**{s['short']}** — {s['full']}")

with st.expander("🔍 Отладка: финальный запрос"):
    st.json(final_params)
    st.write("Фильтры в ответе:", filters_of(html_g))
    st.write("Строк в таблице:", len(df))
