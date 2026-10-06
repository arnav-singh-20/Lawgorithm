"""
Translation engine: AI4Bharat IndicTrans2 (English -> Indian languages,
distilled 200M), via a worker process.

Purpose-built for Indian languages, MIT-licensed (usable commercially,
unlike NLLB), and its IndicProcessor swaps numbers for placeholders
before translation and restores them after. Measured live it kept
"landlord" correct in Hindi and Tamil where NLLB wrote "tenant".

IndicTrans2's downloaded model code only works with transformers 4.x and
the backend runs transformers 5, so the model lives in its own
virtualenv (.venvs/indictrans) and runs as a long-lived child process
(indictrans_worker.py) that this module starts on first use and talks to
over stdin/stdout JSON lines. If the venv or the gated model isn't
available, translator.py falls back to NLLB.

Gated download: the Hugging Face account logged in on this machine
(`hf auth login`) must have accepted the terms on
https://huggingface.co/ai4bharat/indictrans2-en-indic-dist-200M
"""

import json
import logging
import os
import subprocess
import threading
from pathlib import Path

from backend.config import INDICTRANS2_MODEL_NAME, INDICTRANS2_PYTHON

logger = logging.getLogger(__name__)

IT2_CODES = {
    "hindi": "hin_Deva",
    "marathi": "mar_Deva",
    "tamil": "tam_Taml",
    "bengali": "ben_Beng",
    "telugu": "tel_Telu",
    "kannada": "kan_Knda",
}

WORKER = Path(__file__).with_name("indictrans_worker.py")
STARTUP_TIMEOUT_S = 180


class IndicTrans2Unavailable(RuntimeError):
    pass


class IndicTrans2Translator:
    _instance = None
    _class_lock = threading.Lock()

    def __init__(self):
        python = Path(INDICTRANS2_PYTHON)
        if not python.exists():
            raise IndicTrans2Unavailable(f"IndicTrans2 environment not found at {python}")
        self._lock = threading.Lock()
        self._next_id = 0
        self._proc = None
        self._start(python)

    def _start(self, python: Path) -> None:
        env = {**os.environ, "INDICTRANS2_MODEL_NAME": INDICTRANS2_MODEL_NAME, "TOKENIZERS_PARALLELISM": "false"}
        self._proc = subprocess.Popen(
            [str(python), "-I", str(WORKER)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", bufsize=1, env=env,
        )
        ready = self._read_line(timeout=STARTUP_TIMEOUT_S)
        if not ready or not ready.get("ready"):
            self.close()
            raise IndicTrans2Unavailable("IndicTrans2 worker failed to start (is the gated model downloaded?)")
        logger.info("IndicTrans2 worker ready on %s", ready.get("device"))

    def _read_line(self, timeout: float) -> dict | None:
        result: list = []
        reader = threading.Thread(target=lambda: result.append(self._proc.stdout.readline()), daemon=True)
        reader.start()
        reader.join(timeout)
        if not result or not result[0]:
            return None
        return json.loads(result[0])

    @classmethod
    def get(cls) -> "IndicTrans2Translator":
        with cls._class_lock:
            if cls._instance is None or cls._instance._proc.poll() is not None:
                cls._instance = cls()   # first use, or restart after a crash
            return cls._instance

    def translate(self, text: str, target_language: str) -> str:
        """English -> target_language."""
        with self._lock:
            self._next_id += 1
            request = {"id": self._next_id, "text": text, "target": IT2_CODES[target_language]}
            try:
                self._proc.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise IndicTrans2Unavailable("IndicTrans2 worker is not running") from exc
            reply = self._read_line(timeout=120)
        if reply is None:
            raise IndicTrans2Unavailable("IndicTrans2 worker did not answer")
        if "error" in reply:
            raise IndicTrans2Unavailable(reply["error"])
        return reply["translation"]

    def close(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
