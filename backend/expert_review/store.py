"""
Where expert-review tickets wait for a reviewer.

A ticket is one JSON document (see service.py). Two stores with the same
four methods:

  LocalStore      JSON files in a folder -- development and tests.
  HFDatasetStore  a PRIVATE Hugging Face dataset, one file per ticket
                  (tickets/<id>.json). Free and survives Space restarts,
                  unlike the Space's own disk. Everything is loaded into
                  memory at start-up; the Space is a single process, so
                  the in-memory copy is authoritative and every change is
                  written straight through to the dataset.
"""

import json
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)


class LocalStore:
    def __init__(self, directory: str | Path):
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, ticket_id: str) -> Path:
        return self._dir / f"{ticket_id}.json"

    def get(self, ticket_id: str) -> dict | None:
        path = self._path(ticket_id)
        return json.loads(path.read_text()) if path.exists() else None

    def put(self, ticket: dict) -> None:
        with self._lock:
            tmp = self._path(ticket["id"]).with_suffix(".tmp")
            tmp.write_text(json.dumps(ticket, ensure_ascii=False))
            tmp.replace(self._path(ticket["id"]))

    def delete(self, ticket_id: str) -> None:
        self._path(ticket_id).unlink(missing_ok=True)

    def all(self) -> list[dict]:
        return [json.loads(p.read_text()) for p in sorted(self._dir.glob("*.json"))]

    # small named settings documents (e.g. the reviewer list), kept apart from tickets
    def get_meta(self, name: str, default=None):
        path = self._dir / "meta" / f"{name}.json"
        return json.loads(path.read_text()) if path.exists() else default

    def put_meta(self, name: str, data) -> None:
        with self._lock:
            (self._dir / "meta").mkdir(exist_ok=True)
            tmp = self._dir / "meta" / f"{name}.tmp"
            tmp.write_text(json.dumps(data, ensure_ascii=False))
            tmp.replace(self._dir / "meta" / f"{name}.json")


class HFDatasetStore:
    def __init__(self, repo_id: str, token: str):
        from huggingface_hub import HfApi

        self._api = HfApi(token=token)
        self._repo = repo_id
        self._lock = threading.Lock()
        self._tickets: dict[str, dict] = {}
        self._meta: dict[str, object] = {}
        self._load()

    def _load(self) -> None:
        from huggingface_hub import hf_hub_download

        all_files = self._api.list_repo_files(self._repo, repo_type="dataset")
        for name in [f for f in all_files if f.startswith("meta/") and f.endswith(".json")]:
            path = hf_hub_download(self._repo, name, repo_type="dataset", token=self._api.token)
            self._meta[name[len("meta/"):-len(".json")]] = json.loads(Path(path).read_text())
        files = [f for f in all_files if f.startswith("tickets/") and f.endswith(".json")]
        for name in files:
            path = hf_hub_download(self._repo, name, repo_type="dataset", token=self._api.token)
            ticket = json.loads(Path(path).read_text())
            self._tickets[ticket["id"]] = ticket
        logger.info("Expert review: %d ticket(s) loaded", len(self._tickets))

    def get(self, ticket_id: str) -> dict | None:
        with self._lock:
            ticket = self._tickets.get(ticket_id)
            return json.loads(json.dumps(ticket)) if ticket else None

    def put(self, ticket: dict) -> None:
        with self._lock:
            self._api.upload_file(
                path_or_fileobj=json.dumps(ticket, ensure_ascii=False).encode(),
                path_in_repo=f"tickets/{ticket['id']}.json",
                repo_id=self._repo, repo_type="dataset",
                commit_message="update ticket",   # never contract content in commit messages
            )
            self._tickets[ticket["id"]] = ticket

    def delete(self, ticket_id: str) -> None:
        with self._lock:
            if self._tickets.pop(ticket_id, None) is not None:
                self._api.delete_file(f"tickets/{ticket_id}.json", repo_id=self._repo,
                                      repo_type="dataset", commit_message="delete ticket")
                # A dataset is a git repo: the file would live on in its
                # history. Squashing the history makes the deletion real
                # (DPDP right to erasure), and drops older edits too.
                try:
                    self._api.super_squash_history(repo_id=self._repo, repo_type="dataset")
                except Exception as exc:  # the delete itself succeeded; retried on the next one
                    logger.warning("Expert review: history squash failed (%s)", type(exc).__name__)

    def all(self) -> list[dict]:
        with self._lock:
            return json.loads(json.dumps(list(self._tickets.values())))

    def get_meta(self, name: str, default=None):
        with self._lock:
            return json.loads(json.dumps(self._meta[name])) if name in self._meta else default

    def put_meta(self, name: str, data) -> None:
        with self._lock:
            self._api.upload_file(
                path_or_fileobj=json.dumps(data, ensure_ascii=False).encode(),
                path_in_repo=f"meta/{name}.json", repo_id=self._repo, repo_type="dataset",
                commit_message=f"update {name}",
            )
            self._meta[name] = data
