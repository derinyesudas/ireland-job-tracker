"""
Opens and closes the locked research files around a workflow run.

The scraper reads the employer register and the CV profile as ordinary JSON,
so before it runs those files are decrypted into place, and afterwards they
are locked again. The passphrase comes from the TRACKER_KEY repository secret
and never touches the disk.

  python scripts/vault.py open    before the scraper
  python scripts/vault.py close   after it

Only files that actually changed get re-encrypted. Encrypting produces a
different result every time even for identical content - a fresh random nonce
each run - so re-encrypting blindly would make every run look like a change
and commit noise into the history.
"""

import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import crypt as C

ROOT = Path(__file__).resolve().parent.parent

# The research. The job board and run stats are deliberately absent - they
# stay readable so the site works for visitors.
PROTECTED = [
    "data/ireland_register.json",
    "data/companies.json",
    "data/resolution_report.json",
    "data/site_inspection.json",
    "data/seed_companies.json",
    "data/feed_health.json",
    "profile/derin.json",
]

STATE = ROOT / ".vault-state.json"


def passphrase() -> str:
    key = os.environ.get("TRACKER_KEY", "")
    if not key:
        sys.exit("TRACKER_KEY is not set. In Actions this comes from the "
                 "repository secret of that name.")
    return key


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def do_open() -> None:
    key = C.unlock(passphrase(), ROOT / "data/keys.json")
    state, opened = {}, 0
    for rel in PROTECTED:
        enc = ROOT / (rel + ".enc")
        if not enc.exists():
            print(f"  no locked copy of {rel}, skipping")
            continue
        plain = C.unlock_file(enc, key)
        state[rel] = sha(plain)
        opened += 1
    STATE.write_text(json.dumps(state))
    print(f"opened {opened} files")


def do_close() -> None:
    key = C.unlock(passphrase(), ROOT / "data/keys.json")
    before = json.loads(STATE.read_text()) if STATE.exists() else {}
    changed = unchanged = 0
    for rel in PROTECTED:
        plain = ROOT / rel
        if not plain.exists():
            continue
        if before.get(rel) == sha(plain):
            plain.unlink()          # identical - keep the existing ciphertext
            unchanged += 1
            continue
        C.lock_file(plain, key)     # changed - write a new locked copy
        changed += 1
    STATE.unlink(missing_ok=True)
    print(f"closed {changed + unchanged} files "
          f"({changed} re-locked, {unchanged} unchanged so left alone)")

    left = [r for r in PROTECTED if (ROOT / r).exists()]
    if left:
        sys.exit(f"plaintext still on disk: {left}")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"open", "close"}:
        sys.exit(__doc__)
    (do_open if sys.argv[1] == "open" else do_close)()
