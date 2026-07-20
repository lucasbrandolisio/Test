import os

import pytest

from filesync import crypto


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)


def test_encrypt_decrypt_round_trip(tmp_path):
    src = tmp_path / "src"
    enc = tmp_path / "enc"
    dec = tmp_path / "dec"
    _write(src / "main.py", b"print('progetto PLC segreto')")
    _write(src / "sub" / "lib.py", b"def f(): pass")

    count = crypto.encrypt_folder(str(src), str(enc), "password123")
    assert count == 2

    # I sorgenti non devono essere leggibili in chiaro nella cartella cifrata
    for f in (enc / "main.py.enc", enc / "sub" / "lib.py.enc"):
        assert f.exists()
        assert b"PLC" not in f.read_bytes()

    count = crypto.decrypt_folder(str(enc), str(dec), "password123")
    assert count == 2
    assert (dec / "main.py").read_bytes() == b"print('progetto PLC segreto')"
    assert (dec / "sub" / "lib.py").read_bytes() == b"def f(): pass"


def test_wrong_password_fails(tmp_path):
    src = tmp_path / "src"
    enc = tmp_path / "enc"
    dec = tmp_path / "dec"
    _write(src / "a.txt", b"segreto")

    crypto.encrypt_folder(str(src), str(enc), "password-corretta")

    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt_folder(str(enc), str(dec), "password-sbagliata")


def test_salt_is_stable_across_calls(tmp_path):
    root = tmp_path / "root"
    salt1 = crypto.load_or_create_salt(str(root))
    salt2 = crypto.load_or_create_salt(str(root))
    assert salt1 == salt2
