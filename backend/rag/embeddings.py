"""
Embedding wrapper (Phase 6).

Uses sentence-transformers by default. If the model can't be
downloaded/loaded (no internet in this environment, model not cached
yet, etc.) we fall back to a deterministic hashing-based embedding so
the rest of the pipeline (vector_store, retrieval, agent) can still be
exercised end-to-end without a real network call. Swap in the real
model in any environment with internet access — nothing else needs to
change.
"""

import hashlib
import math
import socket
from typing import List

from backend.config import EMBEDDING_MODEL_NAME

_FALLBACK_DIM = 384  # matches all-MiniLM-L6-v2 output dim


def _cosine(vec_a, vec_b) -> float:
    dot = sum(float(a) * float(b) for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(float(a) ** 2 for a in vec_a)) or 1.0
    norm_b = math.sqrt(sum(float(b) ** 2 for b in vec_b)) or 1.0
    return dot / (norm_a * norm_b)


def _huggingface_reachable(timeout: float = 2.0) -> bool:
    """
    Fast TCP-level connectivity probe, deliberately not a full HTTP
    request -- just "can we even open a socket to huggingface.co within
    a couple seconds". Cheap enough to run on every fresh process
    startup, and avoids the ~78-second hang measured when
    sentence-transformers/huggingface_hub is left to retry a real
    download with its own backoff logic in a fully offline environment.
    """
    try:
        socket.create_connection(("huggingface.co", 443), timeout=timeout).close()
        return True
    except OSError:
        return False


class EmbeddingModel:
    """
    Always on the CPU (device="cpu"). On a Hugging Face ZeroGPU Space,
    torch reports a GPU everywhere, so sentence-transformers would put
    the model on "cuda" -- but outside a @spaces.GPU call that's an
    emulation that returns ALL-ZERO vectors. Seen live: every translation
    meaning check scored 0.00 and the vector half of statute retrieval
    searched with an empty query. MiniLM is tiny; the CPU is plenty.
    The pretrained sanity check runs on every load so a model that
    returns nonsense can never be used silently.
    """

    _instance = None

    def __init__(self):
        self._model = None
        self._use_fallback = False
        self._load()

    def _load(self):
        try:
            from sentence_transformers import SentenceTransformer

            # local_files_only=True is deliberate: if the model isn't
            # already cached, this raises immediately instead of
            # sentence-transformers silently falling back to a fresh,
            # randomly-initialized (untrained, non-deterministic across
            # runs) transformer with the right shape but no semantic
            # meaning whatsoever -- which is worse than our own
            # deterministic hash fallback below, and fails silently.
            self._model = SentenceTransformer(EMBEDDING_MODEL_NAME, local_files_only=True, device="cpu")
            if self._looks_pretrained():
                return
            self._model = None
        except Exception:
            pass

        if not _huggingface_reachable():
            # No cached model AND no route to Hugging Face at all --
            # don't even try the full download. Confirmed by measurement
            # that skipping this check costs ~78 seconds here: without
            # it, sentence-transformers/huggingface_hub silently retries
            # with backoff for a long time before finally raising, and
            # that full delay hits on the very first embedding call of
            # every fresh process. A 2-second TCP probe avoids that.
            self._use_fallback = True
            return

        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(EMBEDDING_MODEL_NAME, device="cpu")
            if not self._looks_pretrained():
                raise RuntimeError("Loaded model has no pretrained weights")
        except Exception:
            self._use_fallback = True

    def _looks_pretrained(self) -> bool:
        """
        Sanity check: a genuinely pretrained sentence embedding model
        should put near-identical sentences much closer together than
        unrelated ones. A randomly-initialized model (what you get when
        sentence-transformers can't fetch weights but doesn't raise)
        fails this by a wide margin. Cheap enough to run once at startup.
        """
        try:
            a, b, c = self._model.encode(
                ["the cat sat on the mat", "a cat was sitting on the mat", "quantum physics and tax law"],
                convert_to_numpy=True,
            )
            sim_related = _cosine(a, b)
            sim_unrelated = _cosine(a, c)
            return sim_related > sim_unrelated + 0.1
        except Exception:
            return False

    @classmethod
    def get(cls) -> "EmbeddingModel":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def embed(self, texts: List[str]) -> List[List[float]]:
        if self._use_fallback:
            return [_hash_embedding(t) for t in texts]
        # normalize_embeddings: the published all-MiniLM-L6-v2 ends in a
        # Normalize layer, but a cache missing modules.json loads without
        # it (vectors of length ~6 instead of 1), which silently deflated
        # every L2-distance retrieval score. Normalising here makes that
        # independent of how complete the local model cache is.
        encoded = self._model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        return [[float(x) for x in vec] for vec in encoded]


def _hash_embedding(text: str, dim: int = _FALLBACK_DIM) -> List[float]:
    """
    Deterministic, dependency-free pseudo-embedding for offline dev/testing.
    NOT semantically meaningful -- only for exercising the pipeline
    (segmentation -> retrieval -> agent) before real embeddings are wired up.

    IMPORTANT: byte values are centered to roughly [-1, 1], not left in
    [0, 1]. Summing all-positive per-word components (the original
    implementation) puts every text's vector in the same orthant of the
    space, which systematically inflates cosine similarity between
    UNRELATED texts -- confirmed empirically at ~0.97 for two completely
    unrelated sentences before this fix, which is high enough to make
    the Phase 14 translation-validation similarity check (threshold
    0.75) never actually fail, silently defeating the safety net it
    exists to provide. Centering removes that bias; unrelated texts now
    genuinely land near-orthogonal instead of falsely "very similar".
    """
    vector = [0.0] * dim
    words = text.lower().split()

    if not words:
        return vector

    for word in words:
        digest = hashlib.sha256(word.encode("utf-8")).digest()
        for i in range(dim):
            vector[i] += (digest[i % len(digest)] - 127.5) / 127.5

    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]
