"""
Give the board its own access code, separate from the vault passphrase.

Why bother: TRACKER_KEY opens the research vault - every company, every feed,
every note. The board code gets typed into a browser, on whatever machine
happens to be to hand. Those should not be the same secret, and crypt.py
already supports several holders opening the same data, so they need not be.

    TRACKER_KEY=<vault passphrase> python -m scripts.add_board_code

It asks for the new board code, adds a 'board' holder, and prints nothing
secret. Run it once. Afterwards both codes open the board; only the vault
passphrase opens the vault.
"""

from __future__ import annotations

import sys
from getpass import getpass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import crypt  # noqa: E402

KEYS = Path("data/keys.json")


def main() -> int:
    owner = crypt._passphrase("Vault passphrase: ")
    if not owner:
        print("no vault passphrase given")
        return 1
    if crypt.who(owner, KEYS) != "owner":
        print("that is not the owner passphrase")
        return 1

    holders = crypt.load_keys(KEYS)["holders"]
    if "board" in holders:
        print("a board code already exists - revoke it first if you want a new one")
        return 1

    code = getpass("New board code: ").strip()
    again = getpass("Type it again:  ").strip()
    if code != again:
        print("those did not match - nothing changed")
        return 1
    if len(code) < 10:
        print("too short - use at least 10 characters, letters and digits")
        return 1

    crypt.add_holder(owner, "board", code, KEYS)
    print("\n  board code added.")
    print("  holders now:", ", ".join(crypt.load_keys(KEYS)["holders"]))
    print("  the board opens with this code; the vault still needs the passphrase.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
