"""Парсер БРС СПбГЭУ (rating.unecon.ru)."""
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs
from dataclasses import dataclass, field

BASE = "https://rating.unecon.ru/index.php"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Referer": "https://rating.unecon.ru/",
}


@dataclass
class Option:
    """Пункт выпадающего фильтра."""
    label: str
    params: dict = field(default_factory=dict)


def _parse_href(href: str) -> dict:
    """Из href вида 'index.php?&y=2023&k=1&...' вытащить параметры."""
    if not href:
        return {}
    # убираем префикс index.php?
    if "?" in href:
        href = href.split("?", 1)[1]
    q = parse_qs(href, keep_blank_values=True)
    # parse_qs возвращает списки, берём первые значения и приводим к str
    return {k: v[0] for k, v in q.items()}


def _find_filter(soup: BeautifulSoup, filter_name: str):
    """Найти <li> фильтра по названию ('Курс', 'Группа', ...)."""
    for li in soup.select("div.filter > ul > li"):
        b = li.find("b")
        if b and filter_name.lower() in b.get_text(strip=True).lower():
            return li
    return None


def get_filter_options(html: str, filter_name: str) -> list[Option]:
    """Вернуть список опций для конкретного фильтра."""
    soup = BeautifulSoup(html, "html.parser")
    li = _find_filter(soup, filter_name)
    if not li:
        return []
    options = []
    for a in li.select("a.option"):
        label = a.get_text(strip=True)
        params = _parse_href(a.get("href", ""))
        options.append(Option(label=label, params=params))
    return options


def get_selected_text(html: str, filter_name: str) -> str:
    """Текущее выбранное значение фильтра (для инициализации UI)."""
    soup = BeautifulSoup(html, "html.parser")
    li = _find_filter(soup, filter_name)
    if not li:
        return ""
    sel = li.select_one(".selected_text")
    return sel.get_text(strip=True) if sel else ""


def fetch(params: dict) -> str:
    """Загрузить страницу и вернуть HTML."""
    r = requests.get(BASE, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    r.encoding = "utf-8"
    return r.text


def parse_subjects(html: str):
    """
    Вернуть список предметов:
      [{'short': 'ИМ', 'full': 'Имитационное моделирование (дифф.зач.)'}, ...]
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table or not table.find("thead"):
        return []

    thead_rows = table.find("thead").find_all("tr")
    if len(thead_rows) < 2:
        return []

    subjects = []
    for th in thead_rows[1].find_all("th"):
        short = th.get_text(strip=True)
        full = (th.get("title") or "").strip()
        subjects.append({"short": short, "full": full})

    # подтянем полные названия из ul.upp_descr, если title пустой
    upp_desc = {}
    for li in soup.select("ul.upp_descr li"):
        text = li.get_text(" ", strip=True)
        if " - " in text:
            left, right = text.split(" - ", 1)
            short = left.split(".", 1)[-1].strip()
            upp_desc[short] = right.strip()

    for s in subjects:
        if not s["full"]:
            s["full"] = upp_desc.get(s["short"], "")

    return subjects


def parse_students(html: str, group_name: str | None = None):
    """
    Вернуть список словарей со студентами.
    Если group_name передан — добавит колонку 'Группа'.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table or not table.find("tbody"):
        return []

    subjects = parse_subjects(html)
    students = []

    for tr in table.find("tbody").find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 3:
            continue

        num = tds[0].get_text(strip=True)
        fio_tag = tds[1].find("a")
        fio = fio_tag.get_text(strip=True) if fio_tag else tds[1].get_text(strip=True)

        stud_id = None
        if fio_tag and fio_tag.get("href"):
            q = parse_qs(urlparse(fio_tag["href"]).query)
            stud_id = q.get("stud", [None])[0]

        marks = [td.get_text(strip=True) for td in tds[2:-1]]
        total = tds[-1].get_text(strip=True)

        row = {
            "Группа": group_name,
            "№": num,
            "ФИО": fio,
            "stud_id": stud_id,
        }
        for subj, mark in zip(subjects, marks):
            row[subj["short"]] = mark
        row["Сумма"] = total
        students.append(row)

    return students


def parse_group_names(html: str) -> list[str]:
    """Список названий групп из фильтра 'Группа' (кроме 'Не выбрано'/'Все группы')."""
    opts = get_filter_options(html, "Группа")
    names = []
    for o in opts:
        if o.label in ("Не выбрано", "Все группы"):
            continue
        names.append(o.label)
    return names
