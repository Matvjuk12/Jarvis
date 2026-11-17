"""Ядро Джарвиса: реестр команд, группы инструментов, загрузка плагинов, общие помощники.

Плагины импортируют отсюда:
    from jarvis_core import command, say, confirm, register_group, resolve_path, run_ps
"""
import ctypes
import importlib.util
import inspect
import logging
import os
import re
import subprocess
import types
import typing
import uuid
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("jarvis")

# Хуки ввода/вывода; движок подставляет реальные функции.
_io = {"say": lambda t: log.info("SAY: %s", t),
       "confirm": lambda q: False}


def say(text: str) -> None:
    """Сказать что-либо голосом."""
    _io["say"](text)


def confirm(question: str) -> bool:
    """Спросить подтверждение (голосом «да/нет», кнопкой в окне или в чате)."""
    return _io["confirm"](question)


@dataclass
class Command:
    name: str
    fn: typing.Callable
    description: str
    schema: dict
    patterns: list = field(default_factory=list)  # быстрые офлайн-фразы
    priority: int = 0      # чем больше, тем раньше проверяется (общие «ловушки» — с минусом)
    group: str = "core"    # группа инструментов (см. register_group)


REGISTRY: dict[str, Command] = {}
GROUPS: dict[str, dict] = {}


def register_group(name: str, description: str, keywords: list[str]) -> None:
    """Группа инструментов. В запрос к нейросети группа попадает, если в команде есть одно из
    ключевых слов (или нейросеть сама подключит её через more_tools). Так экономятся лимиты."""
    GROUPS[name] = {"desc": description, "kw": [k.lower() for k in keywords]}


def detect_groups(text: str) -> set[str]:
    t = text.lower()
    return {g for g, info in GROUPS.items() if any(k in t for k in info["kw"])}


def _json_type(tp) -> dict:
    origin = typing.get_origin(tp)
    if origin in (list, typing.List):
        args = typing.get_args(tp)
        return {"type": "array", "items": _json_type(args[0]) if args else {"type": "string"}}
    if origin in (typing.Union, types.UnionType):
        non_none = [a for a in typing.get_args(tp) if a is not type(None)]
        return _json_type(non_none[0]) if non_none else {"type": "string"}
    return {"type": {int: "integer", float: "number", bool: "boolean"}.get(tp, "string")}


def command(phrases: list[str] | None = None, name: str | None = None, priority: int = 0,
            group: str = "core"):
    """Регистрирует функцию как команду Джарвиса.

    * Докстринг функции = описание для нейросети (пишите по-русски/по-английски).
    * Аргументы и их типы (str/int/float/bool/list[str]) -> схема инструмента автоматически.
    * phrases — необязательные регулярные выражения для БЫСТРОГО запуска без нейросети
      (работает офлайн, не тратит лимиты). Именованные группы (?P<имя>...) -> аргументы функции.
    * priority — порядок проверки фраз (по умолчанию 0; у общих «лови всё» фраз — отрицательный).
    * group — группа инструментов; "core" всегда доступна нейросети.
    """
    def deco(fn):
        sig = inspect.signature(fn)
        hints = typing.get_type_hints(fn)
        props, required = {}, []
        for pname, p in sig.parameters.items():
            props[pname] = _json_type(hints.get(pname, str))
            if p.default is inspect.Parameter.empty:
                required.append(pname)
        REGISTRY[name or fn.__name__] = Command(
            name=name or fn.__name__, fn=fn,
            description=(inspect.getdoc(fn) or fn.__name__).strip(),
            schema={"type": "object", "properties": props, "required": required},
            patterns=[re.compile(p, re.IGNORECASE) for p in (phrases or [])],
            priority=priority, group=group,
        )
        return fn
    return deco


def tools_for_llm(groups: typing.Iterable[str] = ()) -> list[dict]:
    active = set(groups) | {"core"}
    return [{"type": "function",
             "function": {"name": c.name, "description": c.description, "parameters": c.schema}}
            for c in REGISTRY.values() if c.group in active]


def run_command(name: str, args: dict) -> str:
    cmd = REGISTRY.get(name)
    if not cmd:
        return f"Неизвестная команда {name}"
    try:
        result = cmd.fn(**args)
        return "Готово." if result is None else str(result)
    except Exception as e:  # noqa: BLE001
        log.exception("Ошибка команды %s", name)
        return f"Ошибка команды {name}: {e}"


def match_fast(text: str) -> tuple[str, dict] | None:
    """Ищет подходящую фразу среди регулярок плагинов (без нейросети)."""
    text = text.strip(" .,!?")
    for cmd in sorted(REGISTRY.values(), key=lambda c: -c.priority):
        for pat in cmd.patterns:
            m = pat.fullmatch(text)
            if m:
                return cmd.name, {k: v for k, v in m.groupdict().items() if v is not None}
    return None


def load_plugins(folder: Path) -> int:
    """(Пере)загружает все plugins/*.py. Файлы, начинающиеся с «_», пропускаются."""
    REGISTRY.clear()
    GROUPS.clear()
    loaded = 0
    for path in sorted(folder.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"jarvis_plugin_{path.stem}", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            loaded += 1
        except Exception:  # noqa: BLE001
            log.exception("Не удалось загрузить плагин %s", path.name)
    return loaded


# ------------------------------------------------------------------ общие помощники
def run_ps(script: str, timeout: int = 60) -> str:
    """Выполнить PowerShell (вывод в UTF-8). Возвращает stdout+stderr."""
    full = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; $ProgressPreference='SilentlyContinue'; " + script
    r = subprocess.run(["powershell", "-NoProfile", "-Command", full], capture_output=True, text=True,
                       timeout=timeout, encoding="utf-8", errors="replace")
    return (r.stdout + r.stderr).strip()


_KNOWN = {  # GUID известных папок Windows (учитывают OneDrive и переименования)
    "desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
    "documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
    "downloads": "374DE290-123F-4565-9164-39C4925E467B",
    "pictures": "33E28130-4E1E-4676-835A-98395C3BC3BB",
    "music": "4BD8D571-6D19-48D3-BE97-422220080E43",
    "videos": "18989B1D-99B5-455B-841C-AB7C74E4DDFC",
}
FOLDER_ALIASES = {
    "рабочий стол": "desktop", "desktop": "desktop", "документы": "documents", "documents": "documents",
    "загрузки": "downloads", "downloads": "downloads", "изображения": "pictures", "картинки": "pictures",
    "pictures": "pictures", "музыка": "music", "music": "music", "видео": "videos", "videos": "videos",
    "домашняя папка": "home", "home": "home", "~": "home",
}


def known_folder(name: str) -> Path:
    if name == "home" or name not in _KNOWN or os.name != "nt":
        return Path.home() / ({"desktop": "Desktop", "documents": "Documents", "downloads": "Downloads",
                               "pictures": "Pictures", "music": "Music", "videos": "Videos"}.get(name, ""))
    try:
        class GUID(ctypes.Structure):
            _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                        ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]
        guid = GUID.from_buffer_copy(uuid.UUID(_KNOWN[name]).bytes_le)
        buf = ctypes.c_wchar_p()
        ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(buf))  # type: ignore[attr-defined]
        path = Path(buf.value)
        ctypes.windll.ole32.CoTaskMemFree(buf)  # type: ignore[attr-defined]
        return path
    except Exception:  # noqa: BLE001
        return Path.home() / name.capitalize()


def resolve_path(p: str) -> Path:
    """Путь с поддержкой «рабочий стол/документы/загрузки…», ~ и переменных среды."""
    s = (p or "").strip().strip('"') or "home"
    parts = re.split(r"[\\/]", s, maxsplit=1)
    head = parts[0].lower().strip(" :")
    if head in FOLDER_ALIASES:
        base = known_folder(FOLDER_ALIASES[head])
        return (base / parts[1]) if len(parts) > 1 and parts[1] else base
    path = Path(os.path.expandvars(os.path.expanduser(s)))
    if not path.is_absolute():
        path = Path.home() / path
    return path


def is_protected(path: Path) -> bool:
    """Системные папки: изменения там требуют подтверждения."""
    roots = [os.environ.get(k) for k in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData")]
    p = str(path).lower()
    return any(r and p.startswith(r.lower()) for r in roots)
