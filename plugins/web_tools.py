"""Интернет: поиск с ответом, чтение страниц, погода."""
import html
import re
import urllib.parse
import urllib.request

from jarvis_core import command, register_group

register_group("web", "Интернет: найти информацию и прочитать страницу, погода, новости",
               ["погод", "новост", "курс", "в интернете", "узнай", "что такое", "кто такой", "weather", "news",
                "look up", "find out", "what is", "who is", "website", "статью", "прочитай страницу"])

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Jarvis/2"}


def _get(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode(r.headers.get_content_charset() or "utf-8", errors="replace")


def _text(h: str) -> str:
    h = re.sub(r"(?is)<(script|style|noscript|svg).*?</\1>", " ", h)
    h = re.sub(r"(?s)<[^>]+>", " ", h)
    return re.sub(r"\s+", " ", html.unescape(h)).strip()


@command(group="web")
def web_lookup(query: str):
    """Найти информацию в интернете и вернуть заголовки, ссылки и описания лучших результатов."""
    page = _get("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query))
    out = []
    for m in re.finditer(r'class="result__a" href="(.*?)">(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</a>',
                         page, re.S):
        href, title, snip = m.groups()
        q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg")
        out.append(f"{_text(title)} — {_text(snip)} ({q[0] if q else href})")
        if len(out) >= 5:
            break
    return "\n".join(out) or "Ничего не найдено"


@command(group="web")
def fetch_url(url: str, max_chars: int = 4000):
    """Загрузить веб-страницу и вернуть её текст (для чтения статей и документации)."""
    if not url.startswith("http"):
        url = "https://" + url
    return _text(_get(url))[:max_chars]


@command(phrases=[r"(?:какая )?погода(?: в (?P<city>.+))?", r"(?:what'?s the )?weather(?: in (?P<city>.+))?"], group="web")
def weather(city: str = ""):
    """Погода в городе (пустое значение — по местоположению компьютера)."""
    return _get(f"https://wttr.in/{urllib.parse.quote(city)}?format=%l:+%C,+%t,+ветер+%w,+влажность+%h&lang=ru").strip()
