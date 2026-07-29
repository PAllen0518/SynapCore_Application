"""bitcracker adapter: restricted-file write (no CWD mutation) and enumeration."""

import os
import stat

from synaptic import bitcracker


def test_write_found_password_writes_restricted_file(tmp_path):
    cwd_before = os.getcwd()
    path = bitcracker.write_found_password("btcr-test-password", cwd=str(tmp_path))
    # CWD is not mutated (no os.chdir).
    assert os.getcwd() == cwd_before
    written = tmp_path / "RECOVERED_PASSWORD.txt"
    assert written.exists()
    assert written.read_text() == "btcr-test-password"
    assert os.path.abspath(path) == str(written)
    if os.name == "posix":  # 0600 perms only meaningful on POSIX
        assert stat.S_IMODE(os.stat(written).st_mode) == 0o600


def test_default_test_wallet_exists():
    assert os.path.exists(bitcracker.DEFAULT_TEST_WALLET)
