"""
Publish Lawgorithm to a free Hugging Face Space (Gradio SDK, ZeroGPU).

    python -m scripts.deploy_space                 # build bundle + publish
    python -m scripts.deploy_space --build-only    # just build build/space/ (local test)

Needs, on this machine (never in code or chat):
  - `hf auth login` with a token that has WRITE access
  - GROQ_API_KEY in .env  (sent to the Space as a private *secret*)
  - optional PRIVACY_CONTACT in .env (grievance contact shown in the
    privacy notice, DPDP Act)
  - for expert review (human in the loop), in .env:
      REVIEWER_KEYS   -- added with `python -m scripts.add_reviewer "Name"`
      HF_REVIEW_TOKEN -- a FINE-GRAINED Hugging Face token with write access
                         to ONLY the review dataset (created here, private)
    Both go to the Space as private secrets. Without them expert review is
    off and "expert check" clauses point to free legal aid (NALSA 15100).

What gets uploaded (build/space/): the backend, the website, the statute
library + a statute-only search index (~10 MB), and the fine-tuned clause
classifier. NOT uploaded: training data, the 63k-clause example index,
local translation models, the local database, .env.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build" / "space"
SPACE_NAME = "lawgorithm"
REVIEW_DATASET_NAME = "lawgorithm-review-queue"

PUBLIC_VARIABLES = {
    "LLM_PROVIDER": "groq",
    "TRANSLATION_ENGINE": "llm",
    "STORE_ANALYSES": "false",
    "RESULT_TTL_MINUTES": "60",
}


def build_bundle() -> Path:
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")

    for name in ("app.py", "gpu_inference.py", "requirements.txt", "packages.txt", "README.md"):
        shutil.copy(ROOT / "deploy" / "space" / name, BUILD / name)
    shutil.copytree(ROOT / "backend", BUILD / "backend", ignore=ignore)
    shutil.copytree(ROOT / "frontend", BUILD / "frontend", ignore=ignore)
    shutil.copytree(ROOT / "data" / "statutes", BUILD / "data" / "statutes", ignore=ignore)
    shutil.copytree(ROOT / "models" / "clause_classifier" / "minilm-l6",
                    BUILD / "models" / "clause_classifier" / "minilm-l6", ignore=ignore)

    # Fresh statute-only index, built into the bundle (not the local 500 MB one).
    env = {**os.environ, "CHROMA_PERSIST_DIR": str(BUILD / "chroma_db")}
    subprocess.run([sys.executable, "-c", "from backend.rag.ingest_laws import build_index; build_index(reset=True)"],
                   cwd=ROOT, env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    size_mb = sum(f.stat().st_size for f in BUILD.rglob("*") if f.is_file()) / 1e6
    print(f"Bundle ready: {BUILD} ({size_mb:.0f} MB)")
    return BUILD


def publish(bundle: Path) -> str:
    from huggingface_hub import HfApi

    settings = dotenv_values(ROOT / ".env")
    groq_key = (settings.get("GROQ_API_KEY") or os.environ.get("GROQ_API_KEY") or "").strip()
    if not groq_key:
        sys.exit("GROQ_API_KEY is missing from .env -- add it there first (never paste it in chat).")

    api = HfApi()
    user = api.whoami()["name"]
    repo_id = f"{user}/{SPACE_NAME}"
    api.create_repo(repo_id, repo_type="space", space_sdk="gradio", space_hardware="zero-a10g",
                    exist_ok=True, private=False)

    api.add_space_secret(repo_id, "GROQ_API_KEY", groq_key)   # private; never printed
    variables = dict(PUBLIC_VARIABLES)
    if settings.get("PRIVACY_CONTACT"):
        variables["PRIVACY_CONTACT"] = settings["PRIVACY_CONTACT"]
    variables.update(_expert_review_settings(api, user, repo_id, settings))
    variables.update(_payment_settings(api, repo_id, settings))
    for key, value in variables.items():
        api.add_space_variable(repo_id, key, value)

    api.upload_folder(folder_path=str(bundle), repo_id=repo_id, repo_type="space",
                      commit_message="Deploy Lawgorithm")
    url = f"https://{user.lower()}-{SPACE_NAME}.hf.space"
    print(f"Published: https://huggingface.co/spaces/{repo_id}")
    print(f"Live site (after the build finishes, ~5-10 min): {url}")
    return url


def _payment_settings(api, space_id: str, settings: dict) -> dict:
    """Razorpay keys as private secrets; prices/business details as variables. No keys = free."""
    key_id = (settings.get("RAZORPAY_KEY_ID") or "").strip()
    secret = (settings.get("RAZORPAY_KEY_SECRET") or "").strip()
    if not (key_id and secret):
        for name in ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET"):
            try:
                api.delete_space_secret(space_id, name)
            except Exception:
                pass
        print("Payments: OFF (no RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET in .env) -- everything is free.")
        out = {}
    else:
        api.add_space_secret(space_id, "RAZORPAY_KEY_ID", key_id)
        api.add_space_secret(space_id, "RAZORPAY_KEY_SECRET", secret)          # never printed
        mode = "TEST mode" if key_id.startswith("rzp_test_") else "LIVE"
        print(f"Payments: ON ({mode}) -- Rs {int(settings.get('PRICE_ANALYSIS_PAISE') or 1000) // 100} per contract")
        out = {}
    for name in ("PRICE_ANALYSIS_PAISE", "EXPERT_REVIEW_PRICE_PAISE", "BUSINESS_NAME", "CONTACT_EMAIL"):
        if (settings.get(name) or "").strip():
            out[name] = settings[name].strip()
    return out


def _expert_review_settings(api, user: str, space_id: str, settings: dict) -> dict:
    """Private review-queue dataset + reviewer secrets; off unless both are configured."""
    reviewers = (settings.get("REVIEWER_KEYS") or "").strip()
    token = (settings.get("HF_REVIEW_TOKEN") or "").strip()
    dataset = f"{user}/{REVIEW_DATASET_NAME}"
    api.create_repo(dataset, repo_type="dataset", private=True, exist_ok=True)
    if not (reviewers and token):
        print("Expert review: OFF on the live site (needs REVIEWER_KEYS and HF_REVIEW_TOKEN in .env).")
        print(f"  1. python -m scripts.add_reviewer \"Name\"   (once per partner reviewer)")
        print(f"  2. https://huggingface.co/settings/tokens -> Fine-grained -> write access to {dataset} only")
        print("     -> put it in .env as HF_REVIEW_TOKEN=... (never paste it in chat)")
        print("  3. python -m scripts.deploy_space")
        return {"EXPERT_REVIEW_STORE": "off"}
    api.add_space_secret(space_id, "REVIEWER_KEYS", reviewers)     # private; never printed
    api.add_space_secret(space_id, "HF_REVIEW_TOKEN", token)
    print(f"Expert review: ON -- {len([r for r in reviewers.split(';') if r.strip()])} reviewer(s), queue in private dataset {dataset}")
    kind = (settings.get("REVIEWER_KIND") or "team").strip().lower()
    print(f"  People are told their clauses go to: {'a lawyer or law student' if kind == 'legal' else 'the Lawgorithm team'}"
          " (set REVIEWER_KIND=legal in .env once a lawyer/law student reviews)")
    return {"EXPERT_REVIEW_STORE": "hf", "REVIEW_DATASET": dataset, "REVIEWER_KIND": kind}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-only", action="store_true")
    args = parser.parse_args()
    bundle = build_bundle()
    if not args.build_only:
        publish(bundle)


if __name__ == "__main__":
    main()
