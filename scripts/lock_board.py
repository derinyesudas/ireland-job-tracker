"""
Lock the published board so only a passphrase opens it.

The site's data files are encrypted with the same data key as the research
vault, using the same format, so the browser can open them with WebCrypto:

    site/data/jobs.json   ->  site/data/jobs.json.enc
    site/data/stats.json  ->  site/data/stats.json.enc
    data/keys.json        ->  site/data/keys.json   (copied, safe to publish)

The plaintext copies are removed from site/data afterwards. That is the whole
point: a visitor without the passphrase can fetch every file the site serves
and still see nothing, because there is nothing readable there to see.

keys.json is published deliberately. It holds each holder's copy of the data
key, locked under their own passphrase - useless to anyone who cannot supply
one, and necessary for the browser to find the right one to try.

Run after the scrape, with TRACKER_KEY in the environment:
    python -m scripts.lock_board
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import crypt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SITE_DATA = ROOT / "site" / "data"
KEYS = ROOT / "data" / "keys.json"
TARGETS = ["jobs.json", "stats.json"]


def main() -> int:
    passphrase = crypt._passphrase("Board passphrase: ")
    if not passphrase:
        print("no passphrase - refusing to publish an unlocked board")
        return 1
    try:
        data_key = crypt.unlock(passphrase, KEYS)
    except Exception as exc:
        print(f"could not unlock: {exc}")
        return 1

    locked = 0
    for name in TARGETS:
        plain = SITE_DATA / name
        if not plain.exists():
            print(f"  {name}: not published this run, skipping")
            continue
        crypt.lock_file(plain, data_key, keep_plaintext=False)
        size = (SITE_DATA / f"{name}.enc").stat().st_size
        print(f"  {name} -> {name}.enc ({size // 1024} KB), plaintext removed")
        locked += 1

    shutil.copyfile(KEYS, SITE_DATA / "keys.json")
    print(f"  keys.json copied to site/data")

    # A published plaintext file would silently undo all of this, so say so
    # loudly rather than leaving it to be noticed later.
    leaks = [p.name for p in SITE_DATA.glob("*.json") if p.name != "keys.json"]
    if leaks:
        print(f"  WARNING: still readable in site/data: {', '.join(leaks)}")
        return 1
    print(f"  board locked: {locked} file(s) encrypted, nothing readable published")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
