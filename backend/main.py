"""
Lawgorithm API entrypoint.

    uvicorn backend.main:app --reload
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.database.db import init_db
from backend.rag.vector_store import LegalVectorStore
from backend.rag.ingest_laws import build_index
from backend.api import routes_analysis, routes_contact, routes_documents, routes_expert, routes_payments, routes_verification

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Lawgorithm API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten before shipping past the prototype stage
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_documents.router, tags=["documents"])
app.include_router(routes_analysis.router, tags=["analysis"])
app.include_router(routes_verification.router, tags=["verification"])
app.include_router(routes_expert.router, tags=["expert review"])
app.include_router(routes_payments.router, tags=["payments"])
app.include_router(routes_contact.router, tags=["contact"])


from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

    @app.get("/")
    def index():
        return FileResponse(str(frontend_dir / "index.html"))

    @app.get("/style.css")
    def get_style():
        return FileResponse(str(frontend_dir / "style.css"))

    @app.get("/app.js")
    def get_app_js():
        return FileResponse(str(frontend_dir / "app.js"))

    @app.get("/i18n.js")
    def get_i18n_js():
        return FileResponse(str(frontend_dir / "i18n.js"))


@app.on_event("startup")
def on_startup():
    init_db()

    store = LegalVectorStore.get()
    if store.is_empty():
        logger.info("Vector store is empty -- seeding from data/statutes/*.json")
        build_index()


@app.get("/health")
def health(deep: bool = False):
    if not deep:
        return {"status": "ok"}
    # /health?deep=true: are embeddings real? (all-zero vectors broke
    # translation checks and retrieval on ZeroGPU once -- see embeddings.py)
    from backend.rag.embeddings import EmbeddingModel

    model = EmbeddingModel.get()
    a, b, c = model.embed(["security deposit refund", "return of the deposit", "quantum physics"])
    cos = lambda x, y: sum(i * j for i, j in zip(x, y)) / ((sum(i * i for i in x) ** .5 * sum(j * j for j in y) ** .5) or 1)
    related, unrelated = cos(a, b), cos(a, c)
    return {"status": "ok", "embeddings": "fallback" if model._use_fallback else "model",
            "embeddings_ok": related > unrelated + 0.1, "related": round(related, 3), "unrelated": round(unrelated, 3)}
