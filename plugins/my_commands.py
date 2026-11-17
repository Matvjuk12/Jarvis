"""ВАШИ КОМАНДЫ. Копируйте примеры ниже и меняйте под себя.

Как добавить команду:
  1. Напишите функцию и повесьте на неё @command(...).
  2. Первая строка докстринга — описание для нейросети: по нему она поймёт,
     когда вызывать функцию (даже если вы сформулируете просьбу своими словами).
  3. phrases=[...] — необязательные фразы для МГНОВЕННОГО запуска без нейросети
     (регулярные выражения; именованные группы (?P<имя>...) станут аргументами).
  4. Скажите «Джарвис, перезагрузи команды» (или пункт в меню трея) — без перезапуска.

Можно создавать и новые файлы в папке plugins/ — они подхватятся сами.
Файлы, имя которых начинается с «_», игнорируются.
"""
import subprocess
import webbrowser

from jarvis_core import command, confirm, say


# --- Пример 1: простая команда с фразой ---------------------------------
@command(phrases=[r"включи (?:мою )?музыку", r"поставь музыку"])
def play_my_music():
    """Открыть любимый плейлист в браузере."""
    webbrowser.open("https://www.youtube.com/results?search_query=lofi+hip+hop")
    return "Включаю музыку"


# --- Пример 2: команда с аргументом -------------------------------------
@command(phrases=[r"(?:открой|запусти) проект (?P<project>.+)"])
def open_project(project: str):
    """Открыть папку проекта в VS Code по названию."""
    projects = {"джарвис": r"C:\Users\Public\jarvis", "сайт": r"C:\Users\Public\site"}  # <- ваши пути
    path = projects.get(project.lower())
    if not path:
        return f"Проект {project} не найден"
    subprocess.Popen(["code", path], shell=True)
    return f"Открываю проект {project}"


# --- Пример 3: сценарий из нескольких действий --------------------------
@command(phrases=[r"режим работы", r"рабочий режим"])
def work_mode():
    """Включить рабочее окружение: браузер, редактор, заметки."""
    subprocess.Popen("start msedge", shell=True)
    subprocess.Popen("start code", shell=True)
    subprocess.Popen("start notepad", shell=True)
    return "Рабочий режим включён"


# --- Пример 4: команда с подтверждением ---------------------------------
@command()
def clean_temp():
    """Очистить временные файлы Windows. Спрашивает подтверждение."""
    if not confirm("Очистить временные файлы?"):
        return "Отменено"
    subprocess.run('del /q /f /s "%TEMP%\\*"', shell=True)
    return "Временные файлы очищены"