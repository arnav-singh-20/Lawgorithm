"""
Local translation engine: Meta's NLLB-200 (distilled, 600M parameters).

Why a dedicated translation model instead of the chat LLM: measured
live, qwen2.5:3b produced garbled Hindi and turned "Rs 2,50,000" into
"25,00,000" -- a translation that changes a number in a contract is
worse than no translation. NLLB is trained for exactly this task, covers
every language Lawgorithm supports in both directions (so it also does
the back-translation meaning check), and runs locally.

LICENCE: NLLB-200 weights are CC-BY-NC-4.0 (non-commercial). Fine for a
research/student prototype; swap in an MIT/Apache model (e.g. AI4Bharat
IndicTrans2, which needs a Hugging Face login to download) before any
commercial use -- see TRANSLATION_ENGINE in config.py.

NLLB is a sentence-level model: long paragraphs are split into
sentences, translated as a batch, and re-joined.
"""

import logging
import re
import threading

from backend.config import NLLB_MODEL_NAME

logger = logging.getLogger(__name__)

NLLB_CODES = {
    "english": "eng_Latn",
    "hindi": "hin_Deva",
    "marathi": "mar_Deva",
    "tamil": "tam_Taml",
    "bengali": "ben_Beng",
    "telugu": "tel_Telu",
    "kannada": "kan_Knda",
}

# Sentence ends, including the Devanagari danda.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?।])\s+")


class NLLBTranslator:
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        self._torch = torch
        self._device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
        self._tokenizer = AutoTokenizer.from_pretrained(NLLB_MODEL_NAME)
        self._model = AutoModelForSeq2SeqLM.from_pretrained(NLLB_MODEL_NAME).to(self._device).eval()

    @classmethod
    def get(cls) -> "NLLBTranslator":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def translate(self, text: str, source_language: str, target_language: str) -> str:
        sentences = [s for s in _SENTENCE_SPLIT.split(text.strip()) if s]
        if not sentences:
            return ""
        self._tokenizer.src_lang = NLLB_CODES[source_language]
        target_id = self._tokenizer.convert_tokens_to_ids(NLLB_CODES[target_language])
        with self._lock, self._torch.no_grad():  # one generation at a time on this device
            batch = self._tokenizer(sentences, return_tensors="pt", padding=True, truncation=True, max_length=256)
            batch = batch.to(self._device)
            out = self._model.generate(
                **batch,
                forced_bos_token_id=target_id,
                max_new_tokens=int(batch["input_ids"].shape[1] * 2.2) + 10,
                num_beams=4,
            )
        return " ".join(self._tokenizer.batch_decode(out, skip_special_tokens=True)).strip()
