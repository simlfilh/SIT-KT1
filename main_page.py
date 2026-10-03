import streamlit as st

st.set_page_config(
    page_title="Парсинг БРС СПбГЭУ", 
    page_icon="📊",                  
    layout="wide",                    
    initial_sidebar_state="expanded"  
)

pages = {
    "Этап 1": [
        st.Page("stage1.py", title="— Сравнение успеваемости групп внутри направлений")
    ]
#    "Этап 2": [
#        st.Page("stage2.py", title="— Сравнение успеваемости студента с однокурсниками")
#    ],
#    "Этап 3": [
#        st.Page("stage3.py", title="— Сравнение успеваемости студента со студентами других направлений")
#    ],
}

pg = st.navigation(pages)
pg.run()
