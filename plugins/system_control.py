"""Системные команды: программы, звук, скриншоты, питание, PowerShell."""
import ctypes
import datetime
import json
import os
import subprocess
import threading
from pathlib import Path

import psutil
from jarvis_core import command, confirm, say

APP_ALIASES = {
    "блокнот": "notepad", "калькулятор": "calc", "проводник": "explorer",
    "paint": "mspaint", "диспетчер задач": "taskmgr", "терминал": "wt",
    "командная строка": "cmd", "параметры": "ms-settings:", "настройки": "ms-settings:",
    "браузер": "msedge", "edge": "msedge", "хром": "chrome", "chrome": "chrome",
    "firefox": "firefox", "word": "winword", "excel": "excel", "код": "code",
}


@command(phrases=[r"(?:закрой|выключи программу) (?P<process_name>.+)", r"(?:close|quit|exit) (?P<process_name>.+)"])
def close_app(process_name: str):
    """Закрыть программу по имени процесса (например chrome, notepad)."""
    process_name = APP_ALIASES.get(process_name.lower().strip(), process_name).replace(".exe", "")
    n = 0
    for p in psutil.process_iter(["name"]):
        if process_name.lower() in (p.info["name"] or "").lower():
            try:
                p.terminate()
                n += 1
            except psutil.Error:
                pass
    return f"Закрыто процессов: {n}" if n else "Такой программы не нашёл"


def _vol():
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    dev = AudioUtilities.GetSpeakers()
    if hasattr(dev, "EndpointVolume"):  # новые версии pycaw
        return dev.EndpointVolume
    return dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None).QueryInterface(IAudioEndpointVolume)


@command(phrases=[r"громкость (?P<level>\d+)(?: процентов)?", r"(?:set )?volume (?:to )?(?P<level>\d+)(?: percent)?"])
def set_volume(level: int | None = None, delta: int | None = None, mute: bool | None = None):
    """Громкость: level 0-100, либо delta (+/-), либо mute true/false. Без аргументов — текущая."""
    v = _vol()
    if mute is not None:
        v.SetMute(1 if mute else 0, None)
        return "Звук выключен" if mute else "Звук включён"
    cur = round(v.GetMasterVolumeLevelScalar() * 100)
    if delta is not None:
        level = cur + delta
    if level is None:
        return f"Громкость {cur} процентов"
    level = max(0, min(100, int(level)))
    v.SetMasterVolumeLevelScalar(level / 100, None)
    return f"Громкость {level}"


@command(phrases=[r"(?:сделай )?погромче", r"увеличь громкость", r"volume up", r"louder", r"turn it up"])
def volume_up():
    """Увеличить громкость на 10."""
    return set_volume(delta=10)


@command(phrases=[r"(?:сделай )?потише", r"уменьши громкость", r"volume down", r"quieter", r"turn it down"])
def volume_down():
    """Уменьшить громкость на 10."""
    return set_volume(delta=-10)


@command(phrases=[r"(?:выключи|отключи) звук", r"без звука", r"mute(?: (?:the )?(?:sound|volume))?"])
def mute_sound():
    """Выключить звук."""
    return set_volume(mute=True)


@command(phrases=[r"(?:включи|верни) звук", r"unmute(?: (?:the )?(?:sound|volume))?"])
def unmute_sound():
    """Включить звук."""
    return set_volume(mute=False)


@command()
def media_key(action: str):
    """Медиа-клавиши: play_pause, next, prev, stop."""
    import pyautogui
    keys = {"play_pause": "playpause", "next": "nexttrack", "prev": "prevtrack", "stop": "stop"}
    pyautogui.press(keys.get(action, "playpause"))
    return "Готово"


@command(phrases=[r"(?:пауза|продолжи|играй|поставь на паузу)", r"pause|play|resume|pause (?:the )?(?:music|video)"])
def play_pause():
    """Пауза / воспроизведение медиа."""
    return media_key("play_pause")


@command(phrases=[r"следующ(?:ий|ая|ее) (?:трек|песня|видео)", r"next (?:track|song|video)|skip"])
def next_track():
    """Следующий трек."""
    return media_key("next")


@command(phrases=[r"предыдущ(?:ий|ая|ее) (?:трек|песня|видео)", r"(?:previous|last) (?:track|song|video)"])
def prev_track():
    """Предыдущий трек."""
    return media_key("prev")


@command(phrases=[r"(?:сделай )?скриншот(?: экрана)?", r"(?:take (?:a )?)?screenshot"])
def take_screenshot():
    """Сделать скриншот экрана и сохранить в Изображения/Jarvis."""
    import pyautogui
    folder = Path.home() / "Pictures" / "Jarvis"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"shot_{datetime.datetime.now():%Y%m%d_%H%M%S}.png"
    pyautogui.screenshot().save(path)
    return "Скриншот сохранён"


@command()
def clipboard(action: str, text: str = ""):
    """Буфер обмена: action=read прочитать, action=write записать text."""
    import pyperclip
    if action == "read":
        return pyperclip.paste() or "Буфер пуст"
    pyperclip.copy(text)
    return "Скопировано"


@command()
def type_text(text: str):
    """Напечатать текст в активном окне (где стоит курсор)."""
    import pyautogui
    import pyperclip
    old = pyperclip.paste()
    pyperclip.copy(text)
    pyautogui.hotkey("ctrl", "v")
    pyperclip.copy(old)
    return "Введено"


@command()
def hotkey(keys: list[str]):
    """Нажать сочетание клавиш, например ["win","d"] или ["ctrl","shift","esc"]."""
    import pyautogui
    pyautogui.hotkey(*keys)
    return "Нажато"


@command(phrases=[r"(?:как )?(?:дела|состояние) (?:компьютера|системы|пк)", r"системная информация", r"system (?:status|info)"])
def system_info():
    """Загрузка процессора и памяти, свободное место на диске, заряд батареи, время."""
    mem = psutil.virtual_memory()
    bat = psutil.sensors_battery()
    disk = psutil.disk_usage(Path.home().anchor or "C:\\")
    return json.dumps({
        "cpu_percent": psutil.cpu_percent(interval=0.5), "ram_percent": mem.percent,
        "disk_free_gb": round(disk.free / 1e9, 1),
        "battery": f"{bat.percent}%" if bat else "нет",
        "time": datetime.datetime.now().strftime("%H:%M %d.%m.%Y")}, ensure_ascii=False)


@command(group="system")
def top_processes(n: int = 5):
    """Процессы, которые больше всего занимают оперативную память."""
    procs = sorted(psutil.process_iter(["name", "memory_percent"]),
                   key=lambda p: p.info["memory_percent"] or 0, reverse=True)[:n]
    return "; ".join(f"{p.info['name']} {p.info['memory_percent']:.1f}%" for p in procs)


@command(phrases=[r"(?:поставь )?таймер на (?P<seconds>\d+) секунд", r"(?:set (?:a )?)?timer for (?P<seconds>\d+) seconds"])
def set_timer(seconds: int, label: str = "Таймер"):
    """Поставить таймер на N секунд; по окончании Джарвис скажет об этом голосом."""
    threading.Timer(int(seconds), lambda: say(f"{label}: время вышло")).start()
    return f"Таймер на {seconds} секунд запущен"


@command(phrases=[r"заблокируй (?:компьютер|экран|пк)", r"lock (?:the )?(?:computer|pc|screen)"])
def lock_pc():
    """Заблокировать компьютер."""
    ctypes.windll.user32.LockWorkStation()  # type: ignore[attr-defined]
    return "Блокирую"


@command()
def power(action: str):
    """Питание: shutdown, restart, sleep или cancel (отмена). Спрашивает подтверждение."""
    cmds = {"shutdown": "shutdown /s /t 30", "restart": "shutdown /r /t 30", "cancel": "shutdown /a",
            "sleep": "rundll32.exe powrprof.dll,SetSuspendState 0,1,0"}
    if action not in cmds:
        return "Неизвестное действие"
    if action != "cancel" and not confirm(f"Точно выполнить: {action}?"):
        return "Отменено"
    subprocess.run(cmds[action], shell=True)
    return "Выполняю"


BLOCKED = ("format-volume", "clear-disk", "remove-partition", "diskpart", "bcdedit", "vssadmin delete",
           "cipher /w", "format c:", "rd /s /q c:\\")


@command()
def run_powershell(command: str):
    """Выполнить команду PowerShell, если для задачи нет другого инструмента. Всегда требует подтверждения."""
    if any(b in command.lower() for b in BLOCKED):
        return "Эта команда заблокирована политикой безопасности"
    if not confirm(f"Выполнить команду PowerShell: {command[:100]}?"):
        return "Отменено"
    r = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True,
                       text=True, timeout=120, encoding="utf-8", errors="replace")
    return ((r.stdout + r.stderr).strip() or "Нет вывода")[:2000]
