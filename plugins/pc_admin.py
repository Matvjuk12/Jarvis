"""Системное администрирование: процессы, службы, реестр, установка программ, настройки Windows,
сеть, заметки и будильники. Опасные действия всегда спрашивают подтверждение."""
import ctypes
import datetime
import subprocess
import threading
import time

import psutil
from jarvis_core import command, confirm, known_folder, register_group, resolve_path, run_ps, say

register_group(
    "system", "Администрирование: процессы, службы, реестр, установка и обновление программ (winget), "
              "яркость, тёмная тема, обои, настройки Windows, сеть, корзина",
    ["процесс", "служб", "реестр", "установи", "удали программ", "обнови", "яркост", "тёмн", "темн", "обои",
     "настройк", "сеть", "wifi", "wi-fi", "интернет", "корзин", "ip", "ping", "пинг", "аптайм", "проводник",
     "process", "service", "registry", "install", "uninstall", "upgrade", "brightness", "dark mode",
     "wallpaper", "settings", "network", "recycle", "uptime", "task", "kill", "зависло", "программ"])
register_group("notes", "Заметки и будильники", ["замет", "запиши", "запомни", "будильник", "напомни",
                                                   "note", "remind", "alarm", "wake me"])

S, N = "system", "notes"
CRITICAL = {"system", "csrss.exe", "wininit.exe", "winlogon.exe", "lsass.exe", "services.exe", "smss.exe",
            "svchost.exe", "dwm.exe", "explorer.exe", "registry"}


@command(group=S)
def list_processes(n: int = 10, sort_by: str = "memory"):
    """Топ процессов по памяти (sort_by=memory) или процессору (sort_by=cpu)."""
    procs = list(psutil.process_iter(["pid", "name", "memory_percent", "cpu_percent"]))
    key = "cpu_percent" if sort_by == "cpu" else "memory_percent"
    procs.sort(key=lambda p: p.info[key] or 0, reverse=True)
    return "\n".join(f"{p.info['pid']} {p.info['name']} mem={p.info['memory_percent']:.1f}% "
                     f"cpu={p.info['cpu_percent']:.0f}%" for p in procs[:n])


@command(group=S)
def kill_process(name_or_pid: str, force: bool = False):
    """Завершить процесс по имени (chrome) или PID. Требует подтверждения; системные процессы защищены."""
    targets = []
    for p in psutil.process_iter(["pid", "name"]):
        nm = (p.info["name"] or "").lower()
        if name_or_pid.isdigit() and p.info["pid"] == int(name_or_pid) or \
                (not name_or_pid.isdigit() and name_or_pid.lower().replace(".exe", "") in nm):
            if nm in CRITICAL:
                return f"{nm} — системный процесс, трогать нельзя"
            targets.append(p)
    if not targets:
        return "Процесс не найден"
    if not confirm(f"Завершить {len(targets)} процесс(ов) {name_or_pid}?"):
        return "Отменено"
    for p in targets:
        try:
            p.kill() if force else p.terminate()
        except psutil.Error:
            pass
    return f"Завершено: {len(targets)}"


@command(group=S)
def service_control(name: str, action: str = "status"):
    """Служба Windows: action = status, start, stop или restart (кроме status — с подтверждением)."""
    if action == "status":
        return run_ps(f"Get-Service -Name '{name}' | Format-List Name,Status,StartType")
    cmd = {"start": "Start-Service", "stop": "Stop-Service -Force", "restart": "Restart-Service -Force"}.get(action)
    if not cmd:
        return "Неизвестное действие"
    if not confirm(f"{action} службу {name}?"):
        return "Отменено"
    return run_ps(f"{cmd} -Name '{name}'; Get-Service -Name '{name}' | Format-List Name,Status") or "Готово"


@command(group=S)
def registry_get(path: str, name: str = ""):
    """Прочитать значение реестра. path вида HKCU:\\Software\\... ; name — имя параметра (пусто — все)."""
    sel = f" | Select-Object -ExpandProperty '{name}'" if name else ""
    return run_ps(f"Get-ItemProperty -Path '{path}'{sel} | Out-String")[:3000]


@command(group=S)
def registry_set(path: str, name: str, value: str, kind: str = "String"):
    """Записать значение в реестр (kind: String, DWord, QWord, ExpandString). Требует подтверждения."""
    if not confirm(f"Записать в реестр {path}\\{name} = {value}?"):
        return "Отменено"
    return run_ps(f"New-Item -Path '{path}' -Force | Out-Null; "
                  f"Set-ItemProperty -Path '{path}' -Name '{name}' -Value '{value}' -Type {kind}") or "Готово"


@command(group=S)
def installed_programs(filter_text: str = ""):
    """Список установленных программ (можно отфильтровать по части названия)."""
    out = run_ps("Get-ItemProperty HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*,"
                 "HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*,"
                 "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* -ErrorAction SilentlyContinue "
                 "| Where-Object DisplayName | Select-Object -ExpandProperty DisplayName | Sort-Object -Unique")
    lines = [l for l in out.splitlines() if filter_text.lower() in l.lower()]
    return "\n".join(lines[:60]) or "Ничего не найдено"


@command(group=S)
def winget_search(query: str):
    """Найти программу в каталоге winget (получить точный id для установки)."""
    return run_ps(f"winget search '{query}' --accept-source-agreements | Select-Object -First 12 | Out-String", 60)


@command(group=S)
def winget_install(package_id: str):
    """Установить программу через winget по id (например Telegram.TelegramDesktop). Требует подтверждения."""
    if not confirm(f"Установить {package_id}?"):
        return "Отменено"
    out = run_ps(f"winget install --id '{package_id}' -e --silent --accept-package-agreements "
                 "--accept-source-agreements | Out-String", 900)
    return out[-600:]


@command(group=S)
def winget_upgrade_all():
    """Обновить все программы через winget. Требует подтверждения."""
    if not confirm("Обновить все программы?"):
        return "Отменено"
    return run_ps("winget upgrade --all --silent --accept-package-agreements --accept-source-agreements "
                  "| Out-String", 1800)[-600:]


@command(group=S)
def set_brightness(level: int):
    """Яркость экрана 0-100 (ноутбуки и встроенные мониторы)."""
    level = max(0, min(100, int(level)))
    run_ps("(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods)"
           f".WmiSetBrightness(1,{level})")
    return f"Яркость {level}"


@command(phrases=[r"(?:включи )?тёмную тему", r"(?:включи )?темную тему", r"(?:turn on )?dark mode"], group=S)
def dark_mode(enable: bool = True):
    """Включить (true) или выключить (false) тёмную тему Windows."""
    v = 0 if enable else 1
    run_ps("$p='HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize'; "
           f"Set-ItemProperty $p AppsUseLightTheme {v}; Set-ItemProperty $p SystemUsesLightTheme {v}")
    return "Тёмная тема включена" if enable else "Светлая тема включена"


@command(phrases=[r"(?:включи )?светлую тему", r"light mode"], group=S)
def light_mode():
    """Включить светлую тему Windows."""
    return dark_mode(False)


@command(group=S)
def set_wallpaper(path: str):
    """Сменить обои рабочего стола на картинку."""
    p = resolve_path(path)
    ctypes.windll.user32.SystemParametersInfoW(20, 0, str(p), 3)  # type: ignore[attr-defined]
    return "Обои изменены"


SETTINGS = {"bluetooth": "bluetooth", "wifi": "network-wifi", "wi-fi": "network-wifi", "вай": "network-wifi",
            "display": "display", "экран": "display", "sound": "sound", "звук": "sound", "apps": "appsfeatures",
            "приложен": "appsfeatures", "update": "windowsupdate", "обновлен": "windowsupdate",
            "privacy": "privacy", "конфиденц": "privacy", "personal": "personalization",
            "персонализ": "personalization", "battery": "batterysaver", "батаре": "batterysaver",
            "network": "network", "сеть": "network", "default": "defaultapps", "по умолчанию": "defaultapps",
            "микрофон": "privacy-microphone", "microphone": "privacy-microphone"}


@command(group=S)
def open_settings(page: str):
    """Открыть раздел настроек Windows: bluetooth, wifi, display, sound, apps, update, privacy, battery и т.д."""
    low = page.lower()
    for key, uri in SETTINGS.items():
        if key in low:
            subprocess.Popen(f"start ms-settings:{uri}", shell=True)
            return f"Открываю настройки: {page}"
    subprocess.Popen("start ms-settings:", shell=True)
    return "Открываю настройки"


@command(group=S)
def empty_recycle_bin():
    """Очистить корзину. Требует подтверждения."""
    if not confirm("Очистить корзину?"):
        return "Отменено"
    run_ps("Clear-RecycleBin -Force -ErrorAction SilentlyContinue")
    return "Корзина очищена"


@command(group=S)
def restart_explorer():
    """Перезапустить Проводник (если панель задач или рабочий стол зависли). Требует подтверждения."""
    if not confirm("Перезапустить Проводник?"):
        return "Отменено"
    subprocess.run("taskkill /f /im explorer.exe & start explorer.exe", shell=True)
    return "Проводник перезапущен"


@command(group=S)
def network_info():
    """Сетевые адаптеры, IP-адреса и текущая Wi-Fi сеть."""
    ip = run_ps("Get-NetIPConfiguration | ForEach-Object { $_.InterfaceAlias + ': ' + "
                "($_.IPv4Address.IPAddress -join ',') }")
    wifi = subprocess.run("netsh wlan show interfaces", shell=True, capture_output=True, text=True,
                          encoding="cp866", errors="replace").stdout
    ssid = next((l.split(":", 1)[1].strip() for l in wifi.splitlines() if l.strip().startswith("SSID")), "")
    return f"{ip}\nWi-Fi: {ssid or 'нет'}"


@command(group=S)
def ping_host(host: str):
    """Проверить связь с хостом (ping)."""
    r = subprocess.run(["ping", "-n", "2", host], capture_output=True, text=True, encoding="cp866", errors="replace")
    return r.stdout[-300:]


@command(group=S)
def uptime():
    """Сколько времени компьютер включён."""
    d = datetime.timedelta(seconds=int(time.time() - psutil.boot_time()))
    return f"Компьютер работает {d}"


# ---------------------------- заметки и будильники ----------------------------
def _notes_file():
    d = known_folder("documents") / "Jarvis"
    d.mkdir(parents=True, exist_ok=True)
    return d / "notes.txt"


@command(phrases=[r"(?:запиши|запомни|заметка)[:,]? (?P<text>.+)", r"(?:note|remember)[:,]? (?P<text>.+)"], group=N)
def note_add(text: str):
    """Записать заметку (сохраняется в Документы/Jarvis/notes.txt)."""
    with open(_notes_file(), "a", encoding="utf-8") as f:
        f.write(f"[{datetime.datetime.now():%d.%m.%Y %H:%M}] {text}\n")
    return "Записал"


@command(group=N)
def note_read(n: int = 10):
    """Прочитать последние n заметок."""
    p = _notes_file()
    if not p.exists():
        return "Заметок нет"
    return "\n".join(p.read_text(encoding="utf-8").splitlines()[-n:])


@command(group=N)
def set_alarm(time_hhmm: str, label: str = "Будильник"):
    """Поставить напоминание/будильник на время ЧЧ:ММ (24 часа). Работает, пока запущен Джарвис."""
    h, m = (int(x) for x in time_hhmm.replace(".", ":").split(":")[:2])
    now = datetime.datetime.now()
    when = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if when <= now:
        when += datetime.timedelta(days=1)
    threading.Timer((when - now).total_seconds(), lambda: say(f"{label}!")).start()
    return f"Поставил на {when:%H:%M}"
