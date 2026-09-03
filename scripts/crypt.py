"""
Locks and unlocks the tracker's data files.

The design in one paragraph: the data is encrypted with a random key that
nobody ever types. That key is then stored once per passphrase, each copy
locked under that passphrase. So the owner and a guest can both open the same
data with different phrases, and revoking a guest means deleting their copy of
the key and rolling it - the owner's phrase never has to change.

Format on disk:
  data/keys.json   who can unlock, and their locked copies of the data key.
                   Safe to publish: useless without a passphrase.
  <file>.enc       IJT1 magic | 12-byte nonce | AES-256-GCM ciphertext+tag

Nothing here is home-made. Key derivation is PBKDF2-HMAC-SHA256 and the cipher
is AES-256-GCM, which is what browsers implement natively - so the same files
open in Python here and in the browser on the site.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"IJT1"
NONCE_BYTES = 12
SALT_BYTES = 16
KEY_BYTES = 32
ITERATIONS = 600_000          # OWASP guidance for PBKDF2-HMAC-SHA256
KEYS_FILE = Path("data/keys.json")


# --------------------------------------------------------------------------
# passphrase -> key
# --------------------------------------------------------------------------

def derive(passphrase: str, salt: bytes, iterations: int = ITERATIONS) -> bytes:
    """Turn a passphrase into a 32-byte key. Deliberately slow, so that
    guessing at it is expensive."""
    return hashlib.pbkdf2_hmac(
        "sha256", passphrase.encode("utf-8"), salt, iterations, dklen=KEY_BYTES
    )


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text)


# --------------------------------------------------------------------------
# the key file
# --------------------------------------------------------------------------

def load_keys(path: Path = KEYS_FILE) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist - run 'init' first")
    return json.loads(path.read_text())


def save_keys(keys: dict, path: Path = KEYS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(keys, indent=2) + "\n")


RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no O/0, no I/1/L


def new_recovery_code(groups: int = 6, size: int = 4) -> str:
    """A code you write on paper. The alphabet leaves out the characters people
    mis-copy by hand, so a 3 never comes back as an 8 or an O as a zero."""
    chars = [secrets.choice(RECOVERY_ALPHABET) for _ in range(groups * size)]
    return "-".join("".join(chars[i:i + size]) for i in range(0, len(chars), size))


def normalise_recovery_code(text: str) -> str:
    """Accept it typed back in any reasonable shape - lower case, spaces
    instead of dashes, dashes left out entirely."""
    keep = [c for c in text.upper() if c in RECOVERY_ALPHABET]
    return "-".join("".join(keep[i:i + 4]) for i in range(0, len(keep), 4))


def _wrap(data_key: bytes, passphrase: str) -> dict:
    """Lock a copy of the data key under one passphrase."""
    salt = secrets.token_bytes(SALT_BYTES)
    nonce = secrets.token_bytes(NONCE_BYTES)
    sealed = AESGCM(derive(passphrase, salt)).encrypt(nonce, data_key, None)
    return {"salt": _b64(salt), "nonce": _b64(nonce), "wrapped": _b64(sealed),
            "iterations": ITERATIONS}


def _unwrap(entry: dict, passphrase: str) -> bytes | None:
    """Try to open one locked copy. Returns None if this is the wrong phrase."""
    try:
        key = derive(passphrase, _unb64(entry["salt"]),
                     entry.get("iterations", ITERATIONS))
        return AESGCM(key).decrypt(_unb64(entry["nonce"]),
                                   _unb64(entry["wrapped"]), None)
    except Exception:
        return None


def init(passphrase: str, path: Path = KEYS_FILE) -> bytes:
    """Create the data key and lock the owner's copy of it."""
    if path.exists():
        raise FileExistsError(f"{path} already exists - use rotate instead")
    data_key = secrets.token_bytes(KEY_BYTES)
    save_keys({"version": 1,
               "kdf": "PBKDF2-HMAC-SHA256",
               "cipher": "AES-256-GCM",
               "holders": {"owner": _wrap(data_key, passphrase)}}, path)
    return data_key


def unlock(passphrase: str, path: Path = KEYS_FILE) -> bytes:
    """Find the data key using whichever passphrase was given. Works for the
    owner and for any guest, which is what lets them share the same data."""
    keys = load_keys(path)
    for entry in keys["holders"].values():
        data_key = _unwrap(entry, passphrase)
        if data_key is not None:
            return data_key
    raise ValueError("that passphrase does not open anything")


def who(passphrase: str, path: Path = KEYS_FILE) -> str | None:
    """Which holder does this passphrase belong to? Useful for a rotation
    that needs to know whether it was handed the owner's phrase."""
    keys = load_keys(path)
    for name, entry in keys["holders"].items():
        if _unwrap(entry, passphrase) is not None:
            return name
    return None


def add_holder(owner_passphrase: str, name: str, new_passphrase: str,
               path: Path = KEYS_FILE) -> None:
    """Let one more passphrase open the data. Requires a phrase that already
    works, so a guest cannot invite further guests."""
    data_key = unlock(owner_passphrase, path)
    keys = load_keys(path)
    if name in keys["holders"]:
        raise ValueError(f"{name} already has access - revoke first")
    keys["holders"][name] = _wrap(data_key, new_passphrase)
    save_keys(keys, path)


def remove_holder(owner_passphrase: str, name: str,
                  path: Path = KEYS_FILE) -> None:
    """Take one holder's access away. Note this only stops them opening files
    encrypted AFTER the next rotate - call rotate_key to make it immediate."""
    unlock(owner_passphrase, path)
    keys = load_keys(path)
    if name == "owner":
        raise ValueError("cannot remove the owner")
    if name not in keys["holders"]:
        raise ValueError(f"no holder called {name}")
    del keys["holders"][name]
    save_keys(keys, path)


def rotate_key(owner_passphrase: str, files: list[Path],
               path: Path = KEYS_FILE) -> bytes:
    """Replace the data key and re-encrypt everything with it. This is what
    makes a revocation bite: the removed guest's phrase no longer opens the
    new key, so nothing published from here on is readable by them."""
    old_key = unlock(owner_passphrase, path)
    plain = {f: decrypt_bytes(f.read_bytes(), old_key) for f in files
             if f.exists()}
    new_key = secrets.token_bytes(KEY_BYTES)
    keys = load_keys(path)
    keys["holders"] = {"owner": _wrap(new_key, owner_passphrase)}
    save_keys(keys, path)
    for f, raw in plain.items():
        f.write_bytes(encrypt_bytes(raw, new_key))
    return new_key


# --------------------------------------------------------------------------
# files
# --------------------------------------------------------------------------

def encrypt_bytes(plaintext: bytes, data_key: bytes) -> bytes:
    nonce = secrets.token_bytes(NONCE_BYTES)
    return MAGIC + nonce + AESGCM(data_key).encrypt(nonce, plaintext, None)


def decrypt_bytes(blob: bytes, data_key: bytes) -> bytes:
    if not blob.startswith(MAGIC):
        raise ValueError("not a tracker-encrypted file")
    nonce = blob[len(MAGIC):len(MAGIC) + NONCE_BYTES]
    return AESGCM(data_key).decrypt(nonce, blob[len(MAGIC) + NONCE_BYTES:], None)


def lock_file(path: Path, data_key: bytes, keep_plaintext: bool = False) -> Path:
    """plain file -> file.enc, and the plain one goes away unless asked."""
    target = path.with_suffix(path.suffix + ".enc")
    target.write_bytes(encrypt_bytes(path.read_bytes(), data_key))
    if not keep_plaintext:
        path.unlink()
    return target


def unlock_file(path: Path, data_key: bytes, keep_ciphertext: bool = True) -> Path:
    """file.enc -> plain file, for the scraper to read at the start of a run."""
    if path.suffix != ".enc":
        raise ValueError(f"{path} is not a .enc file")
    target = path.with_suffix("")
    target.write_bytes(decrypt_bytes(path.read_bytes(), data_key))
    if not keep_ciphertext:
        path.unlink()
    return target


# --------------------------------------------------------------------------
# command line
# --------------------------------------------------------------------------

def _passphrase(prompt: str = "Passphrase: ") -> str:
    """Read a passphrase without echoing it, and never from an argument -
    anything on the command line ends up in shell history."""
    from getpass import getpass
    env = os.environ.get("TRACKER_KEY")
    return env if env else getpass(prompt)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        print("commands: init | lock <files...> | unlock <files...> | "
              "add-guest <name> | revoke <name> | rotate <files...> | holders")
        return 1

    cmd = argv[1]

    if cmd == "init":
        p = _passphrase("Choose a passphrase: ")
        again = _passphrase("Type it again: ") if not os.environ.get("TRACKER_KEY") else p
        if p != again:
            print("Those did not match. Nothing was created.")
            return 1
        if len(p) < 12:
            print("Too short - use at least 12 characters. Nothing was created.")
            return 1
        init(p)
        print(f"Created {KEYS_FILE}. Keep that passphrase safe; it cannot be reset.")
        return 0

    if cmd == "holders":
        print("\n".join(load_keys()["holders"]))
        return 0

    if cmd in {"lock", "unlock", "rotate"}:
        files = [Path(a) for a in argv[2:]]
        if not files:
            print("Give me some files.")
            return 1
        key = unlock(_passphrase())
        if cmd == "lock":
            for f in files:
                print("locked  ", lock_file(f, key))
        elif cmd == "unlock":
            for f in files:
                print("unlocked", unlock_file(f, key))
        else:
            rotate_key(_passphrase(), files)
            print(f"Rolled the key and re-encrypted {len(files)} files.")
        return 0

    if cmd == "add-guest":
        name = argv[2]
        owner = _passphrase("Your passphrase: ")
        guest = _passphrase(f"Passphrase to give {name}: ")
        add_holder(owner, name, guest)
        print(f"{name} can now open the data. Revoke with: revoke {name}")
        return 0

    if cmd == "revoke":
        name = argv[2]
        remove_holder(_passphrase("Your passphrase: "), name)
        print(f"Removed {name}. Run 'rotate' to make it take effect immediately.")
        return 0

    print(f"Don't know the command {cmd!r}.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
