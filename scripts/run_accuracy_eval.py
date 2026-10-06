"""
Measure Lawgorithm's accuracy on the 50 expert-labelled clauses
(data/evaluation/gold_clauses.json) with the live AI setup.

    python -m scripts.run_accuracy_eval

Run it on a fresh day: it uses ~200k tokens, about the main model's whole
free daily allowance. It records which model answered, because results
from a fallback model don't describe the normal setup. Writes
data/evaluation/latest_metrics.json.
"""

import collections
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
os.environ.setdefault("LLM_PROVIDER", "groq")

import httpx  # noqa: E402

calls, tokens = collections.Counter(), collections.Counter()
_post = httpx.Client.post


def _counting_post(self, url, *args, **kwargs):
    response = _post(self, url, *args, **kwargs)
    if "chat/completions" in str(url) and response.status_code == 200:
        model = kwargs["json"]["model"]
        calls[model] += 1
        tokens[model] += response.json().get("usage", {}).get("total_tokens", 0)
    return response


httpx.Client.post = _counting_post


def main():
    from eval.run_evaluation import run

    started = time.time()
    metrics = run()
    metrics.update({"seconds": round(time.time() - started), "calls_by_model": dict(calls),
                    "tokens_by_model": dict(tokens), "run_at": time.strftime("%Y-%m-%d %H:%M")})
    main_model = os.environ.get("GROQ_MODEL_AGENT", "openai/gpt-oss-120b")
    share = calls[main_model] / max(sum(calls.values()), 1)
    metrics["main_model_share"] = round(share, 2)
    if share < 0.8:
        print(f"NOTE: only {share:.0%} of AI calls used {main_model} (daily limits) -- not representative.")
    out = Path(__file__).resolve().parent.parent / "data" / "evaluation" / "latest_metrics.json"
    out.write_text(json.dumps(metrics, indent=2, default=str))
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
