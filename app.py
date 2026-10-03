import io
import time
import streamlit as st
import pandas as pd
import plotly.express as px
from bs4 import BeautifulSoup

import parser as p

st.set_page_config(page_title="БРС СПбГЭУ — сравнение групп", layout="wide")
st.title("📊 Сравнение успеваемости групп — БРС СПбГЭУ")


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
# 2. Все направления выбранного года (up=none)
# ------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def load_directions_for_year(year: str):
    params = {
        "up": "none", "y": year,
        "k": "1", "f": "1",
        "upp": "all", "sort": "fio", "ball": "hide",
    }
    html, used = try_fetch([params])
    if html is None:
        return None, None, []
    opts = [o for o in p.get_filter_options(html, "Направление")
            if o.label not in ("Не выбрано",) and "up" in o.params]
    return html, used, opts


with st.spinner(f"Загружаем направления за {year_label}…"):
    html_year, used_year, directions = load_directions_for_year(year)

if not directions:
    st.warning(f"Не удалось получить направления за {year_label}.")
    st.stop()


# ------------------------------------------------------------
# 3. Селектбокс «Направление»
# ------------------------------------------------------------
dir_labels = [o.label for o in directions]
direction_label = st.selectbox("Направление", dir_labels)
direction_opt = directions[dir_labels.index(direction_label)]
up_id = direction_opt.params["up"]

with st.expander("🔍 Отладка: год → направления", expanded=False):
    st.write("Параметры:", used_year)
    st.write(f"Найдено направлений: {len(directions)}")
    st.write("up выбранного направления:", up_id)


# ------------------------------------------------------------
# 4. Группы выбранного направления
# ------------------------------------------------------------
@st.cache_data(ttl=1800, show_spinner=False)
def load_groups(up_id: str, year: str):
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
        return None, None, []
    groups = [o for o in p.get_filter_options(html, "Группа")
              if o.label not in ("Не выбрано", "Все группы")]
    return html, used, groups


with st.spinner("Загружаем группы…"):
    html_g, used_g, groups = load_groups(up_id, year)

if not groups:
    st.warning("Для выбранного направления и года нет групп.")
    st.stop()

group_options = {o.label: o for o in groups}
group_names = list(group_options.keys())

st.info(f"Найдено групп: **{len(group_names)}** — {', '.join(group_names)}")


# ------------------------------------------------------------
# 5. Мультиселект групп
# ------------------------------------------------------------
selected_groups = st.multiselect(
    "Группы для сравнения",
    options=group_names,
    default=group_names[:2] if len(group_names) >= 2 else group_names,
)

if not selected_groups:
    st.warning("Выберите хотя бы одну группу.")
    st.stop()


# ------------------------------------------------------------
# 6. Скачиваем данные по каждой выбранной группе
# ------------------------------------------------------------
@st.cache_data(ttl=600, show_spinner=False)
def load_group_html(up_id, year, g_id):
    params = {
        "up": up_id, "y": year,
        "k": "1", "f": "1",
        "g": g_id, "upp": "all", "sort": "fio", "ball": "hide",
    }
    return p.fetch(params)


progress = st.progress(0.0, text="Загружаем данные…")
all_rows = []
subject_meta = None

for i, gname in enumerate(selected_groups):
    gopt = group_options[gname]
    g_id = gopt.params.get("g")
    progress.progress((i + 1) / len(selected_groups), text=f"Загружено: {gname}")

    try:
        html_grp = load_group_html(up_id, year, g_id)
    except Exception as e:
        st.warning(f"{gname}: {e}")
        continue

    if subject_meta is None:
        subject_meta = p.parse_subjects(html_grp)

    all_rows.extend(p.parse_students(html_grp, group_name=gname))
    time.sleep(0.2)

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
# 7. Сводка по группам
# ------------------------------------------------------------
st.subheader("Сводка по группам")

summary = (
    df.groupby("Группа")
    .agg(
        Студентов=("ФИО", "count"),
        Средний_балл=("Сумма", "mean"),
        Медиана=("Сумма", "median"),
        Макс=("Сумма", "max"),
        Мин=("Сумма", "min"),
        Пустых=("Сумма", lambda s: int(s.isna().sum())),
    )
    .round(2)
    .reset_index()
    .sort_values("Средний_балл", ascending=False)
)
st.dataframe(summary, use_container_width=True)


# ------------------------------------------------------------
# 8. Графики
# ------------------------------------------------------------
col_a, col_b = st.columns(2)

with col_a:
    fig1 = px.bar(
        summary, x="Группа", y="Средний_балл",
        text="Средний_балл", color="Группа",
        title="Средний суммарный балл по группам",
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
# 9. Сравнение по предметам
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
# 10. Полная таблица и экспорт
# ------------------------------------------------------------
with st.expander("📋 Полная таблица студентов"):
    st.dataframe(df, use_container_width=True)

st.subheader("Экспорт")
col_x, col_y = st.columns(2)

with col_x:
    csv_bytes = df.to_csv(index=False, sep=";", encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button(
        "⬇️ Скачать студентов (CSV)",
        data=csv_bytes, file_name="students_compare.csv", mime="text/csv",
    )

with col_y:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Студенты", index=False)
        summary.to_excel(writer, sheet_name="Сводка", index=False)
        subj_means.to_excel(writer, sheet_name="По предметам", index=False)
    st.download_button(
        "⬇️ Скачать Excel (3 листа)",
        data=buf.getvalue(), file_name="students_compare.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
