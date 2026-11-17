"""Базовые веб-команды и время (английский и русский)."""
import datetime
import urllib.parse
import webbrowser

from jarvis_core import command


@command(phrases=[r"(?:найди в интернете|загугли|поищи) (?P<query>.+)",
                  r"(?:search(?: the web)?(?: for)?|google|look up) (?P<query>.+)"])
def web_search(query: str):
    """Открыть поиск Google в браузере по запросу (для ответа на вопрос используй web_lookup)."""
    webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote(query))
    return f"Ищу: {query}"


@command(phrases=[r"(?:открой сайт|перейди на) (?P<url>.+)", r"(?:open|go to) (?:the )?(?:site|website|url) (?P<url>.+)"])
def open_url(url: str):
    """Открыть сайт по адресу."""
    url = url.replace(" точка ", ".").replace(" dot ", ".").replace(" ", "")
    webbrowser.open(url if url.startswith("http") else "https://" + url)
    return f"Открываю {url}"


@command(phrases=[r"который час", r"сколько времени", r"какая дата", r"какое сегодня число",
                  r"what time is it", r"what'?s the time", r"what'?s the date", r"what day is it"])
def current_time():
    """Текущие дата и время."""
    return datetime.datetime.now().strftime("Сейчас %H:%M, %d.%m.%Y")
