# Lawgorithm

MVP scope (Phase 1, as recommended): **employment contracts and rental
agreements only.** Upload one, get every clause explained in plain
language, grounded in real Indian statutory provisions, and tagged
Red/Amber/Green.

## Newest: decisions, human-in-the-loop review, payments

**A clear decision for every clause** (`backend/risk/decision.py`): ✅ no lawyer
needed · 🤝 ask for a change · ⚖️ talk to a lawyer · 🧑‍⚖️ needs a human expert
check (when the AI can't confirm its own answer). Serious clauses read: *"This
clause is important. If you don't fix it, [consequence]. For more detail, talk
to a lawyer."* -- the consequence is written by the AI per clause.

**Expert review queue** (`backend/expert_review/`, reviewer page at `/#/review`):
the person sends only the uncertain clauses, with consent; a reviewer decides and
the person sees it on a private link. Kept in a private Hugging Face dataset,
deleted 7 days after review (30 days max). The owner adds reviewers from the
page itself (invite link; only a hash of each key is stored).

**Payments** (`backend/payments/razorpay.py`): Rs 10 per contract via Razorpay;
samples free; verified server-side against Razorpay and marked used on the
payment itself; automatic refund if a check fails. Off until
`RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET` are set (test keys work before KYC).
Pricing, Terms, Refund and Contact pages are at `/#/pricing`, `/#/terms`,
`/#/refunds`, `/#/contact` (the contact form doubles as the DPDP grievance channel).

**Cheaper, sturdier AI use**: one request per clause with the law looked up first
(`AGENT_MODE=prefetch`, ~4x fewer tokens), automatic fallback between Groq models
when one's daily allowance runs out, embeddings pinned to CPU (ZeroGPU returned
zero vectors), and 29 law sections recovered (Contract Act ss.13-18, 31, 124...)
plus the Kerala rent Act.

Settings: see `.env.example`. Accuracy run: `python -m scripts.run_accuracy_eval`
(uses about a day of the free AI allowance). A plain-language walkthrough of every
file is in `Lawgorithm_Code_Guide.pdf`.

## Latest round: dataset, local models, remaining phases

### Running it (no API key needed)

```bash
pip install -r requirements.txt
brew install tesseract poppler ollama        # OCR for photos/scans + local LLM server
ollama serve &                               # or open the Ollama app
ollama pull qwen2.5:3b                       # ~1.9 GB, the default local model

# one-off data builds (only needed when the dataset changes)
python -m scripts.build_clause_corpus lawgorithm_train.jsonl   # ~1 min
python -m backend.rag.clause_index                             # embeds 62,903 clauses, ~30-60 min on an 8 GB M2
python -m scripts.train_clause_classifier --model sentence-transformers/all-MiniLM-L6-v2 \
    --epochs 3 --lr 1e-4 --batch-size 32 --name minilm-l6      # ~45-75 min on an 8 GB M2

uvicorn backend.main:app --port 8000         # then open http://localhost:8000
```

`LLM_PROVIDER=gemini` (plus `GEMINI_API_KEY`) switches every LLM call
(agent, summary, verifier, translation) back to Gemini. `AGENT_MAX_STEPS`
sets the ReAct search limit (default 3).

### Going live (free Hugging Face Space + Groq)

- **AI:** `LLM_PROVIDER=groq` uses Groq's free tier (no card, no training
  on API data). `openai/gpt-oss-120b` does the legal reasoning and
  `qwen/qwen3.8-27b` does summaries, checks and translations; Groq's free
  limits apply per model, so this doubles the daily budget (about 200k
  tokens per model per day, roughly 5-8 contracts). Short per-minute limits
  are waited out; a used-up daily quota gives a clear message.
- **Hosting:** free personal Hugging Face accounts can run Gradio Spaces on
  ZeroGPU (Docker Spaces need PRO), so `deploy/space/app.py` serves the
  FastAPI app from a Gradio Space. `python -m scripts.deploy_space` builds a
  125 MB bundle (code, website, law library, statute index, classifier) and
  publishes it. The Groq key goes up as a private Space **secret** read from
  `.env`. Needs `hf auth login` with a **write** token.

### Privacy (DPDP Act, 2023) -- default

- Contracts are processed **in memory only**: no database rows, the upload
  is deleted once read, and results expire after `RESULT_TTL_MINUTES`
  (default 60) or on **Delete now** (`DELETE /document/{id}`).
- **Consent required** (checkbox; the API rejects uploads without it).
- **Data minimisation:** phone numbers, emails, PAN, Aadhaar, IFSC, GSTIN,
  passport and account numbers are removed (`backend/privacy/redaction.py`)
  before any AI call. Names and addresses can't be removed reliably, and the
  notice says so.
- Contract text is kept out of logs. The privacy notice (`#/privacy`) is
  available in all 7 languages and names the processor (Groq, USA).
- Set `PRIVACY_CONTACT` (grievance contact) in `.env`.
- The reviewer desk and corrections dataset need stored analyses, so they
  only exist with `STORE_ANALYSES=true`. Use that only with explicit consent.

### Law library (`data/statutes/`, built by `scripts/build_statute_library.py`)

2,273 sections from 26 Acts plus the Model Tenancy Act. Each section links to
its official India Code PDF (`official_source`).

- **Central:** Contract Act, Transfer of Property Act, Registration, Stamp,
  Specific Relief, Limitation, Arbitration, Delhi Rent Control, IT Act,
  Negotiable Instruments, Consumer Protection, Copyright, POSH, Apprentices,
  RPwD, and the **four Labour Codes** (in force since 21 Nov 2025; the 29
  labour Acts they replaced are deliberately left out).
- **States:** Karnataka, Tamil Nadu, West Bengal and Maharashtra rent laws,
  Uttar Pradesh tenancy (partial, poor scan), and the Andhra Pradesh Shops &
  Establishments Act.
- **Sources:** the `geekyrakshit/indian-legal-acts` dataset (India Code text)
  and PRS Legislative Research PDFs. India Code itself blocks automated
  access (403), so it was not scraped.
- **`verified`** means "taken from an official digital text layer". The 74
  sections OCR'd from scans (Maharashtra, UP) are `verified=false`, so citing
  them flags the answer for checking. Commencement dates (`effective_date`)
  are still missing everywhere. No lawyer has reviewed the library.
- **Retrieval is hybrid:** BM25 keyword search plus embeddings, merged by
  reciprocal rank fusion (`backend/rag/keyword_index.py`). Pure embedding
  search missed Contract Act s.27 for "non-compete" and s.74 for "penalty";
  hybrid search ranks them at the top.

### Frontend (`frontend/`, served at `/`)

Plain HTML/CSS/JS, no build step. Design language: warm cream paper, ink,
editorial serif (Fraunces) + Space Grotesk + JetBrains Mono labels, with the
red/amber/green risk system as the main colour story. Light and dark themes.

- **Language first:** on the first visit a picker asks for one of 7 languages
  (English, Hindi, Marathi, Tamil, Bengali, Telugu, Kannada). The whole
  interface switches instantly (`frontend/i18n.js`, 130 strings each, with
  Noto fonts loaded on demand). The AI's explanations are translated by the
  backend with a meaning check and a number check. `?lang=hi` and
  `?theme=dark` in a URL preselect.
  *The interface strings were written for plain language and still need a
  native-speaker review before launch.*
- **Upload:** drag and drop, file browse, **Take a photo** (opens the phone
  camera), or one of two built-in samples.
- **Live progress:** uses the job API (`POST /analyze-document/start`, then
  polling `GET /jobs/{id}`). Finished clauses appear as they complete, and
  progress survives a page refresh (`#/job/<id>`).
- **Results** (`#/document/<id>`): verdict, simple-English summary with key
  terms, risk filters, clause cards (explanation, *what you should do*,
  confidence, review status, and an expandable *why & the law* with the
  original clause and cited statutes), plus a **Document** view of the
  contract highlighted by risk.
- **Reviewer desk** (`#/review`): approve, fix (a proper form that requires
  a reason), find more evidence, or reject. Each decision is saved to the
  corrections dataset.

All model output is inserted as text, never as HTML.

### Translation engine

Translations try **AI4Bharat IndicTrans2** first (MIT licence, built for
Indian languages). If a translation fails a check, **NLLB-200** gets a go,
and the first one that passes is used. Measured on 36 contract sentences
(6 languages x rent/job clauses with amounts and parties):

| Setup | Passed every check |
|---|---|
| qwen2.5:3b (chat model) | garbled; changed Rs 2,50,000 into 25,00,000 |
| NLLB alone | 7/18 rental sentences (landlord/tenant swapped) |
| NLLB + legal glossary + Indian number words | 28/36 |
| **IndicTrans2, NLLB as fallback (default)** | **35/36** (32 IndicTrans2, 3 rescued by NLLB) |

Each translation must pass: back-translation meaning similarity >= 0.75,
**every multi-digit amount unchanged** (Indian forms such as "७५ हजार" and
"৫ লাখ" are understood), and **the same parties named** (landlord/tenant,
employer/employee). Otherwise the English is shown with a warning in the
user's language.

IndicTrans2's model code needs transformers 4.x, so it runs in its own
virtualenv as a worker process (`backend/translation/indictrans_worker.py`).
One-time setup:

```bash
# 1. accept the terms at https://huggingface.co/ai4bharat/indictrans2-en-indic-dist-200M
hf auth login                      # paste a read token
python3 -m venv .venvs/indictrans
.venvs/indictrans/bin/pip install "torch>=2.6" "transformers==4.51.3" sentencepiece sacremoses IndicTransToolkit
```

If that environment or the model is missing, translation falls back to NLLB
automatically. NLLB weights are CC-BY-NC (non-commercial), so for a commercial
launch keep IndicTrans2 and replace the NLLB fallback.
`TRANSLATION_ENGINE=indictrans2|nllb|llm` selects the engine.

### Request flow

```
upload PDF / photo / DOCX / TXT
  -> extract (text layer, or OCR for photos and scans) -> clean -> split into clauses
  -> summarize_document(): one simple-English summary of the whole contract
  -> per clause:
       clause type  (fine-tuned MiniLM classifier; identification only, never citable)
       ReAct agent  (searches the Indian statute index up to AGENT_MAX_STEPS times,
                     sees the document summary as context)
       citation check -> grounding check -> confidence engine -> routing flags
  -> red / amber / green + simple explanation + "what you should do" + cited sources
```

### The dataset (`lawgorithm_train.jsonl`)

1,850,286 rows, of which 1,014,294 are unique clauses (the rest are
duplicates). Each clause is labelled with its original section heading
(179,221 distinct headings). The clauses are overwhelmingly **US SEC
contract filings, not Indian law**, so the dataset is used to identify
*what kind of clause* something is. It is never a legal source the
agent can cite. Headings are mapped onto 50 clause types
(`backend/rag/clause_taxonomy.py`) and balanced to 62,903 training plus
7,837 held-out clauses (`scripts/build_clause_corpus.py`). The two
non-clause rows include a set of 18 Indian legal templates, exported to
`data/raw/indian_templates/`.

The `.arrow` shard in `Lawgorithm 3/` is a tokenized copy of the same
data in which every label became `None`. Whatever tokenized it read an
`output` field, but the labels are stored under `label`. Don't train on that shard.

### Clause-type accuracy (held-out, 7,837 clauses)

| Method | Top-1 | Macro-F1 | Hint coverage | Accuracy when hinted |
|---|---|---|---|---|
| kNN vote over MiniLM embeddings | 79.6% | 0.779 | 87.1% | 85.9% |
| Logistic regression on the same embeddings | 80.9% | — | — | — |
| **Fine-tuned MiniLM-L6 (shipped)** | **87.7%** | **0.861** | **94.3%** | **90.7%** |
| Fine-tuned bert-base-uncased | not completed: ~3.3 h on an 8 GB M2 with heavy swapping | | | |

Known weak spots: `eviction_default` (8 test examples), `other`, generic
`termination_notice`, `lease_term_renewal`. Indian-specific clause types
are missing from the dataset: there are 4 **probation** clauses in total and
no **lock-in** type at all. Add those types and seed them with Indian
clauses next.

### Local LLM (qwen2.5:3b via Ollama), measured on a live non-compete clause

The plain explanation was good and simple, the citation was correct (Indian
Contract Act s.27, grounding "supported"), and the clause was routed to review.
Weaker than Gemini: the risk came out amber where red is expected, the
free-text legal assessment mixed in irrelevant statutes, and one clause took
about 4 minutes while another job was competing for memory. That free-text
failure is now caught by `unbacked_legal_reference` (below).

### Bugs fixed this round

- PDFs without line breaks in their text layer were analysed as a single clause.
  The PDF reader now falls back to layout extraction, and the segmenter detects
  inline "2. TITLE" headings. The document title is no longer numbered as clause 1.
- Embeddings weren't normalised (the local model cache is missing `modules.json`).
  Retrieval scores for correct matches were about 0.03; they are now about 0.5–0.6.
- An LLM outage crashed uploads with a 500 after about 100 s. It now returns
  a clear 503 within about 40 s and saves nothing.
- `.txt` uploads (used by the frontend's sample buttons) were rejected.
- `/analyze-document` responses had no `clause_text`.
- Photos and scans need `tesseract` and `poppler` installed (now documented above).

### Phases completed this round

| Phase | What |
|---|---|
| 4 | Provenance fields on statutes (`official_source`, `source_version`, `effective_date`, `last_verified`); `scripts/validate_statutes.py` lists the gaps (all 12 seed sections still need them) |
| 9 | Named routing flags: `conflicting_sources`, `jurisdiction_uncertain`, `unverified_source`, `unbacked_legal_reference` (an Act or section in the legal assessment that no claim cites) |
| 11 | `reviewer_corrections` table storing the AI prediction vs. the human decision and the reason; `GET /verification/corrections`; `scripts/export_corrections.py` |
| 13/14 | ECE, Brier score, reliability bins, and threshold recommendation (`backend/confidence/calibration.py`, `scripts/calibrate_thresholds.py`); clause-type eval with real numbers (`eval/eval_clause_types.py`) |
| 17 | Highlighted contract view: click a clause for why, legal source, confidence and what to do |
| 18 | `recommended_action` in the schema, prompt, database, API and UI |
| 19 | `tests/test_end_to_end.py`: upload, summary, agent, checks, database, review, correction, translation |
| 20 | Local LLM provider (`backend/llm/ollama.py`), selected with `LLM_PROVIDER` |

Open decision: with current retrieval scores, a clause that makes a legal claim
tops out at about 0.87 confidence, below the 0.95 auto-approve bar, so all of
them go to human review. Tune the bar from real reviews with
`scripts/calibrate_thresholds.py` rather than guessing.

## What's built (works right now, no dataset required)

| Phase | Status |
|---|---|
| 1. MVP scope lock | done (config.py `SUPPORTED_DOCUMENT_TYPES`) |
| 2. Document ingestion (PDF/DOCX/OCR) | done — `backend/ingestion/` |
| 3. Text cleaning | done — `backend/ingestion/cleaner.py` |
| 4. Clause segmentation | done — `backend/segmentation/clause_segmenter.py` |
| 5–7. RAG (chunking, vector store, retrieval) | done, seeded with **placeholder** statute data — `backend/rag/` |
| 8. ReAct agent | done — `backend/agent/`, evolved from your `version1.py` |
| 9. Risk tiers | done — `backend/risk/risk_rules.py` |
| 10. Confidence-gated verification | done — `backend/verification/` |
| 11. Multilingual output | done — `backend/translation/translator.py` |
| 12. Frontend | minimal working demo — `frontend/index.html` (not the full app UI from the mockups, just enough to exercise the API) |
| 13. API | done — `backend/main.py` + `backend/api/` (FastAPI) |
| 14. Dataset -> processed JSONL | harness built, nothing to run until you drop files in `data/raw/` — `scripts/build_dataset.py` |
| 15. Evaluation | harness built, nothing to run until `data/evaluation/gold_clauses.json` exists — `eval/` |

## Verified end-to-end in this sandbox (with a caveat you need to know about)

I installed `chromadb` and actually ran the ingestion + retrieval pipeline
here (no LLM calls needed for this part):

```bash
python -m backend.rag.ingest_laws   # -> Indexed chunks: 12
```

Then ran the exact smoke-test queries from your Phase 3 checklist
against real retrieval. Some returned the right section (e.g.
"penalty for breaking employment contract" -> Contract Act s.74,
"lock-in period" -> Model Tenancy Act s.23) but others didn't (e.g.
"employee cannot work for competitor after leaving company" should
return s.27 and instead returned an unrelated lease-definition clause).

**Why:** this sandbox has no internet access to Hugging Face, so
`sentence-transformers` can't download real pretrained weights.
`backend/rag/embeddings.py` now correctly detects that (a fix from
this session -- see below) and falls back to the deterministic hash
embedder, which is dependency-free and reproducible but **not
semantically meaningful**. That's why retrieval quality above looks
inconsistent -- it's an environment limitation, not a bug in the
retrieval/chunking/vector-store logic itself, which all ran correctly.

**Action item for you:** run `python -m backend.rag.ingest_laws` on a
machine with real internet access (so `sentence-transformers` can
download `all-MiniLM-L6-v2` and cache it) before trusting retrieval
quality. The pipeline itself is verified working; the embedding
quality in *this* sandbox specifically is not representative.

### Fix: embeddings.py was silently degrading, not just falling back

While testing this I found that `sentence-transformers` doesn't raise
an exception when it can't download weights -- it silently initializes
a fresh, **randomly-weighted, untrained** transformer with the right
shape but no semantic meaning, and worse, non-deterministic between
runs (different random init each process). Our old fallback logic only
caught actual exceptions, so this case slipped through as if it had
succeeded.

Fixed: `EmbeddingModel._load()` now tries `local_files_only=True`
first (fails fast and cleanly if nothing's cached), and if it does
attempt a live download, runs a cheap sanity check afterward (does the
model actually put similar sentences closer together than unrelated
ones?) before trusting it. If that check fails, it uses our
deterministic hash fallback instead -- worse for retrieval quality,
but at least consistent and honestly labeled as a fallback rather than
silently masquerading as a real model.

## This round: NEXT steps (11-16) -- and two more real bugs found

Ran the "NEXT" section of the roadmap to the extent honestly possible
without live model access:

- **Item 13 (human-review flow)** -- added a real "request more
  evidence" reviewer action. Previously the only actions were approve/
  edit/change_risk/reject; now a reviewer can ask Lawgorithm to re-run
  the agent on the same clause (e.g. after the legal corpus has been
  extended) instead of being stuck with a stale result and no path
  forward. Also added `flag_reason()` so the dashboard shows *why* a
  clause was flagged (fabricated citation / insufficient grounding /
  red-risk-always-reviewed / etc), not just that it was. Extracted the
  clause-field-mapping logic that was duplicated between
  `routes_documents.py` and this new re-run path into
  `backend/services/clause_service.py`.
- **Item 12 (fix retrieval/prompt issues) -- found two real bugs while
  building item 16's prerequisites, not hypothetical ones:**
  1. **The offline hash-embedding fallback was actively broken, not
     just "not semantically meaningful".** `_hash_embedding` summed
     per-word byte values in `[0, 255]/255` (all-positive), which puts
     every text's vector in the same orthant of the space -- confirmed
     empirically, two *completely unrelated* sentences scored **0.97
     cosine similarity**. That's high enough that the Phase 14
     translation-validation check (threshold 0.75) would essentially
     never fail, silently defeating the safety net it exists to
     provide, and it also biased `best_retrieval_score()`. Fixed by
     centering byte values to roughly `[-1, 1]`; verified afterward:
     unrelated sentences now score ~0.08, identical text scores 1.0, a
     genuine paraphrase scores ~0.72 (right around the threshold, which
     is sane for a crude bag-of-words-style measure).
  2. **The embedding fallback took ~78 seconds to activate**, not
     milliseconds, in a fully offline environment. `EmbeddingModel._load()`'s
     second attempt (`SentenceTransformer(EMBEDDING_MODEL_NAME)` with
     no `local_files_only`) does a live Hugging Face download attempt,
     and `sentence-transformers`/`huggingface_hub` retries with backoff
     for a long time before finally raising -- measured at 77.8s here.
     That delay hits the *first embedding call of every fresh process*.
     Fixed with a 2-second TCP connectivity probe (`_huggingface_reachable()`)
     before attempting the real download; measured startup time after
     the fix: ~5.5s (still not instant -- DNS resolution and import
     overhead account for the rest -- but a 14x improvement, not a
     multi-minute hang).
  3. Also fixed a smaller bug found while writing tests for the above:
     `translate_and_validate()`'s returned `"attempts"` count could
     understate how many regeneration attempts actually ran, because
     the "keep the best-scoring attempt" comparison used strict `>` --
     if a later attempt tied the earlier one's score (as happens
     whenever the same input produces the same output, which a
     deterministic fake/test setup does), `attempts` stayed at 1 even
     after the maximum had genuinely been tried.
- **Item 14 (evaluation dataset)** -- built `data/evaluation/gold_clauses.json`
  for real: 14 clauses across employment (non-compete, salary, penalty,
  indemnity, termination) and rental (deposit, notice, lock-in,
  eviction, lease term) categories, plus four deliberately hard cases
  (no relevant law in the corpus, ambiguous fiduciary boilerplate,
  wrong jurisdiction, an internally-contradictory carve-out clause) --
  per Phase 12's explicit instruction to include cases where the
  correct answer is abstention, not a guess. Every `expected_sources`
  ID was cross-checked against what `chunk_statute()` actually
  generates from the real seed corpus (`python -m backend.rag.ingest_laws`
  logic), not hand-typed and hoped to be right -- this caught one real
  mismatch (a double-vs-single-underscore slug difference) before it
  could silently make the eval harness look broken for the wrong
  reason.
  - Building this also surfaced a genuine design tension worth knowing
    about: the Issue-4 fix from an earlier round ("green risk + zero
    claims = no legal question, auto-grounded") can accidentally
    swallow a *different* case -- a vague clause where the model
    plausibly should have found something but didn't and just defaulted
    to green. One gold clause (`hard_ambiguous_01`) originally hit
    exactly this collision; fixed by correcting its `risk_label` to
    `amber` (which is also the more honest label for fiduciary-duty
    language), but the underlying ambiguity -- "genuinely no legal
    question" vs. "model gave up and mislabeled it green" -- is still
    only distinguished by trusting the model's own risk self-rating.
    Worth revisiting once there's real evaluation data to see how often
    this actually happens.
- **Item 16 (calibrate confidence)** -- **not done, and cannot honestly
  be done from here.** Calibration requires comparing predicted
  confidence against real expert-labelled correctness, which needs
  either live model predictions or a completed human-review history.
  Neither exists yet in this sandbox. The `GROUNDED_THRESHOLD = 0.95`
  etc. in `backend/confidence/engine.py` remain exactly what they were
  labeled as before: engineering starting points, not calibrated values.
- **Item 15 (measure hallucination) and item 11 (test 20-50 real
  clauses) -- also not honestly achievable here**, for the same reason:
  both need real model predictions, and this sandbox has no network
  route to Gemini's API. What I did instead: built an "oracle" fake
  provider (`tests/fakes/oracle_provider.py`) that already knows the
  gold answers, and ran the *entire* `eval/run_evaluation.py` pipeline
  against all 14 real gold clauses through it
  (`tests/test_eval_harness_smoke.py`). This proves the measurement
  plumbing itself works correctly end-to-end (gold data loads, every
  clause processes without crashing, citation/grounding validation
  runs, the confidence engine computes, `eval/metrics.py`'s functions
  return sane numbers) -- it does NOT produce a real hallucination rate,
  since an oracle scores ~100% by construction. Real numbers for items
  11/15/16 still require running this same harness with a live
  `GEMINI_API_KEY` on a machine with network access.
- **Fixed along the way:** a `pkg_resources`-deprecation crash
  (`textstat` breaks under `setuptools>=81`; pinned `setuptools<81` in
  `requirements.txt` -- confirmed by hitting the exact
  `ModuleNotFoundError` before pinning it) and a Pydantic warning
  (`TranslateRequest.validate` shadowed a `BaseModel` method; renamed
  to `validate_translation`).

### What's still genuinely blocked without a live model

Items 11, 15, and 16 need real Gemini predictions. The harness for all
three now exists and is proven correct mechanically
(`eval/run_evaluation.py`, `data/evaluation/gold_clauses.json`,
`tests/test_eval_harness_smoke.py`) -- running them for real is a
one-command next step (`python -m eval.run_evaluation`) the moment
there's a `GEMINI_API_KEY` and network access, not more engineering.

## This round before: actually ran the "TODAY" TODO list (items 1-10)

Items 1-4 (fix issues, `pytest -q`, RAG independent test) were already
done in the prior round -- re-confirmed: 33/33 passing before this
round's changes.

Items 5-10 (test one clause through the ReAct loop; inspect tool
calls; verify retrieved sources, claims, confidence, final JSON) had
NOT actually been run before -- this sandbox has no network access to
Gemini, so a live agent run isn't possible here. Rather than skip this
again, I added `tests/fakes/scripted_provider.py` -- a scripted fake
`LLMProvider` -- and gave `run_agent()` an optional `provider=`
parameter (production code is unaffected; it defaults to the real lazy
Gemini singleton) so the ReAct loop's *mechanics* could actually be
exercised end-to-end without a live API call:

```bash
pytest tests/test_agent_react_loop.py -v
```

covers exactly the three scenarios your roadmap's Phase 2 calls out:
- one search is enough -> FINAL
- search #1 weak, search #2 better -> FINAL (both sources tracked in
  `retrieved_source_ids`, only the second cited in the claim)
- three searches still insufficient -> cutoff -> correctly abstains
  (`status` in `insufficient_grounding`/`human_review_required`,
  `verification_status: pending`)

**This caught a real bug.** A fourth scenario -- a model that ignores
the "you've hit the search limit" instruction and requests a 4th
search anyway -- exposed an off-by-one in the loop bound: the loop
would cut the model off correctly, but then exit *before reading the
model's forced final answer*, returning a bare `{"error": "Agent did
not produce a final answer after the search cutoff."}` with zero
clause detail -- worse than the `insufficient_grounding` abstention
this whole mechanism exists to produce. Reproduced with a failing test
first, then fixed: the loop bound was `MAX_TOOL_CALLS + 1`, needed to
be `MAX_TOOL_CALLS + 2` to allow one more iteration for the post-cutoff
response. All 5 ReAct loop tests pass now, including a dedicated one
for this exact case (`test_model_ignoring_cutoff_still_gets_forced_to_a_final_answer`).

Also ran a full scripted clause through `run_agent()` and printed the
real final JSON (Step 10) -- verified the confidence engine's output
matches its own formula by hand: retrieval 0.30x0.909 + grounding
0.30x1.0 + citation 0.20x1.0 + consistency 0.10x1.0 + llm_confidence
0.10x0.8 = 0.953, which is exactly what came out.

**Still not run:** a genuinely live Gemini call. That needs a machine
with network access to Google's API and a real `GEMINI_API_KEY` --
run `python -m backend.agent.agent` there. Everything upstream and
downstream of "what Gemini actually says" is now verified; only the
live model call itself remains unverified from this sandbox.

## Fixes from this round of review

- **Issue 1 (HIGH, confirmed reproducible)** — `test_claim_validator.py` failed at collection with `ImportError: cannot import name 'genai' from 'google'` because `claim_validator.py` imported `GeminiProvider` at module load time. Reproduced by uninstalling `google-genai` and re-running `pytest`; confirmed the exact failure. Fixed by lazy-loading the import inside `_call_verifier()`. Also applied the same fix to `agent.py` and `translator.py`, which had the same fragility (module-level `provider = GeminiProvider()`) even though nothing currently importing them happened to trigger it. Verified: `import backend.agent.agent` and `import backend.translation.translator` now both succeed with `google-genai` uninstalled, and all 33 tests pass in that state.
- **Issue 2 (HIGH, confirmed real)** — `retrieval.py` used `documents` in the `ids` fallback expression before `documents` was assigned a few lines later (`UnboundLocalError` waiting to happen the first time Chroma's response omits `ids`). Fixed the ordering. Verified by monkeypatching the vector store to return a response with no `ids`/`distances` keys and confirming it no longer crashes.
- **Issue 3** — removed `retrieved_source_ids` from what the model is asked to produce. Lawgorithm already knows exactly what was retrieved (it made the tool calls) — asking the model to also self-report that list was redundant surface area for no benefit. `_finalize()` already built it from the real retrieval context, not the model's claim; now the model isn't even asked for it.
- **Issue 4** — separated "plain explanation" (always available) from "legal conclusion grounded" (only when backed by evidence). Previously a purely factual clause with no legal question (e.g. "salary is Rs 50,000/month") would get zero claims, score `grounding_score=0`, and get routed to `insufficient_grounding` / human review for no reason. Fixed: the system prompt no longer mandates a search for clauses with no legal implication, and `_finalize()` treats a green-risk, zero-claims result as its own explicit `not_applicable` / `grounded` case rather than running it through grounding scoring meant for clauses that tried to find law and failed. A non-green risk level with zero claims is still correctly flagged as inconsistent (see `tests/test_agent_finalize.py`, which exercises both cases directly with no LLM call needed).
- **Issue 5, 6, 7** — documentation-only, but made explicit rather than left implicit: the grounding verifier is itself an LLM call and needs its own evaluation, not blind trust (`claim_validator.py`); the retrieval score is an engineering heuristic, not a calibrated probability (`retrieval.py`, unchanged from last round, already documented); the translation similarity threshold is an arbitrary starting point pending a real multilingual gold set (`translator.py`).

### Verified this round

```bash
# Issue 1 -- reproduced and fixed
pip uninstall google-genai
pytest -q   # was: 1 error at collection. now: 33 passed.

# Issue 2 -- reproduced via a monkeypatched vector store response
# with no "ids"/"distances" keys; confirmed no UnboundLocalError.

# Step 2 (RAG smoke test, no LLM needed) -- ran for real:
python -c "
from backend.rag.retrieval import search_legal_reference_structured
for q in ['employee cannot join competitor after leaving company', ...]:
    print(search_legal_reference_structured(q, top_k=1))
"
# Same caveat as before: this sandbox has no internet access to
# Hugging Face, so results use the deterministic (non-semantic) hash
# fallback and are not representative of real retrieval quality --
# see "Verified end-to-end in this sandbox" above.
```

**Not run:** Step 3 (a live Gemini -> ReAct -> RAG -> validation pass on
one real clause) needs network access to Google's API, which isn't in
this sandbox's allowlist. Run `python -m backend.agent.agent` yourself
with a real `GEMINI_API_KEY` to do this -- that's still the right next
step, just not one I can execute here.

## Fixes from code review (since the first drop)

- Pinned `google-genai>=1.0.0` — the Interactions API (`client.interactions.create`, `previous_interaction_id`) needs a current SDK.
- Model name lives only in `.env` (`LAWGORITHM_MODEL`) now — no risk of README/config drift.
- `LegalVectorStore.query` no longer hard-filters by `domain`. It was silently excluding statutes like Contract Act s.27/74 from employment-clause searches just because they're tagged `"contract"` rather than `"employment"`. It now searches the whole corpus; `domain` is kept on the signature for a future rerank-not-exclude pass.
- Added more placeholder sections (security deposit, notice period, lock-in, lease definition) so the RAG smoke-test queries in "Testing it manually" below all return something.
- `/analyze-document` no longer silently drops clauses the agent failed on — they come back in a `failed_clauses` list instead of just shrinking the `clauses` array with no explanation.
- Document analysis is one transaction now: `enqueue_for_verification` no longer commits mid-loop; the endpoint commits once at the end and rolls back on error.
- `eval/run_evaluation.py` matches predictions to gold items by `clause_id`, not list position — a single agent failure used to shift every `zip()` pair after it and quietly corrupt every downstream metric.
- Clarified in `eval/metrics.py` that `hallucination_rate` only catches fabricated statute *names*; citing a real but irrelevant statute is a `grounding_precision` problem, not a hallucination by this metric's definition. Neither replaces periodic manual review.
- Added `backend/llm/` (`base.py` + `gemini.py`): the ReAct loop now talks to an `LLMProvider` interface instead of the Gemini SDK directly. Swapping providers later (`openai.py`, `anthropic.py`) means writing one new class, not touching `agent.py` or `translator.py`.

## Testing it manually

```bash
# 1. Fix/verify the Gemini SDK is wired up
python -m backend.agent.agent

# 2. Test RAG retrieval without touching the LLM at all
python -c "
from backend.rag.retrieval import search_legal_reference
for q in [
    'employee cannot work for competitor after leaving company',
    'penalty for breaking employment contract',
    'tenant eviction',
    'security deposit',
    'notice period',
    'lock-in period',
    'indemnity',
]:
    print('Q:', q)
    print(search_legal_reference(q))
    print()
"
```

## What's explicitly waiting on your dataset

- `data/statutes/sample_statutes.json` is **placeholder seed data** (a
  handful of real Contract Act / Rent Control sections) so the RAG
  pipeline and agent have something real to retrieve today. Drop the
  full bare-act corpus as additional `*.json` files (same shape) into
  `data/statutes/` and re-run `python -m backend.rag.ingest_laws` —
  nothing else changes.
- `data/raw/employment/` and `data/raw/rental/` are empty. Once you
  drop the 120-document repository in, `scripts/inspect_dataset.py`
  answers the Phase 1 questions (formats, counts, PII indicators), and
  `scripts/build_dataset.py` converts everything into
  `data/processed/documents.jsonl` / `clauses.jsonl`.
- `data/evaluation/gold_clauses.json` doesn't exist yet. Once the
  60-clause expert-labelled benchmark is ready, `eval/run_evaluation.py`
  computes risk accuracy, grounding precision, hallucination rate, and
  readability improvement against it.

## Running it

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in GEMINI_API_KEY and LAWGORITHM_MODEL

# `pip install -r requirements.txt` pulls google-genai>=1.0.0 (the
# Interactions API used in backend/agent/agent.py needs a recent SDK --
# if you ever see AttributeError on client.interactions, run
# `pip install -U google-genai`).

# one-off: seed the vector store from data/statutes/*.json
python -m backend.rag.ingest_laws

# start the API (this also seeds the vector store automatically if empty)
uvicorn backend.main:app --reload

# open frontend/index.html in a browser (points at http://localhost:8000)
```

Run the offline unit tests (no API key or network needed — they don't
touch the LLM or the embedding model):

```bash
pytest
```

## Notes on things that need real infrastructure

- **OCR** (`backend/ingestion/ocr.py`) needs the system-level
  `tesseract-ocr` and `poppler-utils` binaries installed
  (`apt install tesseract-ocr poppler-utils`), not just the pip
  packages. It fails loudly with an actionable message if they're
  missing, instead of silently producing garbage.
- **Embeddings** (`backend/rag/embeddings.py`) use
  `sentence-transformers` and need to download a model on first run
  (needs internet, or a locally cached model). If that's unavailable,
  it automatically falls back to a deterministic (non-semantic) hash
  embedding so the rest of the pipeline can still be exercised
  end-to-end in an offline dev environment — swap to a real
  internet-connected environment before you trust retrieval quality.
  **Confirmed by testing**: in the sandbox this project was built in,
  `sentence-transformers` installs fine but can't reach
  huggingface.co to download model weights, so it silently runs on the
  hash fallback. Retrieval *mechanics* (ingestion, ids, metadata,
  distance scoring) all check out end-to-end against the seed
  statutes, but retrieval *quality* on the fallback is poor by design
  (e.g. "employee cannot work for competitor" doesn't surface Section
  27 the way it should). This resolves itself automatically once
  `LegalVectorStore`/`EmbeddingModel` run somewhere with real internet
  access to Hugging Face — no code changes needed, just re-run
  `python -m backend.rag.ingest_laws` once the real model loads.
- **Vector store** persists to `./chroma_db` on disk (`CHROMA_PERSIST_DIR`
  in `.env`).
- **Database** defaults to a local SQLite file (`lawgorithm.db`); swap
  `DATABASE_URL` for Postgres later without touching any other code.

## Architecture

```
USER
  |
  v
Upload PDF / DOCX / Image
  |
  v
DOCUMENT INGESTION (PDF / DOCX / OCR)
  |
  v
CLEAN + NORMALIZE TEXT
  |
  v
CLAUSE SEGMENTATION
  |
  v
FOR EACH CLAUSE -> REACT AGENT (reason -> act -> observe)
                       |
                calls search_legal_reference
                       |
                       v
              RAG / VECTOR DATABASE (Indian legal corpus)
                       |
                relevant sections
                       |
                       v
                 LLM ANALYSIS
           (simplify, risk tag, ground, confidence)
                       |
                       v
              confidence >= 0.85 AND risk != red?
              /                              \
            yes                               no
             |                                 |
        show user                    human verifier queue
                                                |
                                       approved / edited
                                                |
                                                v
                                  multilingual explanation (on demand)
```
