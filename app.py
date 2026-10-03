# ------------------------------------------------------------
# 4. Группы И семестры выбранного направления
# ------------------------------------------------------------
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
        return None, None, [], []
    groups = [o for o in p.get_filter_options(html, "Группа")
              if o.label not in ("Не выбрано", "Все группы")]
    sems = p.get_filter_options(html, "Семестр")
    return html, used, groups, sems


with st.spinner("Загружаем группы и семестры…"):
    html_g, used_g, groups, sems = load_groups_and_sems(up_id, year)

if not groups:
    st.warning("Для выбранного направления и года нет групп.")
    st.stop()

group_options = {o.label: o for o in groups}
group_names = list(group_options.keys())
st.info(f"Найдено групп: **{len(group_names)}** — {', '.join(group_names)}")

if not sems:
    st.warning("Сайт не вернул список семестров для выбранного направления.")
    st.stop()

# Список семестров + текущий по умолчанию
sem_labels = [o.label for o in sems]
current_sem = p.get_selected_text(html_g, "Семестр")
default_sem = [current_sem] if current_sem in sem_labels else sem_labels[-1:]


# ------------------------------------------------------------
# 5. Мультиселекты групп и семестров
# ------------------------------------------------------------
col_g, col_s = st.columns(2)

with col_g:
    selected_groups = st.multiselect(
        "Группы для сравнения",
        options=group_names,
        default=group_names[:2] if len(group_names) >= 2 else group_names,
    )

with col_s:
    selected_sems = st.multiselect(
        "Семестры",
        options=sem_labels,
        default=default_sem,
        help="Можно выбрать несколько — тогда данные будут собраны по каждому семестру.",
    )

if not selected_groups:
    st.warning("Выберите хотя бы одну группу.")
    st.stop()
if not selected_sems:
    st.warning("Выберите хотя бы один семестр.")
    st.stop()


# ------------------------------------------------------------
# 6. Скачиваем данные: для каждой группы × каждого семестра
# ------------------------------------------------------------
sem_options = {o.label: o for o in sems}


@st.cache_data(ttl=600, show_spinner=False)
def load_group_html(up_id, year, g_id, s_id):
    params = {
        "up": up_id, "y": year,
        "k": "1", "f": "1",
        "g": g_id, "s": s_id,
        "upp": "all", "sort": "fio", "ball": "hide",
    }
    return p.fetch(params)


total = len(selected_groups) * len(selected_sems)
progress = st.progress(0.0, text="Загружаем данные…")
step = 0
all_rows = []
subject_meta = None

for gname in selected_groups:
    g_id = group_options[gname].params.get("g")
    for sem_label in selected_sems:
        step += 1
        progress.progress(step / total, text=f"{gname} / {sem_label}")

        s_id = sem_options[sem_label].params.get("s")
        try:
            html_grp = load_group_html(up_id, year, g_id, s_id)
        except Exception as e:
            st.warning(f"{gname} / {sem_label}: {e}")
            continue

        if subject_meta is None:
            subject_meta = p.parse_subjects(html_grp)

        rows = p.parse_students(html_grp, group_name=gname)
        for r in rows:
            r["Семестр"] = sem_label
        all_rows.extend(rows)
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
# 7. Сводка по (семестр, группа)
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
    .sort_values(["Семестр", "Средний_балл"], ascending=[True, False])
)
st.dataframe(summary, use_container_width=True)


# ------------------------------------------------------------
# 8. Графики
# ------------------------------------------------------------
col_a, col_b = st.columns(2)

with col_a:
    fig1 = px.bar(
        summary, x="Группа", y="Средний_балл", color="Семестр",
        barmode="group", text="Средний_балл",
        title="Средний суммарный балл: группы × семестры",
    )
    fig1.update_traces(textposition="outside")
    fig1.update_layout(height=460)
    st.plotly_chart(fig1, use_container_width=True)

with col_b:
    fig2 = px.box(
        df, x="Группа", y="Сумма", color="Семестр",
        points="all",
        title="Распределение суммарного балла: группы × семестры",
    )
    fig2.update_layout(height=460)
    st.plotly_chart(fig2, use_container_width=True)

# Если выбрано больше одного семестра — показываем динамику
if len(selected_sems) > 1:
    st.subheader("Динамика среднего балла по семестрам")
    fig_dyn = px.line(
        summary, x="Семестр", y="Средний_балл", color="Группа",
        markers=True,
        title="Как менялся средний балл группы от семестра к семестру",
    )
    fig_dyn.update_layout(height=450)
    st.plotly_chart(fig_dyn, use_container_width=True)


# ------------------------------------------------------------
# 9. Сравнение по предметам
# ------------------------------------------------------------
st.subheader("Средний балл по предметам")

# Выбор семестра для сравнения по предметам
sem_for_subjects = st.selectbox(
    "Семестр для сравнения по предметам",
    options=selected_sems,
    index=len(selected_sems) - 1,
)
df_sem = df[df["Семестр"] == sem_for_subjects]

subj_means = (
    df_sem.groupby("Группа")[subject_shorts]
    .mean()
    .round(2)
    .reset_index()
)

fig3 = px.bar(
    subj_means.melt(id_vars="Группа", var_name="Предмет", value_name="Средний балл"),
    x="Предмет", y="Средний балл", color="Группа", barmode="group",
    title=f"Средний балл по предметам — {sem_for_subjects}",
)
fig3.update_layout(height=500)
st.plotly_chart(fig3, use_container_width=True)
st.dataframe(subj_means, use_container_width=True)
