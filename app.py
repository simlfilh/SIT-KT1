import streamlit as st
import pandas as pd
from bs4 import BeautifulSoup

import parser as p

st.set_page_config(page_title="БРС СПбГЭУ — группы и баллы", layout="wide")
st.title("📋 Группы и баллы по предметам")


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
def filters_of(html: str):
    soup = BeautifulSoup(html, "html.parser")
    return [li.find("b").get_text(strip=True)
            for li in soup.select("div.filter > ul > li")
            if li.find("b")]


def try_fetch(params_list):
    for params in params_list:
        try:
            html = p.fetch(params)
        except Exception:
            continue
        return html, params
    return None, None


# ------------------------------------------------------------
# 1. Селектбокс «Курс»
# ------------------------------------------------------------
year_label = st.selectbox("Курс", list(YEARS.keys()))
year = YEARS[year_label]


# ------------------------------------------------------------
# 2. Загружаем ВСЕ направления выбранного года через up=none
# ------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def load_directions_for_year(year: str):
    """
    up=none&y=<год> — сайт отдаёт страницу со всеми направлениями года.
    Возвращаем список опций (label + params с up).
    """
    params = {
        "up": "none", "y": year,
        "k": "1", "f": "1",
        "upp": "all", "sort": "fio", "ball": "hide",
    }
    html, used = try_fetch([params])
    if html is None:
        return None, None, []
    opts = p.get_filter_options(html, "Направление")
    opts = [o for o in opts
            if o.label not in ("Не выбрано",) and "up" in o.params]
    return html, used, opts


with st.spinner(f"Загружаем направления за {year_label}…"):
    html_year, used_year, directions = load_directions_for_year(year)

if not directions:
    st.warning(
        f"Сайт не отдал список направлений для {year_label}. "
        f"Проверьте, что up=none&y={year} работает в браузере."
    )
    st.stop()


# ------------------------------------------------------------
# 3. Селектбокс «Направление»
# ------------------------------------------------------------
dir_labels = [o.label for o in directions]
direction_label = st.selectbox("Направление", dir_labels)
direction_opt = directions[dir_labels.index(direction_label)]
up_id = direction_opt.params["up"]

with st.expander("🔍 Отладка: год → направления"):
    st.write("Параметры запроса:", used_year)
    st.write("Фильтры:", filters_of(html_year))
    st.write(f"Найдено направлений: {len(directions)}")
    st.write("up выбранного направления:", up_id)


# ------------------------------------------------------------
# 4. Загружаем группы для выбранного направления + года
# ------------------------------------------------------------
@st.cache_data(ttl=1800, show_spinner=False)
def load_groups(up_id: str, year: str):
    params_base = {
        "up": up_id, "y": year,
        "k": "1", "f": "1",
        "g": "all", "upp": "all", "sort": "fio", "ball": "hide",
    }
    html, used = try_fetch([
        params_base,
        {k: v for k, v in params_base.items() if k != "g"},
    ])
    if html is None:
        return None, None, []
    groups = [o for o in p.get_filter_options(html, "Группа")
              if o.label not in ("Не выбрано", "Все группы")]
    return html, used, groups


with st.spinner("Загружаем группы…"):
    html_g, used_g, groups = load_groups(up_id, year)

if not groups:
    st.warning(
        "Для выбранного направления и года сайт не вернул групп. "
        "Попробуйте другое направление или другой год."
    )
    st.stop()

group_labels = [o.label for o in groups]
group_label = st.selectbox("Группа", group_labels)
group_opt = groups[group_labels.index(group_label)]

with st.expander("🔍 Отладка: направление → группы"):
    st.write("up:", up_id, "| y:", year)
    st.write("Сработавшие параметры:", used_g)
    st.write("Все группы:", group_labels)


# ------------------------------------------------------------
# 5. Загружаем данные выбранной группы
# ------------------------------------------------------------
final_params = {
    "up":   up_id,
    "y":    year,
    "k":    "1",
    "f":    "1",
    "g":    group_opt.params.get("g"),
    "upp":  "all",
    "sort": "fio",
    "ball": "hide",
}


@st.cache_data(ttl=600, show_spinner=False)
def load_group_html(params_tuple):
    return p.fetch(dict(params_tuple))


with st.spinner(f"Загружаем {group_label}…"):
    try:
        html_final = load_group_html(tuple(sorted(final_params.items())))
    except Exception as e:
        st.error(f"Ошибка загрузки: {e}")
        st.stop()


# ------------------------------------------------------------
# 6. Парсим и показываем
# ------------------------------------------------------------
subjects = p.parse_subjects(html_final)
subject_shorts = [s["short"] for s in subjects]

rows = p.parse_students(html_final, group_name=group_label)
if not rows:
    st.warning("Сайт вернул пустую таблицу для этой группы.")
    st.stop()

df = pd.DataFrame(rows)
for col in subject_shorts + ["Сумма"]:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col].replace("", pd.NA), errors="coerce")

st.subheader(f"Группа {group_label}")
st.caption(
    f"{year_label} | {direction_label} | "
    f"Предметов: {len(subject_shorts)} | Студентов: {len(df)}"
)

keep = ["№", "ФИО"] + subject_shorts + ["Сумма"]
keep = [c for c in keep if c in df.columns]
st.dataframe(df[keep], use_container_width=True, hide_index=True)

with st.expander("ℹ️ Расшифровка предметов"):
    for s in subjects:
        st.write(f"**{s['short']}** — {s['full']}")

with st.expander("🔍 Отладка: финальный запрос"):
    st.json(final_params)
    st.write("Фильтры в ответе:", filters_of(html_final))
