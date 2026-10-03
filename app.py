import streamlit as st
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup

import parser as p


st.set_page_config(page_title="БРС СПбГЭУ — группы и баллы", layout="wide")
st.title("📋 Группы и баллы по предметам")


# ------------------------------------------------------------
# Утилиты
# ------------------------------------------------------------
def has_group_filter(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    return p._find_filter(soup, "Группа") is not None


def get_groups(html: str):
    return [o.label for o in p.get_filter_options(html, "Группа")
            if o.label not in ("Не выбрано", "Все группы")]


def probe_up(up_id: str):
    """Один запрос по up с g=all. Возвращает (up, groups, params) или (up, [], None)."""
    params = {
        "up": up_id, "g": "all",
        "k": "1", "f": "1",
        "upp": "all", "sort": "fio", "ball": "hide",
    }
    try:
        html = p.fetch(params)
    except Exception:
        return up_id, [], None
    if not has_group_filter(html):
        return up_id, [], None
    groups = get_groups(html)
    if not groups:
        return up_id, [], None
    # Узнаём y/uy из фильтра «Курс» — это нам пригодится позже
    return up_id, groups, params


@st.cache_data(ttl=3600, show_spinner=False)
def discover_all_ups(up_min: int, up_max: int, max_workers: int = 8):
    """Перебирает up в [up_min, up_max], возвращает список (up, groups)."""
    results = []
    ups = [str(u) for u in range(up_min, up_max + 1)]

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(probe_up, u): u for u in ups}
        for fut in as_completed(futures):
            try:
                up_id, groups, _ = fut.result()
            except Exception:
                continue
            if groups:
                results.append((up_id, groups))
    results.sort(key=lambda x: int(x[0]))
    return results


# ------------------------------------------------------------
# 1. Направление
# ------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def load_base_html():
    return p.fetch({})

base_html = load_base_html()
directions = [o for o in p.get_filter_options(base_html, "Направление")
              if "up" in o.params]

if not directions:
    st.error("Не удалось получить направления.")
    st.stop()

dir_labels = [o.label for o in directions]
direction_label = st.selectbox("Направление", dir_labels)
direction_opt = directions[dir_labels.index(direction_label)]
known_up = int(direction_opt.params["up"])


# ------------------------------------------------------------
# 2. Поиск всех up
# ------------------------------------------------------------
st.caption(f"Известный up: **{known_up}**. Ищем соседние up с группами…")

col1, col2, col3 = st.columns(3)
with col1:
    up_min = st.number_input("up от", value=known_up - 500, step=1)
with col2:
    up_max = st.number_input("up до", value=known_up, step=1)
with col3:
    max_workers = st.number_input("Потоков", value=8, min_value=1, max_value=16)

if st.button("🔍 Найти все группы", type="primary"):
    with st.spinner(f"Перебираем up от {up_min} до {up_max}…"):
        results = discover_all_ups(int(up_min), int(up_max), int(max_workers))
    st.session_state["discovered"] = results
    st.success(f"Найдено {len(results)} up с группами.")

# Достаём из session_state
results = st.session_state.get("discovered", [])

if not results:
    st.info("Нажмите «Найти все группы», чтобы собрать список.")
    st.stop()

with st.expander("🔍 Найденные up и группы"):
    for up_id, groups in results:
        st.write(f"up={up_id}: {groups}")


# ------------------------------------------------------------
# 3. Селектбокс «Группа» (все группы со всех up)
# ------------------------------------------------------------
group_to_up = {}
for up_id, groups in results:
    for g in groups:
        group_to_up.setdefault(g, []).append(up_id)

all_groups = sorted(group_to_up.keys())
st.info(f"Всего групп: **{len(all_groups)}** — {', '.join(all_groups)}")

group_label = st.selectbox("Группа", all_groups)

# Если группа встречается в нескольких up — берём первый
up_for_group = group_to_up[group_label][0]


# ------------------------------------------------------------
# 4. Список семестров и загрузка данных
# ------------------------------------------------------------
# Запрос по up с g=all, чтобы получить g-id группы и семестры
params_all = {
    "up": up_for_group, "g": "all",
    "k": "1", "f": "1",
    "upp": "all", "sort": "fio", "ball": "hide",
}
html_all = p.fetch(params_all)

# Находим g-id группы
group_opt = next(
    (o for o in p.get_filter_options(html_all, "Группа")
     if o.label == group_label),
    None,
)
if group_opt is None:
    st.error(f"Не удалось найти группу {group_label} в ответе сайта.")
    st.stop()

g_id = group_opt.params.get("g")

# Финальный запрос с конкретной группой
params_final = {
    "up": up_for_group, "g": g_id,
    "k": "1", "f": "1",
    "upp": "all", "sort": "fio", "ball": "hide",
}
html_final = p.fetch(params_final)

subjects = p.parse_subjects(html_final)
subject_shorts = [s["short"] for s in subjects]

rows = p.parse_students(html_final, group_name=group_label)
if not rows:
    st.warning("Пустая таблица.")
    st.stop()

df = pd.DataFrame(rows)
for col in subject_shorts + ["Сумма"]:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col].replace("", pd.NA), errors="coerce")


# ------------------------------------------------------------
# 5. Вывод
# ------------------------------------------------------------
st.subheader(f"Группа {group_label}")
st.caption(f"up={up_for_group}, g={g_id}, студентов: {len(df)}")

keep = ["№", "ФИО"] + subject_shorts + ["Сумма"]
keep = [c for c in keep if c in df.columns]
st.dataframe(df[keep], use_container_width=True, hide_index=True)

with st.expander("ℹ️ Предметы"):
    for s in subjects:
        st.write(f"**{s['short']}** — {s['full']}")

with st.expander("🔍 Отладка"):
    st.json(params_final)
    st.write("Фильтры:", [b.get_text(strip=True) for b in BeautifulSoup(html_final, "html.parser").select("div.filter b")])
