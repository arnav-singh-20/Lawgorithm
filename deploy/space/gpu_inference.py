"""
ZeroGPU inference for the clause-type classifier.

Free Hugging Face Spaces run on ZeroGPU, which gives a GPU to functions
decorated with @spaces.GPU (and requires at least one). The fine-tuned
clause classifier runs on every clause, so it's the natural GPU workload.
Per ZeroGPU's rules the model is placed on "cuda" at import time (a CUDA
emulation handles that outside decorated calls); the real GPU is attached
only while classify_on_gpu runs.

If the GPU can't be used (daily GPU quota spent, queue timeout), the
backend falls back to its CPU copy of the same model -- see
backend/rag/clause_classifier.py (GPU_PREDICT hook).
"""

import json
import os

import spaces
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

MODEL_DIR = os.environ["CLAUSE_CLASSIFIER_DIR"]

tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR)
model = AutoModelForSequenceClassification.from_pretrained(MODEL_DIR).to("cuda").eval()
labels = json.loads(open(os.path.join(MODEL_DIR, "labels.json")).read())


@spaces.GPU(duration=15)
def classify_on_gpu(text: str) -> list[float]:
    with torch.no_grad():
        enc = tokenizer([text], truncation=True, max_length=128, return_tensors="pt").to("cuda")
        return torch.softmax(model(**enc).logits.float(), dim=-1)[0].cpu().tolist()
