"""
Fine-tuned clause-type classifier (scripts/train_clause_classifier.py).

Used by rag/clause_index.classify_clause_type in place of the kNN vote
when CLAUSE_CLASSIFIER_DIR points at a trained model. Same output
contract either way: a predicted type plus a 0-1 confidence (here the
softmax probability), with the same abstention threshold.
"""

import json
import logging
from pathlib import Path

from backend.config import CLAUSE_CLASSIFIER_DIR

logger = logging.getLogger(__name__)

MAX_LEN = 128

# Optional accelerated path, set by the deployment (deploy/space/app.py on
# ZeroGPU): a callable text -> list of probabilities in labels.json order.
# Any failure falls back to the local model.
GPU_PREDICT = None


class ClauseClassifier:
    _instance = None
    _unavailable = False

    def __init__(self, model_dir: Path):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self._torch = torch
        self._device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
        self._tokenizer = AutoTokenizer.from_pretrained(model_dir)
        self._model = AutoModelForSequenceClassification.from_pretrained(model_dir).to(self._device).eval()
        self.labels = json.loads((model_dir / "labels.json").read_text())

    @classmethod
    def get(cls) -> "ClauseClassifier | None":
        """None when no trained model is configured/present (callers fall back to kNN)."""
        if cls._instance is None and not cls._unavailable:
            model_dir = Path(CLAUSE_CLASSIFIER_DIR) if CLAUSE_CLASSIFIER_DIR else None
            if not model_dir or not (model_dir / "labels.json").exists():
                cls._unavailable = True
                return None
            try:
                cls._instance = cls(model_dir)
            except Exception:
                logger.exception("Could not load clause classifier from %s; using kNN vote.", model_dir)
                cls._unavailable = True
        return cls._instance

    def predict(self, text: str) -> list[tuple[str, float]]:
        """All types with probabilities, most likely first."""
        if GPU_PREDICT is not None:
            try:
                probs = GPU_PREDICT(text)
                return sorted(zip(self.labels, probs), key=lambda x: -x[1])
            except Exception:
                logger.warning("GPU classification unavailable; using CPU.", exc_info=True)
        with self._torch.no_grad():
            enc = self._tokenizer([text], truncation=True, max_length=MAX_LEN, return_tensors="pt").to(self._device)
            probs = self._torch.softmax(self._model(**enc).logits.float(), dim=-1)[0].cpu().tolist()
        return sorted(zip(self.labels, probs), key=lambda x: -x[1])
