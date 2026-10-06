"""
Hugging Face Space entry point (Gradio SDK, ZeroGPU hardware).

Free Hugging Face accounts can host Gradio Spaces (on ZeroGPU), not
Docker ones, so Lawgorithm's FastAPI app is served from a Gradio Space:
the Gradio app is itself a FastAPI app, and ours is mounted around it.
The website and API are served at "/" exactly as when run locally; a
tiny Gradio page lives at /gradio only because the SDK expects one.

All AI work goes to Groq (GROQ_API_KEY is a Space *secret*), so no GPU
is needed; privacy mode is on (STORE_ANALYSES=false): contracts are
processed in memory and never written to disk.
"""

import os

os.environ.setdefault("LLM_PROVIDER", "groq")
os.environ.setdefault("TRANSLATION_ENGINE", "llm")
os.environ.setdefault("STORE_ANALYSES", "false")
os.environ.setdefault("CLAUSE_CLASSIFIER_DIR", os.path.join(os.path.dirname(__file__), "models", "clause_classifier", "minilm-l6"))

from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from gradio import Server  # noqa: E402

from backend.main import app as api, on_startup  # noqa: E402
from backend.rag import clause_classifier  # noqa: E402

# ZeroGPU: the clause classifier runs on the GPU (see gpu_inference.py).
# Off ZeroGPU (e.g. a local test) there's no CUDA, so keep the CPU model.
try:
    import gpu_inference  # noqa: E402

    clause_classifier.GPU_PREDICT = gpu_inference.classify_on_gpu
except Exception as exc:  # no GPU environment
    print(f"GPU inference not enabled ({type(exc).__name__}); classifier runs on CPU.", flush=True)

# Gradio's Server mode is a FastAPI app that Gradio itself launches, which
# is what ZeroGPU expects (its startup hooks find the @spaces.GPU function
# during launch). Running our own uvicorn skipped those hooks ("No
# @spaces.GPU function detected"). Lawgorithm's routes are moved onto it
# unchanged, so the site and API are served at "/" as when run locally.
server = Server(title="Lawgorithm")
server.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
for route in api.router.routes:
    server.router.routes.append(route)

if __name__ == "__main__":
    on_startup()   # create the (empty) database tables; index the statutes if needed
    # ssr_mode=False: Spaces set GRADIO_SSR_MODE=true, whose Node.js server
    # would otherwise take port 7860 ("address already in use").
    server.launch(server_name="0.0.0.0", server_port=int(os.environ.get("PORT", "7860")), ssr_mode=False)
