"""Управление компьютером: запуск ЛЮБЫХ программ, окна, мышь, клавиши, «зрение»."""
import base64
import difflib
import io
import json
import os
import re
import subprocess
import time

from jarvis_core import command, register_group

register_group("windows", "Окна, мышь, клавиатура и управление интерфейсом программ (кнопки, поля)",
               ["окно", "окна", "мыш", "клик", "нажми", "кнопк", "прокрут", "сверни", "разверни", "window", "click",
                "button", "scroll", "minimize", "maximize", "interface", "интерфейс"])
register_group("vision", "Зрение: посмотреть на экран и описать его",
               ["на экране", "экран", "посмотри", "вижу", "screen", "look at", "see"])

# ---- Запуск программ ------------------------------------------------------
DIRECT = {  # системные штуки, которые запускаются напрямую
    "блокнот": "notepad", "калькулятор": "calc", "проводник": "explorer", "paint": "mspaint",
    "пейнт": "mspaint", "диспетчер задач": "taskmgr", "терминал": "wt", "командная строка": "cmd",
    "параметры": "ms-settings:", "настройки": "ms-settings:", "панель управления": "control",
    "браузер": "msedge", "эдж": "msedge", "edge": "msedge",
}
RU_NAMES = {  # русское произношение / типичные ошибки Whisper -> имя в меню «Пуск»
    "телеграм": "telegram", "телеграмм": "telegram", "телега": "telegram", "тг": "telegram",
    "дискорд": "discord", "дискард": "discord", "стим": "steam",
    "хром": "chrome", "гугл хром": "chrome", "гугл": "chrome",
    "ворд": "word", "эксель": "excel", "пауэрпоинт": "powerpoint",
    "спотифай": "spotify", "вайбер": "viber", "ватсап": "whatsapp",
    "скайп": "skype", "зум": "zoom", "опера": "opera",
    "яндекс браузер": "yandex", "яндекс": "yandex",
    "обс": "obs", "вс код": "visual studio code", "код": "visual studio code",
    "файрфокс": "firefox", "фаерфокс": "firefox", "файерфокс": "firefox",
    "огненные леса": "firefox", "огненный лес": "firefox", "файр фокс": "firefox",
    "ютуб": "youtube", "почта": "mail", "браузер": "msedge",
}
_TR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
               ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r",
                "s", "t", "u", "f", "h", "c", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))


def _translit(s: str) -> str:
    return "".join(_TR.get(ch, ch) for ch in s.lower())


_cache = {"t": 0.0, "apps": []}


def start_apps() -> list[dict]:
    """Все приложения из меню «Пуск» (включая Microsoft Store): [{'Name','AppID'}]."""
    if _cache["apps"] and time.time() - _cache["t"] < 600:
        return _cache["apps"]
    ps = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=40)
    try:
        data = json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        data = []
    if isinstance(data, dict):
        data = [data]
    _cache.update(t=time.time(), apps=data)
    return data


def _score(cands: list[str], app_name: str) -> float:
    a = app_name.lower()
    best = 0.0
    for c in cands:
        if len(c) >= 3 and (c in a or (len(a) >= 3 and a in c)):
            best = max(best, 0.95)
        best = max(best, difflib.SequenceMatcher(None, c, a).ratio())
        for w in re.split(r"[\s\-_.]+", a):
            if len(w) >= 3:
                best = max(best, difflib.SequenceMatcher(None, c, w).ratio() * 0.97)
    return best


@command(phrases=[r"(?:открой|запусти|включи|открыть|запустить) (?P<name>.+)",
                  r"(?:open|launch|start|run) (?P<name>.+)"], priority=-10)
def open_app(name: str):
    """Запустить ЛЮБУЮ установленную программу, игру или раздел настроек Windows по названию
    (на русском или английском): Telegram, Discord, Steam, Chrome, Word, Калькулятор и т.д."""
    key = name.lower().strip(" .,!?")
    if key in DIRECT:
        try:
            os.startfile(DIRECT[key])  # type: ignore[attr-defined]
        except OSError:
            subprocess.Popen(f'start "" "{DIRECT[key]}"', shell=True)
        return f"Открываю {name}"

    cands = [key, _translit(key)]
    if key in RU_NAMES:
        cands.insert(0, RU_NAMES[key])
    best, best_score = None, 0.0
    try:
        for app in start_apps():
            sc = _score(cands, app.get("Name", ""))
            if sc > best_score:
                best, best_score = app, sc
    except Exception:  # noqa: BLE001
        best = None
    if best and best_score >= 0.6:
        subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + best["AppID"]])
        return f"Открываю {best['Name']}"

    # запасной путь: сайт, путь к файлу или имя exe
    try:
        os.startfile(key)  # type: ignore[attr-defined]
        return f"Открываю {name}"
    except OSError:
        pass
    # последний шанс: поиск Windows
    import pyautogui
    import pyperclip
    old = pyperclip.paste()
    pyautogui.press("win")
    time.sleep(0.8)
    pyperclip.copy(RU_NAMES.get(key, key))
    pyautogui.hotkey("ctrl", "v")
    time.sleep(1.0)
    pyautogui.press("enter")
    pyperclip.copy(old)
    return f"В списке не нашёл, пробую найти «{name}» через поиск Windows"


# ---- Окна -------------------------------------------------------------------
def _find_windows(title: str):
    import pygetwindow as gw
    t = title.lower().strip()
    t_tr = _translit(t)
    t = RU_NAMES.get(t, t)
    out = []
    for w in gw.getAllWindows():
        if not w.title.strip():
            continue
        wt = w.title.lower()
        if t in wt or t_tr in wt or difflib.SequenceMatcher(None, t, wt).ratio() > 0.7:
            out.append(w)
    return out


@command(group="windows")
def list_windows():
    """Список открытых окон (заголовки)."""
    import pygetwindow as gw
    titles = [w.title for w in gw.getAllWindows() if w.title.strip()]
    return "; ".join(titles[:25]) or "Окон нет"


@command(phrases=[r"(?:переключись на|перейди в|покажи окно|вернись в) (?P<title>.+)",
                  r"(?:switch to|go to|show) (?P<title>.+)"], priority=-5)
def focus_window(title: str):
    """Переключиться на открытое окно по части названия (например 'telegram', 'chrome', 'блокнот')."""
    ws = _find_windows(title)
    if not ws:
        return f"Окно «{title}» не найдено"
    w = ws[0]
    try:
        if w.isMinimized:
            w.restore()
        w.activate()
    except Exception:  # noqa: BLE001
        w.minimize()
        w.restore()
    return f"Переключился на {w.title[:40]}"


@command(group="windows")
def window_action(title: str, action: str):
    """Действие с окном по части названия: action = minimize, maximize, restore или close."""
    ws = _find_windows(title)
    if not ws:
        return f"Окно «{title}» не найдено"
    w = ws[0]
    {"minimize": w.minimize, "maximize": w.maximize, "restore": w.restore, "close": w.close}.get(
        action, w.activate)()
    return "Готово"


@command(phrases=[r"сверни все окна", r"покажи рабочий стол", r"show (?:the )?desktop", r"minimize all(?: windows)?"], group="windows")
def show_desktop():
    """Свернуть все окна (показать рабочий стол)."""
    import pyautogui
    pyautogui.hotkey("win", "d")
    return "Готово"


# ---- Мышь и клавиатура ------------------------------------------------------
@command(group="windows")
def mouse_click(x: int, y: int, button: str = "left", double: bool = False):
    """Кликнуть мышью по координатам экрана (x, y). button: left/right. double: двойной клик."""
    import pyautogui
    pyautogui.click(x, y, button=button, clicks=2 if double else 1)
    return "Клик выполнен"


@command(group="windows")
def scroll(amount: int):
    """Прокрутить колесо мыши: положительное число — вверх, отрицательное — вниз (например -500)."""
    import pyautogui
    pyautogui.scroll(amount)
    return "Готово"


@command(group="windows")
def press_key(key: str, times: int = 1):
    """Нажать клавишу (enter, esc, tab, f5, space, left, right, up, down, delete, backspace...)."""
    import pyautogui
    pyautogui.press(key, presses=times)
    return "Нажато"


@command(group="windows")
def screen_size():
    """Размер экрана и текущая позиция курсора."""
    import pyautogui
    return f"Экран {pyautogui.size()}, курсор {pyautogui.position()}"


# ---- «Зрение» ---------------------------------------------------------------
@command(phrases=[r"что (?:у меня )?на экране", r"что я вижу", r"what(?:'s| is) on (?:the |my )?screen"], group="vision")
def describe_screen(question: str = "Опиши, что сейчас на экране."):
    """Посмотреть на экран и ответить на вопрос о том, что на нём (нужен ключ Gemini).
    Скриншот отправляется в Google."""
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return "Для зрения нужен ключ GEMINI_API_KEY в файле .env"
    import pyautogui
    from openai import OpenAI
    img = pyautogui.screenshot()
    img.thumbnail((1600, 1600))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    client = OpenAI(base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                    api_key=key, timeout=45, max_retries=0)
    r = client.chat.completions.create(
        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"), max_tokens=500,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": question + " Ответь по-русски, кратко."},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}}]}])
    return r.choices[0].message.content


# ---- Управление элементами интерфейса программ (UI Automation) -----------------
def _uia_window(title: str):
    from pywinauto import Desktop
    t = RU_NAMES.get(title.lower().strip(), title)
    win = Desktop(backend="uia").window(title_re=f"(?i).*{re.escape(t)}.*")
    win.wait("exists", timeout=4)
    return win


@command(group="windows")
def ui_list_controls(window: str):
    """Список кнопок, полей и пунктов меню в окне программы (по части названия окна). Нужен, чтобы затем нажать элемент."""
    win = _uia_window(window)
    names = []
    for c in win.descendants():
        info = c.element_info
        if info.name and info.control_type in ("Button", "Edit", "MenuItem", "TabItem", "CheckBox",
                                               "ListItem", "Hyperlink", "ComboBox", "RadioButton"):
            names.append(f"{info.control_type}: {info.name}")
        if len(names) >= 60:
            break
    return "\n".join(names) or "Элементы не найдены"


@command(group="windows")
def ui_click(window: str, control: str, double: bool = False):
    """Нажать кнопку/элемент интерфейса в окне программы по тексту элемента."""
    win = _uia_window(window)
    ctrl = win.child_window(title_re=f"(?i).*{re.escape(control)}.*").wrapper_object()
    ctrl.click_input(double=double)
    return f"Нажато: {control}"


@command(group="windows")
def ui_type(window: str, control: str, text: str):
    """Ввести текст в поле интерфейса в окне программы (поле находится по подписи или имени)."""
    win = _uia_window(window)
    ctrl = win.child_window(title_re=f"(?i).*{re.escape(control)}.*", control_type="Edit").wrapper_object()
    ctrl.set_edit_text(text)
    return "Введено"
