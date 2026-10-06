"""
Fine-tune a BERT-family model as the clause-type classifier.

Replaces the kNN vote over MiniLM embeddings (rag/clause_index.py) with
a model trained end-to-end on the labelled clause corpus built by
scripts/build_clause_corpus.py. No API key, runs locally (Apple MPS /
CUDA / CPU).

    python -m scripts.train_clause_classifier --model bert-base-uncased
    python -m scripts.train_clause_classifier --model nlpaueb/legal-bert-base-uncased
    python -m scripts.train_clause_classifier --model bert-base-uncased --limit-train 500 --epochs 1   # smoke test
    # what produced the shipped model (MiniLM-L6, ~45 min on an 8 GB M2):
    python -m scripts.train_clause_classifier --model sentence-transformers/all-MiniLM-L6-v2 \
        --epochs 3 --lr 1e-4 --batch-size 32 --name minilm-l6

Writes models/clause_classifier/<model-slug>/ (weights, tokenizer,
labels.json, metrics.json). The held-out metrics use the same
definitions as eval/eval_clause_types.py so the numbers are directly
comparable with the kNN baseline.

Point the backend at a trained model with CLAUSE_CLASSIFIER_DIR (see
backend/config.py); without it the kNN vote is used.
"""

import argparse
import json
import math
import random
import time
from pathlib import Path

import torch
from torch.utils.data import DataLoader

from backend.config import BASE_DIR, CLAUSE_CORPUS_DIR, CLAUSE_TYPE_MIN_CONFIDENCE
from eval.clause_type_metrics import classification_report

MODELS_DIR = BASE_DIR / "models" / "clause_classifier"


def pick_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def load_split(name: str) -> list[dict]:
    with open(CLAUSE_CORPUS_DIR / f"{name}.jsonl", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


@torch.no_grad()
def predict(model, tokenizer, texts: list[str], device, max_len: int, batch_size: int = 64) -> torch.Tensor:
    model.eval()
    probs = []
    for start in range(0, len(texts), batch_size):
        enc = tokenizer(texts[start:start + batch_size], truncation=True, max_length=max_len,
                        padding=True, return_tensors="pt").to(device)
        probs.append(torch.softmax(model(**enc).logits.float(), dim=-1).cpu())
    return torch.cat(probs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="bert-base-uncased")
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-len", type=int, default=128)
    parser.add_argument("--lr", type=float, default=3e-5)
    parser.add_argument("--limit-train", type=int, default=None)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--name", default=None, help="output folder name (default: derived from --model)")
    args = parser.parse_args()

    from transformers import AutoModelForSequenceClassification, AutoTokenizer, get_linear_schedule_with_warmup

    random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = pick_device()

    train, test = load_split("train"), load_split("test")
    if args.limit_train:
        train = random.Random(args.seed).sample(train, args.limit_train)
    labels = sorted({r["clause_type"] for r in train} | {r["clause_type"] for r in test})
    label_to_id = {l: i for i, l in enumerate(labels)}

    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.model, num_labels=len(labels),
        id2label=dict(enumerate(labels)), label2id=label_to_id,
    ).to(device)

    def collate(batch):
        enc = tokenizer([r["clause_text"] for r in batch], truncation=True, max_length=args.max_len,
                        padding=True, return_tensors="pt")
        enc["labels"] = torch.tensor([label_to_id[r["clause_type"]] for r in batch])
        return enc

    loader = DataLoader(train, batch_size=args.batch_size, shuffle=True, collate_fn=collate)
    total_steps = args.epochs * len(loader)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    scheduler = get_linear_schedule_with_warmup(optimizer, int(0.06 * total_steps), total_steps)

    print(f"device={device} model={args.model} train={len(train)} test={len(test)} "
          f"labels={len(labels)} steps={total_steps}", flush=True)
    started, step = time.time(), 0
    for epoch in range(args.epochs):
        model.train()
        running = 0.0
        for batch in loader:
            batch = batch.to(device)
            loss = model(**batch).loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad()
            step += 1
            running += loss.item()
            if step % 200 == 0 or step == total_steps:
                rate = step / (time.time() - started)
                eta = (total_steps - step) / rate / 60
                print(f"epoch {epoch + 1} step {step}/{total_steps} loss {running / 200:.4f} "
                      f"({rate:.1f} it/s, ~{eta:.0f} min left)", flush=True)
                running = 0.0

    probs = predict(model, tokenizer, [r["clause_text"] for r in test], device, args.max_len)
    conf, pred = probs.max(dim=-1)
    report = classification_report(
        truth=[r["clause_type"] for r in test],
        predicted=[labels[i] for i in pred.tolist()],
        confidence=conf.tolist(),
        min_confidence=CLAUSE_TYPE_MIN_CONFIDENCE,
    )
    report.update({"model": args.model, "epochs": args.epochs, "max_len": args.max_len,
                   "train_size": len(train), "train_minutes": round((time.time() - started) / 60, 1)})

    out_dir = MODELS_DIR / (args.name or Path(args.model.rstrip("/")).name.replace("/", "__"))
    out_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out_dir)
    tokenizer.save_pretrained(out_dir)
    (out_dir / "labels.json").write_text(json.dumps(labels, indent=2))
    (out_dir / "metrics.json").write_text(json.dumps(report, indent=2))

    print(f"\nHeld-out top-1 accuracy: {report['top1_accuracy']:.1%}  macro-F1: {report['macro_f1']:.3f}")
    selective = report["selective_accuracy"]
    print(f"Hint coverage: {report['coverage']:.1%}  accuracy when hinted: "
          f"{'n/a' if selective is None else f'{selective:.1%}'}")
    print(f"Saved to {out_dir}")


if __name__ == "__main__":
    main()
