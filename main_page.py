import streamlit as st

st.set_page_config(
    page_title="Парсинг БРС СПбГЭУ", 
    page_icon="📊",                  
    layout="wide",                    
    initial_sidebar_state="expanded"  
)

pages = [
    st.Page("stage1.py", title="Этап 1 — Сравнение групп внутри направления"),
    st.Page("stage2.py", title="Этап 2 — Сравнение студента с однокурсниками"),
    st.Page("stage3.py", title="Этап 3 — Сравнение с другими направлениями"),
]

pg = st.navigation(pages)
pg.run()
