"""
JARVIS — фоновый движок голосового агента для Windows (русский + английский, бесплатные нейросети).

Это «мотор»: он работает в фоне (значок в трее), постоянно слушает микрофон, показывает окно с
распознанным текстом сбоку экрана и выполняет команды. Графическое приложение (jarvis_gui.py) —
только пульт управления и чат, оно подключается к движку по локальному сокету.

Запуск:
    pythonw jarvis.py                     фоновый запуск без окна (так запускает приложение)
    python jarvis.py                      то же, но с консолью (для отладки)
    python jarvis.py --mic-test           проверка микрофона и распознавания
    python jarvis.py --install-autostart  запуск движка при входе в Windows (--remove-autostart — убрать)
"""
import argparse
import array
import ctypes
import difflib
import json
import logging
import math
import os
import queue
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = Path.home() / ".jarvis"
DATA.mkdir(exist_ok=True)

logging.basicConfig(filename=DATA / "jarvis.log", level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
log = logging.getLogger("jarvis")


# ------------------------------------------------------------ конфиг (.env)
def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            if v:                                   # пустые значения игнорируем
                os.environ.setdefault(k.strip(), v)


load_env(BASE / ".env")

WAKE_WORDS = [w.strip() for w in os.getenv(
    "WAKE_WORDS", "джарвис,жарвис,чарвис,джервис,джарви,jarvis").lower().split(",") if w.strip()]
VOSK_MODEL_DIR = Path(os.getenv("VOSK_MODEL", BASE / "model"))
# strict — только со словом активации; hybrid — без него только быстрые команды;
# open — реагировать на любую фразу (по умолчанию)
WAKE_MODE = os.getenv("WAKE_MODE", "open").lower()
AUTO_SEND_SECONDS = float(os.getenv("AUTO_SEND_SECONDS", "3"))   # 0 — выполнять сразу
LANGS = [x.strip() for x in os.getenv("LANGUAGES", "ru,en").lower().split(",") if x.strip()] or ["ru"]
WHISPER_ON = os.getenv("WHISPER", "1") != "0"
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")              # tiny/base/small/medium/large-v3-turbo
WHISPER_PROMPT = ("Джарвис, открой Telegram, Discord, Steam, Chrome. Громкость пятьдесят. Который час. "
                  "Jarvis, open Telegram. Volume fifty. What time is it? Take a screenshot.")
HALLUCINATIONS = ("субтитры", "продолжение следует", "спасибо за просмотр", "подписывайтесь",
                  "редактор субтитров", "корректор", "thanks for watching", "subtitles by", "amara.org")
MIN_RMS = float(os.getenv("MIC_THRESHOLD", "250"))     # минимальная громкость, считающаяся речью
END_SILENCE = float(os.getenv("END_SILENCE", "0.9"))   # пауза (с), после которой фраза считается законченной
MAX_PHRASE = 25.0
POPUP_POS = os.getenv("POPUP_POS", "right-bottom").lower()   # right|left - top|middle|bottom
POPUP_W = int(os.getenv("POPUP_WIDTH", "440"))
# Окно правки текста показывается всегда (даже при AUTO_SEND_SECONDS=0 — тогда пауза 3 с).
# EDIT_WINDOW=0 — отключить окно и выполнять команды сразу.
EDIT_WINDOW = os.getenv("EDIT_WINDOW", "1") != "0"
POS_FILE = DATA / "popup_pos.json"              # здесь запоминается, куда вы перетащили окно
IPC_PORT = int(os.getenv("JARVIS_PORT", "47615"))

import jarvis_core as core  # noqa: E402

STOP = threading.Event()
INBOX: queue.Queue = queue.Queue()      # (текст, источник, озвучивать?) — из окна ввода и из чата
_ui = None
_listener = None
RU = re.compile(r"[а-яё]", re.I)

# ------------------------------------------------------------ связь с графическим приложением
RECENT: deque = deque(maxlen=150)       # последние события чата — показываем новому клиенту
_clients: list = []
_clients_lock = threading.Lock()
TOKEN = ""
IPC_READY = threading.Event()
IPC_START_ERROR = ""


class _Client:
    def __init__(self, conn):
        self.conn, self.q, self.alive = conn, queue.Queue(500), True

    def push(self, line: bytes):
        try:
            self.q.put_nowait(line)
        except queue.Full:
            pass

    def writer(self):
        while self.alive:
            line = self.q.get()
            try:
                self.conn.sendall(line)
            except OSError:
                self.alive = False


def _line(ev: dict) -> bytes:
    return (json.dumps(ev, ensure_ascii=False) + "\n").encode("utf-8")


def emit(**ev) -> None:
    """Событие для графического приложения (чат, живой текст, состояние, подтверждения)."""
    if ev.get("t") in ("user", "reply", "tool"):
        ev["ts"] = time.strftime("%H:%M:%S")
        RECENT.append(ev)
    line = _line(ev)
    with _clients_lock:
        for c in list(_clients):
            if c.alive:
                c.push(line)
            else:
                _clients.remove(c)


def _get_token() -> str:
    f = DATA / "token"
    if f.exists() and f.read_text().strip():
        return f.read_text().strip()
    t = secrets.token_hex(16)
    f.write_text(t)
    return t


def _client_thread(conn) -> None:
    c = _Client(conn)
    try:
        rf = conn.makefile("r", encoding="utf-8")
        first = json.loads(rf.readline() or "{}")
        if first.get("token") != TOKEN:               # защита от чужих подключений (в т.ч. из браузера)
            conn.close()
            return
        threading.Thread(target=c.writer, daemon=True).start()
        for ev in list(RECENT):
            c.push(_line(ev))
        c.push(_line({"t": "hello", "commands": len(core.REGISTRY), "mode": WAKE_MODE, "langs": LANGS}))
        with _clients_lock:
            _clients.append(c)
        for raw in rf:
            try:
                _on_ipc(json.loads(raw))
            except Exception:  # noqa: BLE001
                log.exception("IPC message")
    except Exception:  # noqa: BLE001
        pass
    finally:
        c.alive = False
        try:
            conn.close()
        except OSError:
            pass


def _on_ipc(msg: dict) -> None:
    t = msg.get("t")
    if t == "chat" and msg.get("text", "").strip():
        INBOX.put((msg["text"], "gui", bool(msg.get("speak"))))
    elif t == "confirm_answer":
        answer_confirm(bool(msg.get("v")))
    elif t == "reload":
        n = core.load_plugins(BASE / "plugins")
        emit(t="info", text=f"Команды перезагружены: {len(core.REGISTRY)}")
        log.info("Плагинов: %d", n)
    elif t == "quit":
        STOP.set()


def serve_ipc() -> None:
    global IPC_START_ERROR
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind(("127.0.0.1", IPC_PORT))
        srv.listen(5)
        IPC_READY.set()
        log.info("IPC запущен на 127.0.0.1:%d", IPC_PORT)
    except OSError as exc:
        IPC_START_ERROR = f"{type(exc).__name__}: {exc}"
        log.exception("Не удалось открыть IPC-порт %d", IPC_PORT)
        IPC_READY.set()
        try:
            srv.close()
        except OSError:
            pass
        return
    try:
        while not STOP.is_set():
            try:
                conn, _ = srv.accept()
            except OSError:
                break
            threading.Thread(target=_client_thread, args=(conn,), daemon=True).start()
    finally:
        srv.close()


# ------------------------------------------------------------ голос: вывод (двуязычный)
_speak_lock = threading.Lock()
_muted = threading.Event()   # пока говорим — микрофон игнорируется
_reset = threading.Event()   # после речи Джарвиса сбросить распознаватель


def _pick_voice(eng, russian: bool):
    """Запасной выбор голоса для pyttsx3 (мужской предпочтительнее)."""
    voices = list(eng.getProperty("voices") or [])
    male_ru = ("pavel", "dmitry", "maxim", "nikolai", "boris", "ivan", "male", "мужск")
    male_en = ("david", "mark", "james", "george", "male", "richard", "ryan")
    female = ("irina", "zira", "helena", "catherine", "female", "женск", "anna", "marina")
    scored = []
    for v in voices:
        key = (getattr(v, "id", "") + " " + getattr(v, "name", "")).lower()
        tokens = set(re.split(r"[_\-\\/ .]+", key))
        score = 0
        if russian:
            if any(t in key for t in ("russian", "ru-ru", "ru_ru")) or "ru" in tokens:
                score += 50
            if any(m in key for m in male_ru):
                score += 40
            if any(f in key for f in female):
                score -= 30
        else:
            if any(t in key for t in ("english", "en-us", "en_us", "en-gb")) or "en" in tokens:
                score += 50
            if any(m in key for m in male_en):
                score += 40
            if any(f in key for f in female):
                score -= 30
        scored.append((score, v.id))
    scored.sort(reverse=True)
    return scored[0][1] if scored and scored[0][0] > 0 else (voices[0].id if voices else None)


def _play_mp3(path: str) -> None:
    """Проигрывает mp3 через встроенный в Windows MCI (надёжнее playsound, повторные вызовы не ломаются)."""
    import ctypes
    winmm = ctypes.windll.winmm  # type: ignore[attr-defined]
    short = ctypes.create_unicode_buffer(520)             # короткий путь — без проблем с кириллицей в имени
    if ctypes.windll.kernel32.GetShortPathNameW(path, short, 520):  # type: ignore[attr-defined]
        path = short.value
    alias = f"jv{int(time.time() * 1000) % 10**9}"

    def send(cmd: str) -> None:
        err = winmm.mciSendStringW(cmd, None, 0, 0)
        if err:
            msg = ctypes.create_unicode_buffer(256)
            winmm.mciGetErrorStringW(err, msg, 255)
            raise RuntimeError(f"MCI «{cmd}»: {msg.value}")

    send(f'open "{path}" type mpegvideo alias {alias}')
    try:
        send(f"play {alias} wait")
    finally:
        try:
            send(f"close {alias}")
        except RuntimeError:
            pass


def _speak_edge(text: str, russian: bool) -> bool:
    """Нейросетевой голос Microsoft Edge (близко к Джарвису из фильма). Бесплатно, без ключа.
    При сбое пробует ещё раз и только потом отдаёт управление запасному голосу."""
    try:
        import asyncio
        import edge_tts
        import tempfile
    except ImportError:
        log.error("edge-tts не установлен: pip install edge-tts")
        return False

    # Британский мужской — максимально «железный человек». Для русского — Дмитрий.
    # Голос должен знать язык текста: английский Райан не умеет читать русский (будет NoAudioReceived).
    default_voice = "ru-RU-DmitryNeural" if russian else "en-GB-RyanNeural"
    lang_prefix = "ru-" if russian else "en-"
    voice = os.getenv("EDGE_VOICE_RU" if russian else "EDGE_VOICE_EN", "").strip()
    if not voice:
        old = os.getenv("EDGE_VOICE", "").strip()
        voice = old if old.lower().startswith(lang_prefix) else default_voice   # EDGE_VOICE — только если язык подходит
    rate = os.getenv("TTS_RATE_EDGE", "-5%")   # чуть медленнее = спокойнее/солиднее
    pitch = os.getenv("TTS_PITCH", "-2Hz")

    async def _run(v, r, p):
        communicate = edge_tts.Communicate(text, v, rate=r, pitch=p)
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            path = f.name
        await communicate.save(path)
        return path

    for attempt in (1, 2):
        tmp = ""
        try:
            # попытка 2 — со стандартными параметрами (если ваши голос/скорость/тон не принимаются)
            args = (voice, rate, pitch) if attempt == 1 else (default_voice, "+0%", "+0Hz")
            tmp = asyncio.run(asyncio.wait_for(_run(*args), timeout=25))   # нет интернета/завис — не ждём вечно
            done, failed = threading.Event(), []

            def _play(path=tmp):
                try:
                    _play_mp3(path)
                except Exception as e:  # noqa: BLE001
                    failed.append(e)
                finally:
                    done.set()

            threading.Thread(target=_play, daemon=True).start()
            if not done.wait(timeout=max(20, len(text) * 0.2 + 10)):
                raise TimeoutError("воспроизведение зависло")
            if failed:
                raise failed[0]
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("Edge-TTS: попытка %d (голос %s) не удалась: %r", attempt,
                        voice if attempt == 1 else default_voice, e)
            time.sleep(0.4)
        finally:
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
    return False


def _speak_pyttsx3(text: str, russian: bool) -> None:
    try:
        import comtypes
        comtypes.CoInitialize()
    except Exception:  # noqa: BLE001
        pass
    import pyttsx3
    eng = pyttsx3.init()
    voice = _pick_voice(eng, russian)
    if voice:
        eng.setProperty("voice", voice)
    eng.setProperty("rate", int(os.getenv("TTS_RATE", "165")))
    try:
        eng.setProperty("volume", 1.0)
    except Exception:
        pass
    eng.say(text)
    eng.runAndWait()


def speak(text: str, tts: bool = True, popup: bool = True) -> None:
    log.info("JARVIS: %s", text)
    if sys.stdout is not None:
        print("JARVIS:", text)
    emit(t="reply", text=text)
    if popup and _ui is not None:
        _ui.reply(text)
    if not tts:
        return
    with _speak_lock:
        _muted.set()
        try:
            russian = bool(RU.search(text))
            engine = os.getenv("TTS_ENGINE", "edge").lower()  # edge | pyttsx3
            ok = False
            if engine != "pyttsx3":
                ok = _speak_edge(text, russian)
            if not ok and (engine == "pyttsx3" or os.getenv("TTS_FALLBACK", "1") != "0"):
                _speak_pyttsx3(text, russian)
        except Exception:  # noqa: BLE001
            log.exception("TTS error")
        finally:
            time.sleep(0.35)
            _reset.set()
            _muted.clear()


# ------------------------------------------------------------ голос: ввод
def _mic_device():
    d = os.getenv("MIC_DEVICE", "").strip()
    if not d:
        return None
    return int(d) if d.isdigit() else d


def _normalize(text: str) -> str:
    t = re.sub(r"[^\w\s-]", " ", text.lower())
    return " ".join(t.split())


def _rms(data: bytes) -> float:
    a = array.array("h", data)
    return math.sqrt(sum(x * x for x in a) / len(a)) if a else 0.0


class Listener:
    """Непрерывный слух. Границы фраз ищет по громкости (работает для любого языка),
    Vosk показывает «живой» текст по-русски, а итоговый текст на русском/английском
    выдаёт Whisper (офлайн)."""

    def __init__(self, load_whisper: bool = True):
        import sounddevice as sd
        self.rec = None
        if VOSK_MODEL_DIR.exists():
            import vosk
            vosk.SetLogLevel(-1)
            self.rec = vosk.KaldiRecognizer(vosk.Model(str(VOSK_MODEL_DIR)), 16000)
        else:
            log.warning("Модель Vosk не найдена (%s): «живого» текста не будет", VOSK_MODEL_DIR)
        self.q: queue.Queue = queue.Queue()
        self.ring: deque = deque(maxlen=8)            # ~0.8 с звука до начала речи
        self.buf: list = []
        self.speaking = False
        self.silence, self.last_chunk = 0, 0.0           # тишина в блоках по 0.1 с
        self.hot = self.voiced = 0
        self.floor = 100.0                            # уровень фонового шума
        self.committed = self.last_live = ""
        self.whisper = None
        self._hot_ok = True
        if load_whisper and WHISPER_ON:
            self._load_whisper()
        if load_whisper and not self.rec and not self.whisper:
            raise SystemExit("Нет ни модели Vosk, ни Whisper. Установите faster-whisper или скачайте модель Vosk.")
        self.stream = sd.RawInputStream(
            samplerate=16000, blocksize=1600, dtype="int16", channels=1, device=_mic_device(),
            callback=lambda data, *_: self.q.put(bytes(data)))
        self.stream.start()
        log.info("Микрофон открыт: %s", sd.query_devices(_mic_device(), "input")["name"])

    def _load_whisper(self):
        try:
            from faster_whisper import WhisperModel
            self.whisper = WhisperModel(WHISPER_MODEL, device=os.getenv("WHISPER_DEVICE", "cpu"),
                                        compute_type=os.getenv("WHISPER_COMPUTE", "int8"))
            log.info("Whisper загружен: %s, языки: %s", WHISPER_MODEL, LANGS)
        except ImportError:
            log.warning("faster-whisper не установлен: точность ниже (pip install faster-whisper)")
        except Exception:  # noqa: BLE001
            log.exception("Не удалось загрузить Whisper")

    def _drain(self):
        while not self.q.empty():
            self.q.get_nowait()

    def _reset_state(self, drain: bool = False):
        if drain:
            self._drain()
        self.ring.clear()
        self.buf, self.speaking, self.hot, self.voiced = [], False, 0, 0
        self.committed = self.last_live = ""
        if self.rec:
            self.rec.Reset()

    def _vosk(self, data: bytes, on_partial):
        if not self.rec:
            return
        if self.rec.AcceptWaveform(data):
            t = json.loads(self.rec.Result()).get("text", "")
            if t:
                self.committed = (self.committed + " " + t).strip()
            part = ""
        else:
            part = json.loads(self.rec.PartialResult()).get("partial", "")
        live = (self.committed + " " + part).strip()
        if live and live != self.last_live and on_partial:
            on_partial(live)
            self.last_live = live

    def _transcribe(self, pcm, language):
        kw = dict(language=language, beam_size=5, vad_filter=True, temperature=0.0,
                  condition_on_previous_text=False, initial_prompt=WHISPER_PROMPT)
        if self._hot_ok:
            kw["hotwords"] = "Джарвис Jarvis"
        try:
            return self.whisper.transcribe(pcm, **kw)
        except TypeError:                                  # старая версия без hotwords
            self._hot_ok = False
            kw.pop("hotwords", None)
            return self.whisper.transcribe(pcm, **kw)

    def _refine(self, audio: bytes, fallback: str) -> str:
        """Точный текст через Whisper (ru/en автоматически); при проблеме — текст Vosk."""
        if not self.whisper or len(audio) < 16000 * 2 * 0.3:
            return fallback
        try:
            import numpy as np
            pcm = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
            multi = len(LANGS) > 1
            segs, info = self._transcribe(pcm, None if multi else LANGS[0])
            if multi and getattr(info, "language", None) not in LANGS:
                segs, info = self._transcribe(pcm, LANGS[0])
            parts = [sg.text for sg in segs if sg.no_speech_prob <= 0.6 and sg.avg_logprob >= -1.2]
            text = _normalize(" ".join(parts))
            log.info("Whisper[%s]: %s", getattr(info, "language", "?"), text)
        except Exception:  # noqa: BLE001
            log.exception("Whisper error")
            return fallback
        return "" if any(h in text for h in HALLUCINATIONS) else text

    def _finish(self) -> str:
        audio, voiced = b"".join(self.buf), self.voiced
        vosk_text = ""
        if self.rec:
            vosk_text = (self.committed + " " + json.loads(self.rec.FinalResult()).get("text", "")).strip()
        self._reset_state()
        if voiced < 3:                                    # щелчок или шум короче 0.3 с
            return ""
        return self._refine(audio, vosk_text)

    def phrase(self, timeout: float = 1.0, on_partial=None) -> str:
        """Ждёт начала речи до timeout секунд; если речь началась — ждёт конца фразы.
        on_partial(text) — «живой» текст (пустая строка — речь началась, текста пока нет)."""
        t0 = time.time()
        while True:
            if _reset.is_set() and not _muted.is_set():
                self._reset_state(drain=True)
                _reset.clear()
            try:
                data = self.q.get(timeout=0.2)
            except queue.Empty:
                if not self.speaking and time.time() - t0 > timeout:
                    return ""
                if self.speaking and time.time() - self.last_chunk > 2.0:    # поток звука замер
                    return self._finish()
                continue
            if _muted.is_set():
                continue                                  # пока Джарвис говорит — не слушаем себя
            now, level = time.time(), None
            level = _rms(data)
            voiced = level > max(MIN_RMS, self.floor * 3.0)
            if not self.speaking:
                self.ring.append(data)
                if voiced:
                    self.hot += 1
                else:
                    self.hot = 0
                    self.floor = 0.98 * self.floor + 0.02 * level
                if self.hot >= 2:
                    self.speaking, self.buf = True, list(self.ring)
                    self.silence, self.last_chunk = 0, now
                    self.voiced, self.committed, self.last_live = self.hot, "", ""
                    if on_partial:
                        on_partial("")
                    for ch in self.buf:
                        self._vosk(ch, on_partial)
                elif now - t0 > timeout:
                    return ""
                continue
            self.buf.append(data)
            self.last_chunk = now
            if voiced:
                self.silence, self.voiced = 0, self.voiced + 1
            else:
                self.silence += 1
            self._vosk(data, on_partial)
            if self.silence * 0.1 >= END_SILENCE or len(self.buf) * 0.1 > MAX_PHRASE:
                return self._finish()


_PH = {"щ": "sch", "ш": "sh", "ч": "ch", "ж": "j", "ц": "ts", "х": "h", "й": "y", "ю": "yu", "я": "ya",
       "ё": "e", "э": "e", "ы": "y", "ъ": "", "ь": "", "а": "a", "б": "b", "в": "v", "г": "g", "д": "d",
       "е": "e", "з": "z", "и": "i", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
       "с": "s", "т": "t", "у": "u", "ф": "f"}


def _phon(s: str) -> str:
    """Приблизительная латинская запись по звучанию: «джарвис», «жарвис», «jarvis» -> «jarvis»."""
    s = s.lower().replace("дж", "j")
    return "".join(_PH.get(c, c) for c in s).replace("w", "v")


def find_wake(text: str):
    """Ищет слово активации с допуском на ошибки распознавания и на алфавит (Whisper может написать
    «Джарвис» кириллицей, а в WAKE_WORDS стоит jarvis). Возвращает остаток фразы или None."""
    words = text.split()
    wake = [(w, _phon(w)) for w in WAKE_WORDS]

    def close(word: str) -> bool:
        pw = _phon(word)
        sm = difflib.SequenceMatcher
        return any(sm(None, word, w).ratio() >= 0.72 or sm(None, pw, pwk).ratio() >= 0.74 for w, pwk in wake)

    for i, w in enumerate(words):
        if close(w):
            return " ".join(words[i + 1:])
    for i in range(len(words) - 1):                       # «жар вис» -> «жарвис»
        if close(words[i] + words[i + 1]):
            return " ".join(words[i + 2:])
    return None


def mic_test() -> None:
    """Диагностика: микрофоны, уровень шума/голоса и то, что слышит Джарвис."""
    import sounddevice as sd
    print("\nУстройства ввода (номер: название):")
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            print(f"  {i}: {d['name']}{'  <- по умолчанию' if i == sd.default.device[0] else ''}")
    print("\nЗагружаю модели…")
    lst = Listener(load_whisper=True)
    for label, secs in (("Молчите 2 секунды…", 2), ("Теперь скажите что-нибудь обычным голосом (3 секунды)…", 3)):
        print(label)
        end, levels = time.time() + secs, []
        while time.time() < end:
            try:
                levels.append(_rms(lst.q.get(timeout=0.3)))
            except queue.Empty:
                pass
        print(f"   уровень: средний {sum(levels) / max(1, len(levels)):.0f}, максимум {max(levels, default=0):.0f}")
    print("\nЕсли «максимум» при речи меньше 300 — микрофон слишком тихий (поднимите громкость микрофона в Windows"
          "\nили задайте MIC_THRESHOLD пониже, например 120). Если шум выше 200 — повысьте MIC_THRESHOLD.")
    print("\nТеперь говорите (60 секунд). Показываю, что Джарвис понял:\n")
    lst._reset_state(drain=True)
    end = time.time() + 60
    while time.time() < end:
        txt = lst.phrase(timeout=1.0, on_partial=lambda t: print("\r  … " + t[:70].ljust(70), end="", flush=True))
        if txt:
            wake = "ДА" if find_wake(txt) is not None else "нет"
            print(f"\n  ✔ ПОНЯЛ: «{txt}»   (слово активации: {wake})")
    print("\nТест окончен.")


# ------------------------------------------------------------ LLM: бесплатные провайдеры (много ключей + приоритет)
PROVIDERS = [
    # name, base_url, default_model, key_env, strength
    ("groq", "https://api.groq.com/openai/v1", "openai/gpt-oss-120b", "GROQ_API_KEY", 100),
    ("gemini", "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.5-flash", "GEMINI_API_KEY", 90),
    ("openrouter", "https://openrouter.ai/api/v1", "nvidia/nemotron-3-ultra-550b-a55b:free", "OPENROUTER_API_KEY", 85),
    ("cerebras", "https://api.cerebras.ai/v1", "llama-3.3-70b", "CEREBRAS_API_KEY", 70),
    ("modelscope", "https://api-inference.modelscope.cn/v1", "Qwen/Qwen3.8-Flash-Next", "MODELSCOPE_API_KEY", 55),
    ("siliconflow", "https://api.siliconflow.cn/v1", "Qwen/Qwen2.5-7B-Instruct", "SILICONFLOW_API_KEY", 50),
    ("zhipu", "https://open.bigmodel.cn/api/paas/v4", "glm-4-flash", "ZHIPU_API_KEY", 45),
    ("ollama", "http://localhost:11434/v1", "qwen2.5:7b", "OLLAMA_ENABLED", 10),
]

SYSTEM_PROMPT = """Ты — Джарвис (Jarvis), голосовой ИИ-ассистент, который УПРАВЛЯЕТ компьютером пользователя \
под Windows. У тебя полный доступ к компьютеру через инструменты: программы, окна, мышь и клавиатура, \
звук, файлы и папки, интернет, процессы, службы, реестр, установка программ, PowerShell. ВСЕГДА выполняй \
просьбу инструментом, а не объясняй, как сделать это вручную. Никогда не говори «я не могу» или «сделайте \
вручную» — найди подходящий инструмент. Если нужного инструмента нет в списке — вызови more_tools(group), \
чтобы подключить группу (files, web, windows, system, notes, vision), а в крайнем случае используй run_powershell. \
Текст приходит из распознавания речи и часто содержит ошибки. Угадывай смысл и названия программ: \
«огненные леса» / «файр фокс» = Firefox, «хром» / «гугл» = Chrome, «телега» / «тг» = Telegram, \
«дискард» = Discord, «вс код» = VS Code. Отвечай на том же языке, очень коротко (1–2 фразы). \
Деструктивные действия — только по явной просьбе. Если инструмент вернул ошибку — честно скажи."""

_cooldown: dict[str, float] = {}
_model_override: dict[str, str] = {}
history: list[dict] = []
_key_index: dict[str, int] = {}


def _keys_for(env_name: str) -> list[str]:
    keys = []
    for var in (env_name, env_name + "S"):
        raw = os.getenv(var, "")
        if raw and raw not in ("0", "1", "true", "false"):
            keys.extend(k.strip() for k in re.split(r"[,;\s]+", raw) if k.strip() and len(k.strip()) > 8)
    i = 1
    while True:
        k = os.getenv(f"{env_name}_{i}", "").strip()
        if not k:
            break
        keys.append(k)
        i += 1
    seen, out = set(), []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _clients_llm():
    from openai import OpenAI
    ordered = sorted(PROVIDERS, key=lambda x: -x[4])
    for name, url, model, keyvar, _str in ordered:
        if name == "ollama":
            if not os.getenv("OLLAMA_ENABLED"):
                continue
            if time.time() < _cooldown.get(name, 0):
                continue
            yield name, OpenAI(base_url=url, api_key="ollama", timeout=60, max_retries=0), \
                os.getenv("OLLAMA_MODEL") or _model_override.get(name) or model
            continue
        keys = _keys_for(keyvar)
        if not keys:
            continue
        start = _key_index.get(name, 0) % len(keys)
        for off in range(len(keys)):
            idx = (start + off) % len(keys)
            key = keys[idx]
            ck = f"{name}|{key[:12]}"
            if time.time() < _cooldown.get(ck, 0) or time.time() < _cooldown.get(name, 0):
                continue
            _key_index[name] = idx + 1
            yield name, OpenAI(base_url=url, api_key=key, timeout=35, max_retries=0), \
                os.getenv(f"{name.upper()}_MODEL") or _model_override.get(name) or model


def _discover(client, current: str):
    try:
        ids = [m.id for m in client.models.list().data]
    except Exception:  # noqa: BLE001
        return None
    bad = ("whisper", "guard", "tts", "embed", "orpheus", "playai", "safeguard", "compound", "image", "moderation")
    ids = [i for i in ids if i != current and not any(b in i.lower() for b in bad)]
    for pref in ("gpt-oss-120b", "gpt-oss-20b", "70b", "flash", "llama-3.3", "qwen3", "qwen2.5", "nemotron", "glm-4"):
        for i in ids:
            if pref in i.lower():
                return i
    return ids[0] if ids else None


def _chat(messages, tools):
    last_err = None
    tried = set()
    for name, client, model in _clients_llm():
        key_id = getattr(client, "api_key", "")[:12]
        ck = f"{name}|{key_id}"
        if ck in tried:
            continue
        tried.add(ck)
        for attempt in (1, 2):
            try:
                resp = client.chat.completions.create(model=model, messages=messages, tools=tools,
                                                      max_tokens=700)
                log.info("LLM provider: %s (%s) key=%s...", name, model, key_id)
                return resp.choices[0].message
            except Exception as e:  # noqa: BLE001
                log.warning("Провайдер %s (%s) не сработал: %s", name, model, e)
                last_err, s = e, str(e).lower()
                if attempt == 1 and ("404" in s or "does not exist" in s or "not found" in s or ("model" in s and "invalid" in s)):
                    new = _discover(client, model)
                    if new:
                        _model_override[name] = model = new
                        continue
                wait = 90 if ("429" in s or "rate" in s or "quota" in s or "limit" in s) else 45
                _cooldown[ck] = time.time() + wait
                if "429" in s or "rate" in s:
                    _cooldown[name] = time.time() + 15
                break
    raise RuntimeError(f"Все провайдеры/ключи недоступны: {last_err}")


def _window(h: list[dict], n: int = 18) -> list[dict]:
    """Последние сообщения, начиная с реплики пользователя (чтобы не оборвать пару вызов/результат)."""
    w = h[-n:]
    for i, m in enumerate(w):
        if m["role"] == "user":
            return w[i:]
    return w


def _more_tools_schema(active: set) -> dict | None:
    left = {g: i["desc"] for g, i in core.GROUPS.items() if g not in active}
    if not left:
        return None
    desc = "Подключить дополнительные инструменты. Группы: " + "; ".join(f"{g} — {d}" for g, d in left.items())
    return {"type": "function", "function": {"name": "more_tools", "description": desc, "parameters": {
        "type": "object", "properties": {"group": {"type": "string"}}, "required": ["group"]}}}


def agent(user_text: str, max_steps: int = 10) -> str:
    active = core.detect_groups(user_text)
    history.append({"role": "user", "content": user_text})
    for _ in range(max_steps):
        tools = core.tools_for_llm(active)
        extra = _more_tools_schema(active)
        if extra:
            tools.append(extra)
        msg = _chat([{"role": "system", "content": SYSTEM_PROMPT}] + _window(history), tools)
        entry = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            entry["tool_calls"] = [
                {"id": t.id, "type": "function",
                 "function": {"name": t.function.name, "arguments": t.function.arguments or "{}"}}
                for t in msg.tool_calls]
        history.append(entry)
        if not msg.tool_calls:
            return (msg.content or "Готово.").strip()
        for t in msg.tool_calls:
            try:
                args = json.loads(t.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            name = t.function.name
            if name == "more_tools":
                g = args.get("group", "")
                if g in core.GROUPS:
                    active.add(g)
                    result = f"Подключено: {g}. Доступно: " + ", ".join(
                        c.name for c in core.REGISTRY.values() if c.group == g)
                else:
                    result = "Нет такой группы. Есть: " + ", ".join(core.GROUPS)
            else:
                result = core.run_command(name, args)
            log.info("tool %s %s -> %s", name, args, result[:120])
            emit(t="tool", name=name, args=args, result=result[:300])
            history.append({"role": "tool", "tool_call_id": t.id, "content": result[:1500]})
    return "Не удалось завершить задачу за разумное число шагов."


# ------------------------------------------------------------ обработка команды
FILLERS = re.compile(
    r"\b(пожалуйста|плиз|ну|давай|мне|можешь|можно|а|э|эм|ладно|да|please|hey|okay|ok|uh|um|"
    r"can you|could you|would you)\b")
VERBS = ("открой", "запусти", "включи", "закрой", "выключи", "найди", "поищи", "загугли", "поставь",
         "сделай", "громкость", "заблокируй", "перейди", "переключись", "сверни", "покажи", "пауза",
         "скриншот", "таймер", "следующий", "предыдущий", "потише", "погромче", "запиши", "запомни",
         "open", "launch", "start", "run", "close", "quit", "search", "google", "look up", "volume", "mute",
         "unmute", "screenshot", "timer", "lock", "switch to", "show", "go to", "pause", "resume", "next",
         "previous", "louder", "quieter", "take a", "what", "weather", "note")
EXIT_PHRASES = ("отбой", "завершить работу", "выключись", "shut down jarvis", "exit jarvis", "go to sleep jarvis")


def clean_command(text: str) -> str:
    """Убирает слова-паразиты и мусор в начале («да вес а открой пожалуйста телеграмм» -> «открой телеграмм»)."""
    t = " ".join(FILLERS.sub(" ", text).split())
    starts = [m.start() for v in VERBS if (m := re.search(r"\b" + v, t))]
    return t[min(starts):] if starts else t


def handle(text: str, src: str = "voice", tts: bool = True) -> None:
    text = text.strip()
    if not text:
        return
    emit(t="user", text=text, src=src)
    say = lambda m: speak(m, tts=tts, popup=(src != "gui"))   # noqa: E731
    log.info("USER(%s): %s", src, text)
    if any(p in text.lower() for p in EXIT_PHRASES):
        say("До связи." if RU.search(text) else "See you.")
        STOP.set()
        return
    fast = core.match_fast(text) or core.match_fast(clean_command(text))   # 1) быстрый офлайн-путь
    if fast:
        name, args = fast
        result = core.run_command(name, args)
        emit(t="tool", name=name, args=args, result=result[:300])
        say(result)
        return
    try:                                                                   # 2) агент на бесплатном LLM
        say(agent(text))
    except Exception as e:  # noqa: BLE001
        log.error("agent: %s", e)
        say("Нейросеть сейчас недоступна. Базовые команды работают." if RU.search(text)
            else "The AI is unavailable right now. Basic commands still work.")


# ------------------------------------------------------------ подтверждения (голос / кнопки / чат)
_pending: dict = {}
YES = ("да", "давай", "подтверждаю", "ага", "yes", "yeah", "yep", "sure", "confirm", "okay", "ok")
NO = ("нет", "отмена", "не", "no", "cancel", "stop", "nope")


def answer_confirm(value: bool) -> None:
    h = _pending.get("h")
    if h:
        h[1]["v"] = value
        h[0].set()


def ask_confirm(question: str) -> bool:
    ev, holder = threading.Event(), {"v": False}
    _pending["h"] = (ev, holder)
    emit(t="confirm", q=question)
    if _ui is not None:
        _ui.ask(question, answer_confirm)
    ru = bool(RU.search(question))
    speak(question + (" Скажите «да» или «нет»." if ru else " Say yes or no."), popup=False)
    deadline = time.time() + 25
    while not ev.is_set() and time.time() < deadline and not STOP.is_set():
        if _listener:
            words = _listener.phrase(timeout=1.0).split()
            if any(w in YES for w in words):
                answer_confirm(True)
            elif any(w in NO for w in words):
                answer_confirm(False)
        else:
            ev.wait(1.0)
    _pending.clear()
    emit(t="confirm_done")
    if _ui is not None:
        _ui.close_ask()
    return bool(holder["v"])


# ------------------------------------------------------------ окно с редактируемым текстом (сбоку экрана)
class UI:
    """Небольшое окно сбоку экрана: показывает, что вы говорите, даёт поправить текст (как строка поиска
    Google), показывает ответы и запросы подтверждения. Доступ из других потоков — через очередь."""
    BG, PANEL, FG, ACC, DIM = "#0f172a", "#1e293b", "#e2e8f0", "#38bdf8", "#94a3b8"

    def __init__(self):
        import tkinter as tk
        self.root = tk.Tk()
        self.root.withdraw()
        self.jobs: queue.Queue = queue.Queue()
        self.mode = "idle"                  # idle | listening | editing | typing | reply | asking
        self._ev = None
        self._holder: dict = {}
        self._count_job = self._hide_job = None
        self._counting = False
        self._remaining = 0.0
        self._on_answer = None
        self.pos = self._load_pos()
        self._dx = self._dy = 0

        w = self.win = tk.Toplevel(self.root)
        w.withdraw()
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.configure(bg=self.BG, highlightthickness=1, highlightbackground=self.ACC)
        bar = tk.Frame(w, bg=self.PANEL, cursor="fleur")            # «заголовок» окна — за него таскаем
        bar.pack(fill="x")
        grip = tk.Label(bar, text="\u283f\u283f\u283f  Джарвис — перетащите, чтобы переместить", bg=self.PANEL,
                        fg=self.DIM, font=("Segoe UI", 8), cursor="fleur")
        grip.pack(side="left", padx=8, pady=2)
        self.status = tk.Label(w, anchor="w", bg=self.BG, fg=self.ACC, font=("Segoe UI", 10, "bold"),
                               cursor="fleur")
        self.status.pack(fill="x", padx=12, pady=(7, 2))
        for wd in (bar, grip, self.status):
            wd.bind("<ButtonPress-1>", self._drag_start)
            wd.bind("<B1-Motion>", self._drag_move)
            wd.bind("<ButtonRelease-1>", self._drag_end)
        self.row = tk.Frame(w, bg=self.BG)
        self.var = tk.StringVar()
        self.entry = tk.Entry(self.row, textvariable=self.var, font=("Segoe UI", 13), bg=self.PANEL,
                              fg=self.FG, insertbackground=self.FG, relief="flat",
                              readonlybackground=self.PANEL)
        self.entry.pack(side="left", fill="x", expand=True, ipady=6)
        tk.Button(self.row, text="\u25b6", command=self._submit, bg=self.ACC, fg="#04111d", relief="flat",
                  font=("Segoe UI", 11, "bold"), width=3, cursor="hand2").pack(side="left", padx=(6, 0))
        tk.Button(self.row, text="\u2715", command=self._cancel, bg=self.PANEL, fg=self.FG, relief="flat",
                  font=("Segoe UI", 11), width=3, cursor="hand2").pack(side="left", padx=(4, 0))
        self.btns = tk.Frame(w, bg=self.BG)
        tk.Button(self.btns, text="Да / Yes", command=lambda: self._answer(True), bg=self.ACC, fg="#04111d",
                  relief="flat", font=("Segoe UI", 11, "bold"), cursor="hand2").pack(side="left", expand=True,
                                                                                    fill="x", padx=(0, 4))
        tk.Button(self.btns, text="Нет / No", command=lambda: self._answer(False), bg=self.PANEL, fg=self.FG,
                  relief="flat", font=("Segoe UI", 11), cursor="hand2").pack(side="left", expand=True, fill="x")
        self.hint = tk.Label(w, anchor="w", justify="left", wraplength=POPUP_W - 30, bg=self.BG, fg=self.DIM,
                             font=("Segoe UI", 10))
        self.hint.pack(fill="x", padx=12, pady=(3, 9))
        self.entry.bind("<Return>", lambda e: self._submit())
        self.entry.bind("<Escape>", lambda e: self._cancel())
        self.entry.bind("<Key>", lambda e: self._stop_count(), add="+")
        self.entry.bind("<Button-1>", self._on_click)
        self.root.after(40, self._pump)

    # ---- служебное (поток интерфейса) ----
    def post(self, fn):
        self.jobs.put(fn)

    def _pump(self):
        while True:
            try:
                fn = self.jobs.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception:  # noqa: BLE001
                log.exception("UI job")
        if STOP.is_set():
            self.root.quit()
            return
        self.root.after(40, self._pump)

    def run(self):
        self.root.mainloop()

    # ---- перетаскивание окна ----
    def _load_pos(self):
        try:
            d = json.loads(POS_FILE.read_text(encoding="utf-8"))
            return int(d["x"]), int(d["y"])
        except Exception:  # noqa: BLE001
            return None

    def _drag_start(self, e):
        if self.mode == "editing":
            self._stop_count()                 # взялись за окно — таймер автоотправки останавливаем
        self._dx, self._dy = e.x_root - self.win.winfo_x(), e.y_root - self.win.winfo_y()

    def _drag_move(self, e):
        self.win.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def _drag_end(self, e):
        self.pos = (self.win.winfo_x(), self.win.winfo_y())
        try:
            POS_FILE.write_text(json.dumps({"x": self.pos[0], "y": self.pos[1]}), encoding="utf-8")
        except OSError:
            pass

    def _place(self):
        w = self.win
        w.update_idletasks()
        h = w.winfo_reqheight()
        sw, sh = w.winfo_screenwidth(), w.winfo_screenheight()
        if self.pos:                           # место, куда вы перетащили окно
            x = min(max(self.pos[0], 0), max(0, sw - 120))
            y = min(max(self.pos[1], 0), max(0, sh - 60))
        else:
            side, _, vert = POPUP_POS.partition("-")
            x = 18 if side == "left" else sw - POPUP_W - 18
            y = {"top": 60, "middle": (sh - h) // 2}.get(vert, sh - h - 80)
        w.geometry(f"{POPUP_W}x{h}+{x}+{y}")
        if not w.winfo_viewable():
            w.deiconify()
        w.lift()

    def _set_hint(self, text, color=None):
        self.hint.config(text=text, fg=color or self.DIM)

    def _show(self, status, text, state, hint=""):
        self._cancel_hide()
        self.btns.pack_forget()
        self.status.config(text=status)
        self.row.pack(fill="x", padx=12, pady=4, before=self.hint)
        self.entry.config(state="normal")
        self.var.set(text)
        self.entry.config(state=state)
        self._set_hint(hint)
        self._place()

    def _cancel_hide(self):
        if self._hide_job:
            self.root.after_cancel(self._hide_job)
            self._hide_job = None

    def _hide(self):
        self._cancel_hide()
        self._counting = False
        if self._count_job:
            self.root.after_cancel(self._count_job)
            self._count_job = None
        self.win.withdraw()
        self.mode = "idle"

    def _on_click(self, _e):
        if self.mode in ("editing", "typing"):
            self._stop_count()
            self.entry.focus_force()

    # ---- «живой» текст ----
    def partial(self, text):
        self.post(lambda: self._ui_partial(text))

    def _ui_partial(self, text):
        if self.mode in ("editing", "typing", "asking"):
            return
        self.mode = "listening"
        self._show("\U0001f3a4 Слушаю… / Listening…", text, "readonly")

    def hide_listening(self):
        self.post(lambda: self.mode == "listening" and self._hide())

    # ---- ответ Джарвиса ----
    def reply(self, text):
        self.post(lambda: self._ui_reply(text))

    def _ui_reply(self, text):
        if self.mode in ("editing", "typing", "asking") or not text:
            return
        self.mode = "reply"
        self._cancel_hide()
        self.btns.pack_forget()
        self.status.config(text="\U0001f916 Джарвис")
        self.row.pack_forget()
        self._set_hint(text, self.FG)
        self._place()
        self._hide_job = self.root.after(max(3000, 70 * len(text)), self._hide)

    # ---- подтверждение ----
    def ask(self, question, on_answer):
        self.post(lambda: self._ui_ask(question, on_answer))

    def _ui_ask(self, question, on_answer):
        self._hide()
        self.mode, self._on_answer = "asking", on_answer
        self.status.config(text="\u26a0\ufe0f Подтвердите / Confirm")
        self.row.pack_forget()
        self.btns.pack(fill="x", padx=12, pady=4, before=self.hint)
        self._set_hint(question, self.FG)
        self._place()

    def _answer(self, v):
        cb = self._on_answer
        self._hide()
        if cb:
            cb(v)

    def close_ask(self):
        self.post(lambda: self.mode == "asking" and self._hide())

    # ---- редактирование распознанного текста (вызывается из рабочего потока, блокирует) ----
    def edit(self, text, delay):
        ev, holder = threading.Event(), {}
        self.post(lambda: self._ui_edit(text, delay, ev, holder))
        ev.wait()
        return holder.get("text")

    def _ui_edit(self, text, delay, ev, holder):
        self.mode = "editing"
        self._ev, self._holder = ev, holder
        self._show("\u270f\ufe0f Распознано / Recognized", text, "normal")
        self.entry.icursor("end")
        if delay <= 0 and EDIT_WINDOW:
            delay = 3.0                        # окно правки показываем всегда
        if delay <= 0:
            self._finish(text)
            return
        self._counting, self._remaining = True, delay
        self._tick()

    def _tick(self):
        if not self._counting or self.mode != "editing":
            return
        if self._remaining <= 0:
            self._finish(self.var.get())
            return
        self._set_hint(f"Выполню через {self._remaining:.1f} с · клик по тексту — исправить · "
                       "Enter — сразу · Esc — отмена")
        self._remaining -= 0.1
        self._count_job = self.root.after(100, self._tick)

    def _stop_count(self):
        if self._counting:
            self._counting = False
            if self._count_job:
                self.root.after_cancel(self._count_job)
                self._count_job = None
            self._set_hint("Исправьте текст и нажмите Enter · Esc — отмена")

    def _finish(self, text):
        ev, holder = self._ev, self._holder
        self._hide()
        holder["text"] = text
        if ev:
            ev.set()

    def _submit(self):
        text = self.var.get().strip()
        if self.mode == "editing":
            self._finish(text)
        elif self.mode == "typing":
            if text:
                INBOX.put((text, "typed", True))
            self._hide()

    def _cancel(self):
        if self.mode == "editing":
            self._finish(None)
        else:
            self._hide()

    # ---- ручной ввод (меню в трее) ----
    def type_mode(self):
        self.post(self._ui_type)

    def _ui_type(self):
        if self.mode in ("editing", "asking"):
            return
        self.mode = "typing"
        self._show("\u2328\ufe0f Введите команду / Type a command", "", "normal",
                   "Enter — выполнить · Esc — закрыть")
        self.win.focus_force()
        self.entry.focus_force()


# ------------------------------------------------------------ трей, автозапуск, один экземпляр
def _pythonw() -> str:
    pw = Path(sys.executable).with_name("pythonw.exe")
    return str(pw if pw.exists() else sys.executable)


def start_tray(ui=None) -> None:
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        return
    ico = BASE / "jarvis.ico"
    if ico.exists():
        img = Image.open(ico)
    else:
        img = Image.new("RGB", (64, 64), "#0b1f3a")
        d = ImageDraw.Draw(img)
        d.ellipse((10, 10, 54, 54), outline="#00d0ff", width=5)
        d.ellipse((24, 24, 40, 40), fill="#00d0ff")

    def open_gui(icon, item):
        subprocess.Popen([_pythonw(), str(BASE / "jarvis_gui.py")], cwd=str(BASE))

    def reload_(icon, item):
        core.load_plugins(BASE / "plugins")
        log.info("Команд: %d", len(core.REGISTRY))

    def quit_(icon, item):
        STOP.set()
        icon.stop()

    items = [pystray.MenuItem("Открыть окно Джарвиса", open_gui, default=True)]
    if ui is not None:
        items.append(pystray.MenuItem("Ввести текст", lambda i, it: ui.type_mode()))
    items += [pystray.MenuItem("Перезагрузить команды", reload_),
              pystray.MenuItem("Открыть лог", lambda i, it: os.startfile(DATA / "jarvis.log")),
              pystray.MenuItem("Выход", quit_)]
    pystray.Icon("jarvis", img, "Джарвис", pystray.Menu(*items)).run_detached()


def autostart(enable: bool) -> None:
    import winreg
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                         r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
    if enable:
        winreg.SetValueEx(key, "Jarvis", 0, winreg.REG_SZ, f'"{_pythonw()}" "{BASE / "jarvis.py"}"')
        print("Автозапуск включён.")
    else:
        try:
            winreg.DeleteValue(key, "Jarvis")
        except FileNotFoundError:
            pass
        print("Автозапуск выключен.")


def single_instance() -> bool:
    ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\JarvisAssistantMutex")
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


# ------------------------------------------------------------ рабочий поток
def voice_loop(ui: "UI") -> None:
    """Слушает микрофон, показывает текст в окне сбоку и выполняет команды."""
    global _listener
    try:
        import comtypes
        comtypes.CoInitialize()
    except Exception:  # noqa: BLE001
        pass
    try:
        ui.reply("Загружаю модели распознавания…")
        emit(t="state", v="loading")
        _listener = Listener()
    except BaseException as e:  # noqa: BLE001
        log.exception("Не удалось запустить прослушивание")
        ui.reply(f"Ошибка запуска: {e}")
        emit(t="info", text=f"Ошибка запуска прослушивания: {e}")
        time.sleep(10)
        STOP.set()
        return
    listener = _listener
    core._io["confirm"] = ask_confirm

    def live(t: str) -> None:             # «живой» текст показываем, если он нас касается
        emit(t="live", text=t)
        if WAKE_MODE == "open" or find_wake(t) is not None:
            ui.partial(t)

    speak("Джарвис запущен.")
    emit(t="state", v="idle")
    while not STOP.is_set():
        try:
            try:                                          # команды из окна ввода и из чата
                text, src, tts = INBOX.get_nowait()
                handle(text, src, tts)
                emit(t="state", v="idle")
                continue
            except queue.Empty:
                pass
            heard = listener.phrase(timeout=1.0, on_partial=live)
            if not heard:
                emit(t="live", text="")
                ui.hide_listening()
                continue
            log.info("HEARD: %s", heard)
            if sys.stdout is not None:
                print("слышу:", heard)
            cmd = find_wake(heard)
            if cmd is None:
                if WAKE_MODE == "strict" or (WAKE_MODE == "hybrid" and not core.match_fast(heard)) or \
                        (WAKE_MODE == "open" and len(heard.split()) < 2 and not core.match_fast(heard)):
                    if WAKE_MODE == "strict":
                        emit(t="info", text=f"Слово активации не услышано, пропускаю: «{heard}»")
                    emit(t="live", text="")
                    ui.hide_listening()                   # шум или не нам
                    continue
                cmd = heard
            if not cmd:                                   # сказали только «Джарвис»
                speak("Да?")
                cmd = listener.phrase(timeout=8, on_partial=ui.partial)
                if not cmd:
                    ui.hide_listening()
                    continue
            emit(t="live", text="")
            text = ui.edit(cmd, AUTO_SEND_SECONDS)        # показали, дали поправить
            _reset.set()                                  # выкинуть звук, накопленный за время правки
            if text and text.strip():
                emit(t="state", v="busy")
                handle(text.strip(), "voice")
                emit(t="state", v="idle")
        except Exception:  # noqa: BLE001
            log.exception("Ошибка главного цикла")
            time.sleep(1)


def main() -> None:
    global _ui, TOKEN
    ap = argparse.ArgumentParser()
    ap.add_argument("--mic-test", action="store_true")
    ap.add_argument("--install-autostart", action="store_true")
    ap.add_argument("--remove-autostart", action="store_true")
    args = ap.parse_args()

    if args.install_autostart or args.remove_autostart:
        autostart(args.install_autostart)
        return
    if args.mic_test:
        mic_test()
        return
    if not single_instance():
        # Старый/зависший процесс мог оставить mutex, уже не слушая IPC.
        # Выходим только если на порту действительно отвечает работающий движок.
        try:
            probe = socket.create_connection(("127.0.0.1", IPC_PORT), timeout=1.0)
            probe.close()
            log.info("Движок уже работает и слушает IPC-порт %d", IPC_PORT)
            return
        except OSError:
            log.warning("Обнаружен занятый mutex, но IPC-порт %d не отвечает; запускаю восстановление", IPC_PORT)

    sys.path.insert(0, str(BASE))
    n = core.load_plugins(BASE / "plugins")
    log.info("Плагинов: %d, команд: %d", n, len(core.REGISTRY))
    core.REGISTRY["reload_plugins"] = core.Command(
        "reload_plugins", lambda: f"Команды перезагружены: {core.load_plugins(BASE / 'plugins')}",
        "Перезагрузить плагины-команды после изменения файлов в plugins/",
        {"type": "object", "properties": {}, "required": []},
        [re.compile(r"перезагрузи (команды|плагины)|reload (commands|plugins)", re.I)])
    core._io["say"] = speak

    TOKEN = _get_token()
    threading.Thread(target=serve_ipc, name="jarvis-ipc", daemon=True).start()
    if not IPC_READY.wait(5):
        raise RuntimeError("IPC-сервер не сообщил о запуске за 5 секунд")
    if IPC_START_ERROR:
        raise RuntimeError(f"Не удалось запустить IPC на порту {IPC_PORT}: {IPC_START_ERROR}")
    _ui = UI()
    start_tray(_ui)
    threading.Thread(target=voice_loop, args=(_ui,), daemon=True).start()
    _ui.run()


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        log.exception("Критическая ошибка запуска движка")
        raise
