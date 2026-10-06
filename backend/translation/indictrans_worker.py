"""
IndicTrans2 translation worker -- runs in its OWN virtualenv.

IndicTrans2's model/tokenizer code (downloaded from Hugging Face) only
works with transformers 4.x, while the rest of Lawgorithm uses
transformers 5. So this file runs under .venvs/indictrans (transformers
4.51) as a long-lived child process of the backend, speaking JSON lines:

    stdin : {"id": 1, "text": "...", "target": "hin_Deva"}
    stdout: {"id": 1, "translation": "..."}      or {"id": 1, "error": "..."}

It imports nothing from the backend (different environment). Started and
managed by backend/translation/indictrans.py; set up once with

    python3 -m venv .venvs/indictrans
    .venvs/indictrans/bin/pip install "torch>=2.6" "transformers==4.51.3" sentencepiece sacremoses IndicTransToolkit
"""

import json
import os
import re
import sys

import torch
from IndicTransToolkit.processor import IndicProcessor
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

MODEL = os.environ.get("INDICTRANS2_MODEL_NAME", "ai4bharat/indictrans2-en-indic-dist-200M")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def main() -> None:
    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    tokenizer = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)
    model = AutoModelForSeq2SeqLM.from_pretrained(MODEL, trust_remote_code=True).to(device).eval()
    processor = IndicProcessor(inference=True)
    print(json.dumps({"ready": True, "device": str(device)}), flush=True)

    for line in sys.stdin:
        if not line.strip():
            continue
        request = json.loads(line)
        try:
            sentences = [s for s in SENTENCE_SPLIT.split(request["text"].strip()) if s]
            batch = processor.preprocess_batch(sentences, src_lang="eng_Latn", tgt_lang=request["target"])
            inputs = tokenizer(batch, truncation=True, padding="longest", return_tensors="pt",
                               return_attention_mask=True).to(device)
            with torch.no_grad():
                out = model.generate(**inputs, use_cache=True, min_length=0, max_length=256,
                                     num_beams=5, num_return_sequences=1)
            decoded = tokenizer.batch_decode(out, skip_special_tokens=True, clean_up_tokenization_spaces=True)
            translation = " ".join(processor.postprocess_batch(decoded, lang=request["target"])).strip()
            reply = {"id": request.get("id"), "translation": translation}
        except Exception as exc:  # report, keep serving
            reply = {"id": request.get("id"), "error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(reply, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
