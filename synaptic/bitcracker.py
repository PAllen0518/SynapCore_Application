"""Wraps the vendored MultiBit checker.

multibit_check.py and the public test wallet live under vendor/, so synaptic
runs without a BitCracker checkout. Does two things:

- enumerate candidates through the checker's own tokenlist parser, so what we
  rank and dedup is exactly what the checker will try (no drift).
- run a recovery by shelling out to the checker and reporting only whether the
  password was found, never the password.

The checker verifies on the CPU (pycryptodome: MD5/AES/base58). synaptic decides
what to check; the fast CUDA tool in BitCracker V2 is separate and not used here,
though generate.py emits tokenlists you can feed to it.

The vendored checker is a point-in-time copy from the BitCracker V2 project
((c) 2026 Paul Allen, GPLv2); see vendor/__init__.py.
"""

from __future__ import annotations

import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_VENDOR_DIR = os.path.join(_HERE, "vendor")
CHECKER = os.path.join(_VENDOR_DIR, "multibit_check.py")
DEFAULT_TEST_WALLET = os.path.join(_VENDOR_DIR, "test-wallets", "multibit-wallet.key")


def _import_checker():
    from .vendor import multibit_check

    return multibit_check


def enumerate_candidates(tokenlist_path: str, delimiter: str | None = None) -> list[str]:
    """Return every base password a tokenlist expands to, via the checker's parser.

    This is the same enumeration multibit_check performs internally, so the
    candidate set synaptic reasons about matches the search exactly.
    """
    mc = _import_checker()
    lines = mc.parse_tokenlist(tokenlist_path, delimiter)
    return list(mc.generate_passwords(lines))


def wallet_salt_hex(wallet_path: str) -> str:
    """Load a MultiBit Classic .key file and return its salt as hex (an id, not a secret)."""
    return load_wallet(wallet_path).salt.hex()


def load_wallet(wallet_path: str):
    """Return a multibit_check.MultiBitWallet for in-process candidate checks."""
    mc = _import_checker()
    return mc.MultiBitWallet.load(wallet_path)


def write_found_password(password: str, cwd: str | None = None) -> str:
    """Write a recovered password to a restricted (0600) file and return its path.

    Mirrors the checker's own routine (owner-only file, never stdout) but writes
    directly to the target directory instead of mutating the process CWD, so it
    is safe to call re-entrantly. synaptic calls this only at the moment of a hit
    and never keeps the plaintext itself.
    """
    directory = cwd or os.getcwd()
    path = os.path.join(directory, "RECOVERED_PASSWORD.txt")
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(password)
    return os.path.abspath(path)


class RunResult:
    def __init__(self, found: bool, checked: int, returncode: int):
        self.found = found
        self.checked = checked
        self.returncode = returncode


def run_checker(
    wallet_path: str, tokenlist_path: str, delimiter: str | None = None, cwd: str | None = None
) -> RunResult:
    """Run multibit_check.py over a tokenlist and report the outcome.

    Returns whether a password was found and how many candidates were checked.
    The recovered password is deliberately not captured here - the checker writes
    it to a restricted RECOVERED_PASSWORD.txt and synaptic never reads it.
    """
    cmd = [sys.executable, CHECKER, "--wallet", wallet_path, "--tokenlist", tokenlist_path]
    if delimiter is not None:
        cmd += ["--delimiter", delimiter]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd or os.getcwd(), check=False)
    checked = _parse_checked(proc.stdout)
    return RunResult(found=proc.returncode == 0, checked=checked, returncode=proc.returncode)


def _parse_checked(stdout: str) -> int:
    """Pull the '<n> checked' count the checker prints on its last progress line."""
    best = 0
    for token in stdout.replace(",", "").split():
        if token.isdigit():
            best = max(best, int(token))
    return best
