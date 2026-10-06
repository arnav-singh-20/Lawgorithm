"""
Give a partner reviewer (lawyer / law student) a personal key for the
reviewer desk (https://<site>/#/review).

    python -m scripts.add_reviewer "Adv. Asha Rao"
    python -m scripts.add_reviewer --list
    python -m scripts.add_reviewer --remove "Adv. Asha Rao"

Keys live in .env as REVIEWER_KEYS (never in code); `python -m
scripts.deploy_space` sends them to the Space as a private secret. The new
key is printed ONCE -- send it to the reviewer privately (not by email
in plain sight of others, not in a group chat). Removing a reviewer and
redeploying revokes their key.
"""

import argparse
import secrets
import sys
from pathlib import Path

from dotenv import dotenv_values, set_key

ENV = Path(__file__).resolve().parent.parent / ".env"


def _load() -> dict[str, str]:
    """{name: key}"""
    raw = dotenv_values(ENV).get("REVIEWER_KEYS") or ""
    out = {}
    for entry in raw.split(";"):
        name, _, key = entry.strip().rpartition("=")
        if name.strip() and key.strip():
            out[name.strip()] = key.strip()
    return out


def _save(reviewers: dict[str, str]) -> None:
    ENV.touch(exist_ok=True)
    set_key(str(ENV), "REVIEWER_KEYS", ";".join(f"{n}={k}" for n, k in reviewers.items()), quote_mode="always")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("name", nargs="*", help='e.g. Arnav Singh (quotes optional)')
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--remove", metavar="NAME")
    args = parser.parse_args()
    args.name = " ".join(args.name).strip()
    reviewers = _load()

    if args.list:
        print("\n".join(reviewers) or "No reviewers yet.")
        return
    if args.remove:
        if reviewers.pop(args.remove, None) is None:
            sys.exit(f"No reviewer called {args.remove!r}.")
        _save(reviewers)
        print(f"Removed {args.remove}. Redeploy (python -m scripts.deploy_space) to revoke their key on the live site.")
        return
    if not args.name or any(c in args.name for c in "=;\n"):
        sys.exit('Give the reviewer\'s display name, e.g. python -m scripts.add_reviewer "Adv. Asha Rao"')
    if args.name in reviewers:
        sys.exit(f"{args.name!r} already has a key. Remove them first to issue a new one.")

    key = secrets.token_urlsafe(24)
    reviewers[args.name] = key
    _save(reviewers)
    print(f"Reviewer added: {args.name}")
    print(f"Their key (shown once -- send it privately): {key}")
    print("They sign in at <your site>/#/review. Redeploy to make the key work on the live site.")


if __name__ == "__main__":
    main()
