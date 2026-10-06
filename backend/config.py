"""
Central configuration for Lawgorithm backend.

Everything that changes between dev / prod / "we finally got the dataset"
should live here, not scattered across modules.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent  # lawgorithm/

# --- LLM ---
# Which model backend generates text: "groq" (free API tier, see
# backend/llm/openai_compat.py), "ollama" (local, no API key -- see
# backend/llm/ollama.py) or "gemini" (Google API).
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama").strip().lower()
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_BASE_URL = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
# Groq's free limits are per model, so the work is split: the stronger
# model does the legal reasoning; the lighter one does summaries, the
# grounding check and translations.
GROQ_MODEL_AGENT = os.environ.get("GROQ_MODEL_AGENT", "openai/gpt-oss-120b")
GROQ_MODEL_LIGHT = os.environ.get("GROQ_MODEL_LIGHT", "qwen/qwen3.8-27b")
# Each Groq model has its OWN free daily token allowance (TPD). When a
# model's allowance runs out, the next model in its list takes over, so
# the site keeps working instead of failing until the window frees up.
GROQ_MODEL_AGENT_FALLBACKS = [m.strip() for m in os.environ.get(
    "GROQ_MODEL_AGENT_FALLBACKS", "openai/gpt-oss-20b,qwen/qwen3.8-27b").split(",") if m.strip()]
GROQ_MODEL_LIGHT_FALLBACKS = [m.strip() for m in os.environ.get(
    "GROQ_MODEL_LIGHT_FALLBACKS", "openai/gpt-oss-20b").split(",") if m.strip()]
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
OLLAMA_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "8192"))
OLLAMA_TIMEOUT_SECONDS = float(os.environ.get("OLLAMA_TIMEOUT_SECONDS", "300"))

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
MODEL = os.environ.get("LAWGORITHM_MODEL", "gemini-3.6-flash")
# Retries per LLM call after the first attempt. The SDK waits out the
# server's retry-after (~30s on a 429) before each one, so keep this low:
# 1 rides out a per-minute rate limit; 0 fails immediately.
LLM_MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "1"))

# --- ReAct agent ---
# Maximum statute searches (tool-call rounds) the agent may make per
# clause before it is forced to answer with the evidence it has.
AGENT_MAX_STEPS = int(os.environ.get("AGENT_MAX_STEPS", "3"))

# How a clause is researched:
#   "prefetch" (default) -- Lawgorithm searches the statute library itself
#       (clause-type hint query + the clause's own words) and hands the
#       sections to the model in ONE request. Measured on Groq: ~4x fewer
#       tokens per clause than "react", because a multi-turn loop resends
#       the whole growing conversation on every turn.
#   "react" -- the model decides what to search, up to AGENT_MAX_STEPS rounds.
AGENT_MODE = os.environ.get("AGENT_MODE", "prefetch").strip().lower()
PREFETCH_MAX_SOURCES = int(os.environ.get("PREFETCH_MAX_SOURCES", "4"))
PREFETCH_EXCERPT_CHARS = int(os.environ.get("PREFETCH_EXCERPT_CHARS", "1100"))

# --- Confidence gating (Phase 10) ---
# Legacy: the original flat threshold. Superseded by the multi-factor
# confidence engine's own thresholds (GROUNDED_THRESHOLD /
# PARTIALLY_GROUNDED_THRESHOLD in backend/confidence/engine.py), which
# is what should_send_for_verification() actually uses now. Kept here
# so existing .env files don't break; not read by the current pipeline.
CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.85"))

# --- Privacy (Digital Personal Data Protection Act, 2023) ---
# Default: contracts are processed in memory only and NEVER written to
# the database or disk; results are wiped after RESULT_TTL_MINUTES (or
# on "Delete now"). The reviewer desk and the corrections dataset need
# stored analyses, so they only exist when STORE_ANALYSES=true -- use that
# only with users' explicit consent (e.g. internal research).
STORE_ANALYSES = os.environ.get("STORE_ANALYSES", "false").strip().lower() == "true"
RESULT_TTL_MINUTES = int(os.environ.get("RESULT_TTL_MINUTES", "60"))
# Grievance contact shown in the privacy notice (DPDP Act s.8(10) / s.13).
PRIVACY_CONTACT = os.environ.get("PRIVACY_CONTACT", "")
# Official text of the DPDP Act, 2023 (MeitY), linked from the privacy notice.
DPDP_ACT_URL = os.environ.get(
    "DPDP_ACT_URL", "https://www.meity.gov.in/static/uploads/2024/06/2bf1f0e9f04e6fb4f8fef35e82c42aa5.pdf")

# --- Expert review (human in the loop) ---
# Clauses Lawgorithm can't confirm are sent -- only if the person asks and
# consents -- to partner reviewers (lawyers / law students). Store:
#   "local" -- JSON files in EXPERT_REVIEW_DIR (development)
#   "hf"    -- a PRIVATE Hugging Face dataset (REVIEW_DATASET), written with
#              HF_REVIEW_TOKEN: a fine-grained token with write access to
#              that one dataset (a Space secret, never in code)
#   ""      -- off: "expert check" clauses point to free legal aid instead
EXPERT_REVIEW_STORE = os.environ.get("EXPERT_REVIEW_STORE", "local").strip().lower()
EXPERT_REVIEW_DIR = os.environ.get("EXPERT_REVIEW_DIR", str(BASE_DIR / "data" / "expert_reviews"))
REVIEW_DATASET = os.environ.get("REVIEW_DATASET", "")
HF_REVIEW_TOKEN = os.environ.get("HF_REVIEW_TOKEN", "")
# "Adv. Asha Rao=key1;Priya (law student)=key2" -- one personal key per
# reviewer, created with `python -m scripts.add_reviewer "Name"`.
REVIEWER_KEYS = os.environ.get("REVIEWER_KEYS", "")
# DPDP storage limitation: deleted this many days after the review, and
# never kept longer than EXPERT_REVIEW_MAX_DAYS even if nobody reviews it.
EXPERT_REVIEW_KEEP_DAYS = int(os.environ.get("EXPERT_REVIEW_KEEP_DAYS", "7"))
EXPERT_REVIEW_MAX_DAYS = int(os.environ.get("EXPERT_REVIEW_MAX_DAYS", "30"))
# Who reviews, as the person is told: "team" (the Lawgorithm team, while
# there are no legal partners yet) or "legal" (lawyers / law students).
REVIEWER_KIND = os.environ.get("REVIEWER_KIND", "team").strip().lower()
FREE_LEGAL_AID = "15100"   # NALSA national legal aid helpline, toll-free, 24x7

# --- Payments (Razorpay) ---
# Off (everything free) until both keys are set. Test keys (rzp_test_...)
# work before KYC; switch to live keys after Razorpay activates the account.
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "").strip()
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "").strip()
PRICE_ANALYSIS_PAISE = int(os.environ.get("PRICE_ANALYSIS_PAISE", "1000"))        # Rs 10 per contract
# Human expert check: free while the reviewers are the Lawgorithm team.
# Only enrolled advocates may practise law in India (Advocates Act, 1961,
# s.33), so charge for it (e.g. 500 = Rs 5) once a lawyer reviews.
EXPERT_REVIEW_PRICE_PAISE = int(os.environ.get("EXPERT_REVIEW_PRICE_PAISE", "0"))
# Public business contact for the Contact / Terms pages (Razorpay needs one).
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "").strip()
BUSINESS_NAME = os.environ.get("BUSINESS_NAME", "Lawgorithm").strip()

# --- Database ---
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'lawgorithm.db'}")

# --- Vector store / RAG ---
CHROMA_PERSIST_DIR = os.environ.get("CHROMA_PERSIST_DIR", str(BASE_DIR / "chroma_db"))
CHROMA_COLLECTION_NAME = "indian_legal_corpus"
# Separate collection for example contract clauses (clause-type
# identification only). Never searched by the citation tool -- see
# backend/rag/clause_index.py for why the two must stay apart.
CLAUSE_COLLECTION_NAME = "clause_precedents"
# Below this kNN vote share the clause type is reported as unknown
# rather than guessed.
CLAUSE_TYPE_MIN_CONFIDENCE = float(os.environ.get("CLAUSE_TYPE_MIN_CONFIDENCE", "0.45"))
# Fine-tuned clause-type classifier (scripts/train_clause_classifier.py).
# When the directory exists it replaces the kNN vote for the type
# prediction; set CLAUSE_CLASSIFIER_DIR="" to force the kNN vote.
CLAUSE_CLASSIFIER_DIR = os.environ.get(
    "CLAUSE_CLASSIFIER_DIR", str(BASE_DIR / "models" / "clause_classifier" / "minilm-l6")
)
EMBEDDING_MODEL_NAME = os.environ.get("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")

# --- Data locations ---
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
STATUTES_DIR = DATA_DIR / "statutes"
EVALUATION_DIR = DATA_DIR / "evaluation"
CLAUSE_CORPUS_DIR = PROCESSED_DIR / "clause_corpus"

# --- Supported document scope for the MVP (Phase 1) ---
SUPPORTED_DOCUMENT_TYPES = ["employment", "rental"]

# --- Risk tiers (Phase 9) ---
RISK_LEVELS = ["red", "amber", "green"]

# Minimum characters of extracted text per page before we treat a PDF's
# native text layer as "insufficient" and fall back to OCR.
MIN_TEXT_CHARS_PER_PAGE = 40

SUPPORTED_LANGUAGES = ["hindi", "tamil", "bengali", "marathi", "telugu", "kannada"]

# Translation engine: "indictrans2" (AI4Bharat, MIT; tries NLLB next if a
# translation fails a check), "nllb" (Meta, non-commercial licence), or
# "llm" (the chat model from LLM_PROVIDER). Unavailable engines are skipped.
TRANSLATION_ENGINE = os.environ.get("TRANSLATION_ENGINE", "indictrans2").strip().lower()
NLLB_MODEL_NAME = os.environ.get("NLLB_MODEL_NAME", "facebook/nllb-200-distilled-600M")
# AI4Bharat IndicTrans2 (MIT): used for English -> Indian languages when
# TRANSLATION_ENGINE=indictrans2. Gated download: accept the terms on its
# Hugging Face page and run `hf auth login` once on the machine.
INDICTRANS2_MODEL_NAME = os.environ.get("INDICTRANS2_MODEL_NAME", "ai4bharat/indictrans2-en-indic-dist-200M")
# IndicTrans2 needs transformers 4.x, so it runs in its own virtualenv
# (see backend/translation/indictrans_worker.py for the setup commands).
INDICTRANS2_PYTHON = os.environ.get("INDICTRANS2_PYTHON", str(BASE_DIR / ".venvs" / "indictrans" / "bin" / "python"))
