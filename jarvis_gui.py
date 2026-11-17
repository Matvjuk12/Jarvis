"""
Джарвис — графическое приложение (пульт управления и чат).

Сам Джарвис (jarvis.py) работает в фоне без окон: слушает микрофон и выполняет команды.
Это окно только запускает/останавливает его, показывает чат (голосовые и письменные команды,
ответы, действия), даёт настроить ключи и параметры. Закрыли окно — Джарвис продолжает работать.

    pythonw jarvis_gui.py                 открыть приложение
    python jarvis_gui.py --install-shortcut   создать ярлыки (рабочий стол + меню «Пуск») и значок
"""
import ctypes
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = Path.home() / ".jarvis"
DATA.mkdir(exist_ok=True)
ICO = BASE / "jarvis.ico"
ENV = BASE / ".env"
def _gui_port() -> int:
    """Использует тот же приоритет порта, что и jarvis.py: окружение, затем .env."""
    value = os.getenv("JARVIS_PORT")
    if not value and ENV.exists():
        try:
            for line in ENV.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, raw = line.split("=", 1)
                    if key.strip() == "JARVIS_PORT" and raw.strip():
                        value = raw.strip().strip('"').strip("'")
                        break
        except OSError:
            pass
    try:
        port = int(value or "47615")
        return port if 1 <= port <= 65535 else 47615
    except (TypeError, ValueError):
        return 47615


PORT = _gui_port()
TITLE = "Джарвис"

BG, PANEL, FG, ACC, DIM = "#0f172a", "#1e293b", "#e2e8f0", "#38bdf8", "#94a3b8"
GOOD, BAD, WARN = "#4ade80", "#f87171", "#fbbf24"


# ------------------------------------------------------------------ помощники
def pythonw() -> str:
    pw = Path(sys.executable).with_name("pythonw.exe")
    return str(pw if pw.exists() else sys.executable)


def make_icon(path: Path = ICO) -> bool:
    """Рисует значок (светящееся «ядро») и сохраняет как .ico."""
    try:
        from PIL import Image, ImageDraw, ImageFilter
    except ImportError:
        return False
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((6, 6, size - 6, size - 6), fill=(11, 24, 48, 255))
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    for r, w in ((100, 14), (72, 10), (46, 8)):
        g.ellipse((size / 2 - r, size / 2 - r, size / 2 + r, size / 2 + r), outline=(0, 208, 255, 255), width=w)
    g.ellipse((size / 2 - 22, size / 2 - 22, size / 2 + 22, size / 2 + 22), fill=(180, 240, 255, 255))
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(5)))
    img = Image.alpha_composite(img, glow)
    img.save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return True


def install_shortcuts() -> str:
    """Ярлыки «Джарвис» на рабочем столе и в меню «Пуск»."""
    sys.path.insert(0, str(BASE))
    from jarvis_core import resolve_path
    make_icon()
    q = lambda s: str(s).replace("'", "''")  # noqa: E731
    targets = [resolve_path("desktop") / f"{TITLE}.lnk",
               Path(os.environ.get("APPDATA", str(Path.home()))) / "Microsoft/Windows/Start Menu/Programs" / f"{TITLE}.lnk"]
    done = []
    for t in targets:
        t.parent.mkdir(parents=True, exist_ok=True)
        ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}'); $s.TargetPath='{pw}'; "
              "$s.Arguments='\"{gui}\"'; $s.WorkingDirectory='{base}'; $s.IconLocation='{ico}'; "
              "$s.Description='Джарвис — голосовой помощник'; $s.Save()").format(
            lnk=q(t), pw=q(pythonw()), gui=q(BASE / "jarvis_gui.py"), base=q(BASE), ico=q(ICO))
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
        if r.returncode == 0:
            done.append(str(t))
    return "Ярлыки созданы:\n" + "\n".join(done) if done else "Не удалось создать ярлыки"


_ENGINE_PROCESS = None


def start_engine() -> None:
    """Надёжно запускает движок; stdout/stderr движка сохраняются в журнал."""
    global _ENGINE_PROCESS
    # Не плодим процессы при повторном нажатии кнопки.
    if _ENGINE_PROCESS is not None and _ENGINE_PROCESS.poll() is None:
        return

    log_path = DATA / "engine-launch.log"
    # Для фонового движка предпочтителен python.exe: даже ошибки импорта попадут в лог.
    # Если рядом его нет, используем тот же интерпретатор, которым запущен GUI.
    exe = Path(sys.executable)
    console_python = exe.with_name("python.exe")
    engine_python = str(console_python if console_python.exists() else exe)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        with log_path.open("a", encoding="utf-8", errors="replace") as log_file:
            log_file.write(f"\n--- запуск {BASE / 'jarvis.py'}; порт GUI={PORT}; Python={engine_python} ---\n")
            log_file.flush()
            _ENGINE_PROCESS = subprocess.Popen(
                [engine_python, "-u", str(BASE / "jarvis.py")],
                cwd=str(BASE),
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                creationflags=flags,
                close_fds=True,
            )
    except Exception as exc:
        try:
            with log_path.open("a", encoding="utf-8", errors="replace") as log_file:
                log_file.write(f"Ошибка запуска движка: {type(exc).__name__}: {exc}\n")
        except OSError:
            pass


def autostart_enabled() -> bool:
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run")
        winreg.QueryValueEx(key, "Jarvis")
        return True
    except (OSError, ImportError):
        return False


def set_autostart(on: bool) -> None:
    subprocess.run([sys.executable, str(BASE / "jarvis.py"),
                    "--install-autostart" if on else "--remove-autostart"],
                   creationflags=0x08000000, capture_output=True)


# --- .env
def read_env() -> dict:
    vals = {}
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals


def write_env(updates: dict) -> None:
    """Обновляет ключи в .env, сохраняя остальные строки и комментарии."""
    if ENV.exists():
        lines = ENV.read_text(encoding="utf-8-sig").splitlines()
    elif (BASE / ".env.example").exists():
        lines = (BASE / ".env.example").read_text(encoding="utf-8-sig").splitlines()
    else:
        lines = []
    for key, value in updates.items():
        idx = next((i for i, l in enumerate(lines) if l.strip().lstrip("# ").startswith(key + "=")
                    or l.strip() == key + "="), None)
        new = f"{key}={value}" if value else f"# {key}="
        if idx is not None:
            lines[idx] = new
        elif value:
            lines.append(new)
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ связь с движком
class Link:
    def __init__(self, events: queue.Queue):
        self.events, self.sock, self.connected = events, None, False

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            try:
                token_file = DATA / "token"
                if not token_file.exists():
                    time.sleep(0.5)
                    continue
                token = token_file.read_text(encoding="utf-8").strip()
                if not token:
                    time.sleep(0.5)
                    continue
                s = socket.create_connection(("127.0.0.1", PORT), timeout=3)
                s.sendall((json.dumps({"token": token}) + "\n").encode("utf-8"))
                s.settimeout(None)
                self.sock, self.connected = s, True
                self.events.put({"t": "_connected"})
                for line in s.makefile("r", encoding="utf-8"):
                    if line.strip():
                        self.events.put(json.loads(line))
                self._last_error = None
            except Exception as exc:  # noqa: BLE001
                message = f"Связь с движком: {type(exc).__name__}: {exc} (127.0.0.1:{PORT})"
                if getattr(self, "_last_error", None) != message:
                    self.events.put({"t": "_connection_error", "text": message})
                    self._last_error = message
            if self.connected:
                self.events.put({"t": "_disconnected"})
            self.sock, self.connected = None, False
            time.sleep(1.5)

    def send(self, obj: dict) -> bool:
        if not self.sock:
            return False
        try:
            self.sock.sendall((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
            return True
        except OSError:
            return False


# ------------------------------------------------------------------ окно
FIELDS = [
    ("Ключи (можно несколько через запятую — переключение при лимите, контекст сохраняется)", None, None, None),
    ("GROQ_API_KEY", "Groq (сильный) — console.groq.com/keys", "secret", None),
    ("GEMINI_API_KEY", "Gemini — aistudio.google.com/apikey", "secret", None),
    ("OPENROUTER_API_KEY", "OpenRouter — openrouter.ai/keys", "secret", None),
    ("CEREBRAS_API_KEY", "Cerebras — cloud.cerebras.ai", "secret", None),
    ("MODELSCOPE_API_KEY", "ModelScope (без VPN) — modelscope.cn", "secret", None),
    ("SILICONFLOW_API_KEY", "SiliconFlow (без VPN) — siliconflow.cn", "secret", None),
    ("ZHIPU_API_KEY", "Zhipu/GLM — open.bigmodel.cn", "secret", None),
    ("Голос (как в Железном человеке)", None, None, None),
    ("TTS_ENGINE", "Движок голоса", "combo", ["edge", "pyttsx3"]),
    ("EDGE_VOICE", "Голос Edge (en-GB-RyanNeural / ru-RU-DmitryNeural)", "entry", None),
    ("TTS_RATE_EDGE", "Скорость Edge (−10% спокойнее)", "entry", None),
    ("Распознавание речи", None, None, None),
    ("LANGUAGES", "Языки", "combo", ["ru,en", "ru", "en"]),
    ("WHISPER_MODEL", "Модель Whisper", "combo",
     ["tiny", "base", "small", "medium", "large-v3-turbo"]),
    ("WAKE_MODE", "Режим активации", "combo", ["open", "hybrid", "strict"]),
    ("WAKE_WORDS", "Слова активации через запятую", "entry", None),
    ("AUTO_SEND_SECONDS", "Пауза перед выполнением, сек", "entry", None),
    ("MIC_DEVICE", "Номер микрофона", "entry", None),
    ("MIC_THRESHOLD", "Порог громкости речи", "entry", None),
    ("POPUP_POS", "Позиция окна с текстом", "combo",
     ["right-bottom", "right-middle", "right-top", "left-bottom", "left-middle", "left-top"]),
]


class App:
    def __init__(self):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.events: queue.Queue = queue.Queue()
        self.link = Link(self.events)
        self.root = tk.Tk()
        self.root.title(TITLE)
        self.root.geometry("820x640")
        self.root.minsize(640, 480)
        self.root.configure(bg=BG)
        if make_icon_if_needed():
            try:
                self.root.iconbitmap(str(ICO))
            except tk.TclError:
                pass
        self.confirm_win = None
        self.state_text = "Подключаюсь…"
        self._style()
        self._build_top()
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=10, pady=(4, 6))
        self._build_chat()
        self._build_settings()
        self._build_log()
        tk.Label(self.root, text="Закрытие окна не останавливает Джарвиса — он работает в фоне (значок возле часов). "
                                 "Остановить: кнопка «Остановить».", bg=BG, fg=DIM, font=("Segoe UI", 9)
                 ).pack(fill="x", padx=12, pady=(0, 8))
        self.link.start()
        self.root.after(100, self._pump)
        self.root.after(2200, self._auto_start)

    # ---- оформление ----
    def _style(self):
        st = self.ttk.Style()
        st.theme_use("clam")
        st.configure("TNotebook", background=BG, borderwidth=0)
        st.configure("TNotebook.Tab", background=PANEL, foreground=FG, padding=(16, 7), font=("Segoe UI", 10))
        st.map("TNotebook.Tab", background=[("selected", ACC)], foreground=[("selected", "#04111d")])
        st.configure("TFrame", background=BG)
        st.configure("TCombobox", fieldbackground=PANEL, background=PANEL, foreground=FG, arrowcolor=FG)
        st.map("TCombobox", fieldbackground=[("readonly", PANEL)], foreground=[("readonly", FG)])

    def _btn(self, parent, text, cmd, accent=False, **kw):
        return self.tk.Button(parent, text=text, command=cmd, relief="flat", cursor="hand2",
                              bg=ACC if accent else PANEL, fg="#04111d" if accent else FG,
                              activebackground=ACC, font=("Segoe UI", 10, "bold" if accent else "normal"),
                              padx=12, pady=5, **kw)

    def _build_top(self):
        tk = self.tk
        top = tk.Frame(self.root, bg=BG)
        top.pack(fill="x", padx=12, pady=(12, 4))
        self.dot = tk.Label(top, text="●", fg=BAD, bg=BG, font=("Segoe UI", 16))
        self.dot.pack(side="left")
        self.status = tk.Label(top, text=self.state_text, fg=FG, bg=BG, font=("Segoe UI", 12, "bold"))
        self.status.pack(side="left", padx=(4, 16))
        self._btn(top, "▶ Запустить", self.on_start, accent=True).pack(side="left", padx=3)
        self._btn(top, "⏹ Остановить", self.on_stop).pack(side="left", padx=3)
        self._btn(top, "↻ Перезапустить", self.on_restart).pack(side="left", padx=3)
        self.auto_var = tk.BooleanVar(value=autostart_enabled())
        tk.Checkbutton(top, text="Запускать с Windows", variable=self.auto_var, command=self.on_autostart,
                       bg=BG, fg=FG, selectcolor=PANEL, activebackground=BG, activeforeground=FG,
                       font=("Segoe UI", 10)).pack(side="right")

    def _build_chat(self):
        tk = self.tk
        f = tk.Frame(self.nb, bg=BG)
        self.nb.add(f, text="  Чат  ")
        self.chat = tk.Text(f, bg=PANEL, fg=FG, relief="flat", wrap="word", state="disabled",
                            font=("Segoe UI", 11), padx=12, pady=10, spacing3=6, insertbackground=FG)
        sb = tk.Scrollbar(f, command=self.chat.yview)
        self.chat.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.chat.pack(fill="both", expand=True, padx=(0, 0), pady=(6, 4))
        self.chat.tag_config("you", foreground=ACC, font=("Segoe UI", 11, "bold"))
        self.chat.tag_config("jarvis", foreground=GOOD, font=("Segoe UI", 11, "bold"))
        self.chat.tag_config("tool", foreground=DIM, font=("Consolas", 9))
        self.chat.tag_config("info", foreground=WARN, font=("Segoe UI", 10, "italic"))
        self.live = tk.Label(f, text="", anchor="w", bg=BG, fg=WARN, font=("Segoe UI", 10, "italic"))
        self.live.pack(fill="x", padx=4)
        row = tk.Frame(f, bg=BG)
        row.pack(fill="x", pady=(2, 8))
        self.entry = tk.Entry(row, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", font=("Segoe UI", 12))
        self.entry.pack(side="left", fill="x", expand=True, ipady=8, padx=(0, 8))
        self.entry.bind("<Return>", lambda e: self.on_send())
        self._btn(row, "Отправить", self.on_send, accent=True).pack(side="left")
        self.speak_var = tk.BooleanVar(value=False)
        tk.Checkbutton(row, text="Озвучивать", variable=self.speak_var, bg=BG, fg=FG, selectcolor=PANEL,
                       activebackground=BG, activeforeground=FG, font=("Segoe UI", 10)).pack(side="left", padx=8)
        self.entry.focus_set()

    def _build_settings(self):
        tk, ttk = self.tk, self.ttk
        outer = tk.Frame(self.nb, bg=BG)
        self.nb.add(outer, text="  Настройки  ")
        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        sb = tk.Scrollbar(outer, command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True)
        inner = tk.Frame(canvas, bg=BG)
        canvas.create_window((0, 0), window=inner, anchor="nw", width=760)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        values = read_env()
        self.vars: dict = {}
        for key, label, kind, options in FIELDS:
            if kind is None:
                tk.Label(inner, text=key, bg=BG, fg=ACC, font=("Segoe UI", 11, "bold"), anchor="w"
                         ).pack(fill="x", padx=14, pady=(14, 2))
                continue
            tk.Label(inner, text=label, bg=BG, fg=DIM, font=("Segoe UI", 9), anchor="w").pack(fill="x", padx=14)
            var = tk.StringVar(value=values.get(key, ""))
            self.vars[key] = var
            if kind == "combo":
                w = ttk.Combobox(inner, textvariable=var, values=options, state="normal")
            else:
                w = tk.Entry(inner, textvariable=var, bg=PANEL, fg=FG, insertbackground=FG, relief="flat",
                             show="•" if kind == "secret" else "")
            w.pack(fill="x", padx=14, pady=(0, 6), ipady=4)
        bar = tk.Frame(inner, bg=BG)
        bar.pack(fill="x", padx=14, pady=16)
        self._btn(bar, "Сохранить и перезапустить", self.on_save, accent=True).pack(side="left")
        self._btn(bar, "Папка команд (plugins)", lambda: os.startfile(BASE / "plugins")).pack(side="left", padx=6)
        self._btn(bar, "Создать ярлыки", self.on_shortcuts).pack(side="left")
        self._btn(bar, "Перезагрузить команды", lambda: self.link.send({"t": "reload"})).pack(side="left", padx=6)

    def _build_log(self):
        tk = self.tk
        f = tk.Frame(self.nb, bg=BG)
        self.nb.add(f, text="  Журнал  ")
        self.log = tk.Text(f, bg=PANEL, fg=DIM, relief="flat", wrap="none", state="disabled", font=("Consolas", 9))
        sb = tk.Scrollbar(f, command=self.log.yview)
        self.log.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(fill="both", expand=True, pady=6)
        self.root.after(1500, self._refresh_log)

    # ---- действия ----
    def on_start(self):
        if self.link.connected:
            return
        start_engine()
        self._set_status("Запускаю…", WARN)

    def on_stop(self):
        self.link.send({"t": "quit"})
        self._set_status("Останавливаю…", WARN)

    def on_restart(self):
        self.link.send({"t": "quit"})
        self._set_status("Перезапускаю…", WARN)
        self._wait_restart(0)

    def _wait_restart(self, n):
        if self.link.connected and n < 40:
            self.root.after(250, lambda: self._wait_restart(n + 1))
        else:
            self.root.after(800, start_engine)

    def _auto_start(self):
        if not self.link.connected:
            start_engine()

    def on_autostart(self):
        set_autostart(self.auto_var.get())

    def on_shortcuts(self):
        from tkinter import messagebox
        messagebox.showinfo(TITLE, install_shortcuts())

    def on_save(self):
        write_env({k: v.get().strip() for k, v in self.vars.items()})
        self.on_restart()

    def on_send(self):
        text = self.entry.get().strip()
        if not text:
            return
        if self.link.send({"t": "chat", "text": text, "speak": self.speak_var.get()}):
            self.entry.delete(0, "end")
        else:
            self._append("Джарвис не запущен. Нажмите «Запустить».\n", "info")

    # ---- события от движка ----
    def _set_status(self, text, color):
        self.status.config(text=text)
        self.dot.config(fg=color)

    def _append(self, text, tag):
        self.chat.config(state="normal")
        self.chat.insert("end", text, tag)
        self.chat.config(state="disabled")
        self.chat.see("end")

    def _pump(self):
        try:
            while True:
                self._on_event(self.events.get_nowait())
        except queue.Empty:
            pass
        self.root.after(100, self._pump)

    def _on_event(self, ev: dict):
        t = ev.get("t")
        if t == "_connected":
            self._set_status("Работает", GOOD)
        elif t == "_disconnected":
            self._set_status("Остановлен", BAD)
            self.live.config(text="")
        elif t == "_connection_error":
            self._set_status("Нет связи с движком", BAD)
            self._append(ev.get("text", "Ошибка подключения") + "\n", "info")
        elif t == "hello":
            self._append(f"— подключено · команд: {ev.get('commands')} · режим: {ev.get('mode')} —\n", "info")
        elif t == "state":
            v = ev.get("v")
            self._set_status({"loading": "Загружаю модели…", "busy": "Выполняю…"}.get(v, "Слушаю"),
                             WARN if v in ("loading", "busy") else GOOD)
        elif t == "user":
            src = {"voice": "🎤", "gui": "⌨", "typed": "⌨"}.get(ev.get("src"), "")
            self._append(f"{src} Вы  {ev.get('ts', '')}\n", "you")
            self._append(ev.get("text", "") + "\n", "")
        elif t == "reply":
            self._append(f"Джарвис  {ev.get('ts', '')}\n", "jarvis")
            self._append(ev.get("text", "") + "\n", "")
        elif t == "tool":
            args = json.dumps(ev.get("args", {}), ensure_ascii=False)[:120]
            self._append(f"⚙ {ev.get('name')}({args}) → {str(ev.get('result', ''))[:160]}\n", "tool")
        elif t == "info":
            self._append(f"{ev.get('text', '')}\n", "info")
        elif t == "live":
            txt = ev.get("text", "")
            self.live.config(text=("🎤 " + txt) if txt else "")
        elif t == "confirm":
            self._open_confirm(ev.get("q", ""))
        elif t == "confirm_done":
            self._close_confirm()

    def _open_confirm(self, question: str):
        tk = self.tk
        self._close_confirm()
        w = self.confirm_win = tk.Toplevel(self.root)
        w.title("Подтверждение")
        w.configure(bg=BG)
        w.attributes("-topmost", True)
        tk.Label(w, text=question, bg=BG, fg=FG, font=("Segoe UI", 12), wraplength=380, justify="left"
                 ).pack(padx=20, pady=(18, 10))
        row = tk.Frame(w, bg=BG)
        row.pack(pady=(0, 16))
        self._btn(row, "Да", lambda: self._answer(True), accent=True).pack(side="left", padx=6)
        self._btn(row, "Нет", lambda: self._answer(False)).pack(side="left", padx=6)
        w.protocol("WM_DELETE_WINDOW", lambda: self._answer(False))

    def _answer(self, v: bool):
        self.link.send({"t": "confirm_answer", "v": v})
        self._close_confirm()

    def _close_confirm(self):
        if self.confirm_win:
            self.confirm_win.destroy()
            self.confirm_win = None

    def _refresh_log(self):
        try:
            if self.nb.index(self.nb.select()) == 2:
                lines = (DATA / "jarvis.log").read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
                self.log.config(state="normal")
                self.log.delete("1.0", "end")
                self.log.insert("end", "\n".join(lines))
                self.log.config(state="disabled")
                self.log.see("end")
        except OSError:
            pass
        self.root.after(2500, self._refresh_log)

    def run(self):
        self.root.mainloop()


def make_icon_if_needed() -> bool:
    return ICO.exists() or make_icon()


def focus_existing() -> bool:
    """Если окно уже открыто — просто показываем его."""
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, TITLE)
    if hwnd:
        user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)
        return True
    return False


def main() -> None:
    if "--install-shortcut" in sys.argv:
        print(install_shortcuts())
        return
    ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\JarvisGuiMutex")
    if ctypes.windll.kernel32.GetLastError() == 183:      # окно уже запущено
        focus_existing()
        return
    App().run()


if __name__ == "__main__":
    main()
