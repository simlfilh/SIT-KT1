import time
import streamlit as st
import pandas as pd
import plotly.express as px

import parser as p

st.set_page_config(page_title="БРС СПбГЭУ — сравнение групп", layout="wide")

st.title("📊 Сравнение успеваемости групп — БРС СПбГЭУ")

# ---------- 1. Загрузка фильтров ----------
@st.cache_data(ttl=3600, show_spinner=False)
def load_base_html():
    return p.fetch({})

try:
    base_html = load_base_html()
except Exception as e:
    st.error(f"Не удалось загрузить сайт: {e}")
    st.stop()

directions = p.get_filter_options(base_html, "Направление")
semesters  = p.get_filter_options(base_html, "Семестр")
courses    = p.get_filter_options(base_html, "Курс")

if not directions:
    st.error("Не удалось получить список направлений. Проверьте доступность сайта.")
    st.stop()

# ---------- 2. Выбор параметров ----------
col1, col2, col3 = st.columns(3)

with col1:
    direction_labels = [o.label for o in directions]
    # индекс выбранного по умолчанию — первый не «Не выбрано»
    default_dir_idx = 0
    for i, o in enumerate(directions):
        if "Прикладная математика" in o.label:
            default_dir_idx = i
            break
    direction_label = st.selectbox("Направление", direction_labels, index=default_dir_idx)
    direction_opt = directions[direction_labels.index(direction_label)]

with col2:
    course_labels = [o.label for o in courses] or ["4 курс"]
    course_label = st.selectbox("Курс", course_labels, index=0)
    course_opt = next((o for o in courses if o.label == course_label), None)

with col3:
    sem_labels = [o.label for o in semesters] or ["6 семестр"]
    sem_label = st.selectbox("Семестр", sem_labels, index=0)
    sem_opt = next((o for o in semesters if o.label == sem_label), None)

# ---------- 3. Получаем HTML с направлением и «все группы» ----------
params_all = dict(direction_opt.params)
if course_opt:
    params_all.update(course_opt.params)
if sem_opt:
    params_all.update(sem_opt.params)
params_all["g"] = "all"

try:
    html_all = p.fetch(params_all)
except Exception as e:
    st.error(f"Ошибка загрузки страницы: {e}")
    st.stop()

group_names = p.parse_group_names(html_all)
st.info(f"Найдено групп в направлении: **{len(group_names)}** — {', '.join(group_names) or '—'}")

if not group_names:
    st.warning("В выбранном направлении не найдено ни одной группы.")
    st.stop()

# ---------- 4. Скачиваем данные по каждой группе ----------
@st.cache_data(ttl=3600, show_spinner=False)
def load_group(params_key: tuple, group_name: str):
    params = dict(params_key)
    return p.fetch(params), group_name

# Найдём ID групп из фильтра
group_options = {o.label: o for o in p.get_filter_options(html_all, "Группа")}

selected_groups = st.multiselect(
    "Группы для сравнения",
    options=group_names,
    default=group_names[:2] if len(group_names) >= 2 else group_names,
)

if not selected_groups:
    st.warning("Выберите хотя бы одну группу.")
    st.stop()

progress = st.progress(0.0, text="Загружаем данные групп...")
all_rows = []
subject_meta = None

for i, gname in enumerate(selected_groups):
    gopt = group_options.get(gname)
    if not gopt:
        continue
    params_g = dict(params_all)
    params_g.update(gopt.params)   # там уже правильный g=<id>
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
    time.sleep(0.3)  # вежливость к серверу

progress.empty()

if not all_rows:
    st.error("Не удалось получить данные ни по одной группе.")
    st.stop()

df = pd.DataFrame(all_rows)

# ---------- 5. Преобразование баллов в числа ----------
subject_shorts = [s["short"] for s in subject_meta]
for col in subject_shorts + ["Сумма"]:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col].replace("", pd.NA), errors="coerce")

# ---------- 6. Сводная статистика по группам ----------
st.subheader("Сводка по группам")

summary = []
for gname, gdf in df.groupby("Группа"):
    row = {
        "Группа": gname,
        "Студентов": len(gdf),
        "Средний суммарный балл": round(gdf["Сумма"].mean(), 2),
        "Медиана суммарного балла": round(gdf["Сумма"].median(), 2),
        "Макс. балл": round(gdf["Сумма"].max(), 2),
        "Мин. балл": round(gdf["Сумма"].min(), 2),
        "Есть пустые оценки": int(gdf[subject_shorts].isna().sum().sum()),
    }
    summary.append(row)

summary_df = pd.DataFrame(summary).sort_values("Средний суммарный балл", ascending=False)
st.dataframe(summary_df, use_container_width=True)

# ---------- 7. График: средний балл по группам ----------
col_a, col_b = st.columns(2)

with col_a:
    fig1 = px.bar(
        summary_df,
        x="Группа",
        y="Средний суммарный балл",
        text="Средний суммарный балл",
        title="Средний суммарный балл по группам",
        color="Группа",
    )
    fig1.update_traces(textposition="outside")
    fig1.update_layout(showlegend=False, height=420)
    st.plotly_chart(fig1, use_container_width=True)

with col_b:
    fig2 = px.box(
        df,
        x="Группа",
        y="Сумма",
        color="Группа",
        points="all",
        title="Распределение суммарного балла",
    )
    fig2.update_layout(showlegend=False, height=420)
    st.plotly_chart(fig2, use_container_width=True)

# ---------- 8. Сравнение по предметам ----------
st.subheader("Средний балл по предметам")

subj_means = (
    df.groupby("Группа")[subject_shorts]
    .mean()
    .round(2)
    .reset_index()
)

fig3 = px.bar(
    subj_means.melt(id_vars="Группа", var_name="Предмет", value_name="Средний балл"),
    x="Предмет",
    y="Средний балл",
    color="Группа",
    barmode="group",
    title="Средний балл по предметам в разрезе групп",
)
fig3.update_layout(height=500)
st.plotly_chart(fig3, use_container_width=True)

st.dataframe(subj_means, use_container_width=True)

# ---------- 9. Полная таблица ----------
with st.expander("📋 Полная таблица студентов"):
    st.dataframe(df, use_container_width=True)

# ---------- 10. Экспорт ----------
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
    import io
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
