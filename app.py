import streamlit as st
import pandas as pd

import parser as p

st.set_page_config(page_title="БРС СПбГЭУ — группы и баллы", layout="wide")
st.title("📋 Группы и баллы по предметам")


# ============================================================
# ЯКОРЯ: up для каждого года ПМИ
# ============================================================
YEAR_UP = {
    "2023 (4 курс)": "13613",
    "2024 (3 курс)": "13835",
    "2025 (2 курс)": "14007",
    "2026 (1 курс)": "14101",
}
# ============================================================


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
# 1. Селектбокс «Год / курс»
# ------------------------------------------------------------
year_label = st.selectbox("Год поступления / курс", list(YEAR_UP.keys()))
up_id = YEAR_UP[year_label]
y_id = year_label.split()[0]   # "2023" из "2023 (4 курс)"


# ------------------------------------------------------------
# 2. Подтягиваем группы для выбранного года
# ------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def load_groups_for_year(up_id: str, y_id: str):
    params_base = {
        "up": up_id, "y": y_id, "k": "1", "f": "1",
        "g": "all", "upp": "all", "sort": "fio", "ball": "hide",
    }
    html, used = try_fetch([
        params_base,
        {k: v for k, v in params_base.items() if k != "g"},   # без g
    ])
    if html is None:
        return None, None, []
    groups = [o for o in p.get_filter_options(html, "Группа")
              if o.label not in ("Не выбрано", "Все группы")]
    return html, used, groups


with st.spinner(f"Загружаем группы за {year_label}…"):
    html_year, used_year, groups = load_groups_for_year(up_id, y_id)

if not groups:
    st.warning(
        f"Сайт не отдал список групп для {year_label}. "
        f"Проверьте, что up={up_id} актуален."
    )
    st.stop()

group_labels = [o.label for o in groups]
group_label = st.selectbox("Группа", group_labels)
group_opt = groups[group_labels.index(group_label)]

with st.expander("🔍 Отладка: год → группы"):
    st.write("up:", up_id, "| y:", y_id)
    st.write("Сработавшие параметры:", used_year)
    st.write("Все группы:", group_labels)
    st.write("Параметры выбранной группы:", group_opt.params)


# ------------------------------------------------------------
# 3. Загружаем данные выбранной группы
# ------------------------------------------------------------
final_params = {
    "up":   up_id,
    "y":    y_id,
    "k":    "1",
    "f":    "1",
    "g":    group_opt.params.get("g"),      # id группы из фильтра
    "upp":  "all",
    "sort": "fio",
    "ball": "hide",
}

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
# 4. Парсим и показываем
# ------------------------------------------------------------
subjects = p.parse_subjects(html_g)
subject_shorts = [s["short"] for s in subjects]

rows = p.parse_students(html_g, group_name=group_label)
if not rows:
    st.warning("Сайт вернул пустую таблицу.")
    st.stop()

df = pd.DataFrame(rows)
for col in subject_shorts + ["Сумма"]:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col].replace("", pd.NA), errors="coerce")

st.subheader(f"Группа {group_label}")
st.caption(
    f"Курс: {year_label} | "
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
