import pytest

from filesync import keys
from filesync.crypto import DecryptionError


def test_master_keypair_round_trip(tmp_path):
    private_pem, public_pem = keys.generate_master_keypair("passphrase-master")

    private_path = tmp_path / "master_private.pem"
    public_path = tmp_path / "master_public.pem"
    private_path.write_bytes(private_pem)
    public_path.write_bytes(public_pem)

    public_key = keys.load_public_key(str(public_path))
    dek = b"0123456789abcdef0123456789abcdef"[:32].ljust(32, b"0")
    wrapped = keys.rsa_wrap(dek, public_key)

    private_key = keys.load_private_key(str(private_path), "passphrase-master")
    unwrapped = keys.rsa_unwrap(wrapped, private_key)

    assert unwrapped == dek


def test_master_private_key_wrong_passphrase(tmp_path):
    private_pem, _ = keys.generate_master_keypair("passphrase-corretta")
    private_path = tmp_path / "master_private.pem"
    private_path.write_bytes(private_pem)

    with pytest.raises(DecryptionError):
        keys.load_private_key(str(private_path), "passphrase-sbagliata")


def test_recovery_key_is_readable_and_random():
    k1 = keys.generate_recovery_key()
    k2 = keys.generate_recovery_key()
    assert k1 != k2
    assert "-" in k1
    assert all(part for part in k1.split("-"))
