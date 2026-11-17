"""Файлы и папки по всему компьютеру: список, чтение, запись, копирование, перенос, удаление, поиск, архивы."""
import fnmatch
import os
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

from jarvis_core import command, confirm, is_protected, register_group, resolve_path, run_ps

register_group(
    "files", "Файлы и папки: список, чтение, запись, копирование, перенос, удаление, поиск, архивы",
    ["файл", "папк", "документ", "диск", "удали", "скопиру", "перемест", "перенес", "архив", "загрузк",
     "рабочий стол", "file", "folder", "delete", "copy", "move", "zip", "directory", "download", "desktop"])

G = "files"


def _guard(path: Path, action: str) -> None:
    if is_protected(path) and not confirm(f"{action} в системной папке {path}?"):
        raise PermissionError("Отменено пользователем")


@command(group=G)
def list_dir(path: str = "home"):
    """Показать содержимое папки (поддерживаются «рабочий стол», «документы», «загрузки», полные пути)."""
    p = resolve_path(path)
    items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    out = [("[папка] " if i.is_dir() else "") + i.name for i in items[:60]]
    return f"{p} ({len(items)} элементов):\n" + "\n".join(out)


@command(group=G)
def read_file(path: str, max_chars: int = 4000):
    """Прочитать текстовый файл целиком или начало (до max_chars символов)."""
    p = resolve_path(path)
    raw = p.read_bytes()[:max_chars * 4]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1251", errors="replace")
    return text[:max_chars]


@command(group=G)
def write_file(path: str, content: str, append: bool = False):
    """Записать текст в файл (append=true — дописать в конец). Перезапись существующего файла требует подтверждения."""
    p = resolve_path(path)
    _guard(p, "Запись файла")
    if p.exists() and not append and not confirm(f"Файл {p.name} уже есть. Перезаписать?"):
        return "Отменено"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a" if append else "w", encoding="utf-8") as f:
        f.write(content)
    return f"Записано: {p}"


@command(group=G)
def make_folder(path: str):
    """Создать папку (вместе с родительскими)."""
    p = resolve_path(path)
    p.mkdir(parents=True, exist_ok=True)
    return f"Папка создана: {p}"


@command(group=G)
def copy_path(src: str, dst: str):
    """Скопировать файл или папку."""
    s, d = resolve_path(src), resolve_path(dst)
    _guard(d, "Копирование")
    if d.exists() and not confirm(f"{d.name} уже существует. Заменить?"):
        return "Отменено"
    if s.is_dir():
        shutil.copytree(s, d, dirs_exist_ok=True)
    else:
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s, d)
    return f"Скопировано в {d}"


@command(group=G)
def move_path(src: str, dst: str):
    """Переместить или переименовать файл либо папку."""
    s, d = resolve_path(src), resolve_path(dst)
    _guard(s, "Перемещение")
    _guard(d, "Перемещение")
    if d.exists() and not confirm(f"{d.name} уже существует. Заменить?"):
        return "Отменено"
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(s), str(d))
    return f"Перемещено в {d}"


@command(group=G)
def delete_path(path: str):
    """Удалить файл или папку (в корзину). Всегда спрашивает подтверждение."""
    p = resolve_path(path)
    if not p.exists():
        return "Не найдено"
    if not confirm(f"Удалить {p.name}?"):
        return "Отменено"
    try:
        from send2trash import send2trash
        send2trash(str(p))
    except ImportError:
        kind = "DeleteDirectory" if p.is_dir() else "DeleteFile"
        run_ps("Add-Type -AssemblyName Microsoft.VisualBasic; "
               f"[Microsoft.VisualBasic.FileIO.FileSystem]::{kind}('{p}','OnlyErrorDialogs','SendToRecycleBin')")
    return f"Удалено в корзину: {p.name}"


@command(group=G)
def find_files(pattern: str, folder: str = "home", max_results: int = 20):
    """Найти файлы по маске или части имени (например *.pdf или отчёт) внутри папки, включая вложенные."""
    base = resolve_path(folder)
    pat = pattern.lower() if any(c in pattern for c in "*?[") else f"*{pattern.lower()}*"
    hits, deadline = [], time.time() + 20
    skip = {"$recycle.bin", "windows", "appdata", "node_modules", ".git", "system volume information"}
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d.lower() not in skip]
        for name in files + dirs:
            if fnmatch.fnmatch(name.lower(), pat):
                hits.append(os.path.join(root, name))
                if len(hits) >= max_results:
                    return "\n".join(hits)
        if time.time() > deadline:
            break
    return "\n".join(hits) or "Ничего не найдено"


@command(group=G)
def open_path(path: str):
    """Открыть файл программой по умолчанию или папку в Проводнике."""
    os.startfile(str(resolve_path(path)))  # type: ignore[attr-defined]
    return "Открываю"


@command(group=G)
def reveal_in_explorer(path: str):
    """Показать файл в Проводнике (выделить его)."""
    subprocess.Popen(["explorer", "/select,", str(resolve_path(path))])
    return "Показываю"


@command(group=G)
def file_info(path: str):
    """Размер, даты создания и изменения файла или папки."""
    p = resolve_path(path)
    st = p.stat()
    size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.is_dir() else st.st_size
    fmt = lambda t: time.strftime("%d.%m.%Y %H:%M", time.localtime(t))  # noqa: E731
    return f"{p}\nРазмер: {size / 1e6:.2f} МБ\nИзменён: {fmt(st.st_mtime)}\nСоздан: {fmt(st.st_ctime)}"


@command(group=G)
def zip_path(path: str, dest: str = ""):
    """Упаковать файл или папку в zip-архив."""
    p = resolve_path(path)
    out = resolve_path(dest) if dest else p.with_suffix(".zip") if p.is_file() else p.parent / (p.name + ".zip")
    if p.is_dir():
        shutil.make_archive(str(out.with_suffix("")), "zip", p)
    else:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(p, p.name)
    return f"Архив: {out}"


@command(group=G)
def unzip_file(path: str, dest: str = ""):
    """Распаковать zip-архив (по умолчанию в папку рядом)."""
    p = resolve_path(path)
    out = resolve_path(dest) if dest else p.with_suffix("")
    _guard(out, "Распаковка")
    with zipfile.ZipFile(p) as z:
        z.extractall(out)
    return f"Распаковано в {out}"
