import os

import pytest

from filesync import envelope, keys, vault
from filesync.crypto import DecryptionError


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def test_lock_encrypts_and_deletes_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    vault_dir = tmp_path / "vault"
    _write(workspace / "main.py", "print('segreto')")
    _write(workspace / "sub" / "lib.py", "x = 1")

    count = vault.lock(str(workspace), str(vault_dir), "password-vault")

    assert count == 2
    assert not workspace.exists()  # cancellata per davvero

    # nel vault non ci sono ne' nomi originali ne' contenuto leggibile
    blob_files = list(vault_dir.glob("*.blob"))
    assert len(blob_files) == 2
    for blob in blob_files:
        assert b"segreto" not in blob.read_bytes()
        assert "main" not in blob.name and "lib" not in blob.name


def test_unlock_restores_original_files(tmp_path):
    workspace = tmp_path / "workspace"
    vault_dir = tmp_path / "vault"
    restored = tmp_path / "restored"
    _write(workspace / "main.py", "print('segreto PLC')")
    _write(workspace / "sub" / "lib.py", "x = 1")

    dek = envelope.create_envelope(str(vault_dir), "Progetto", "password-vault")
    from cryptography.fernet import Fernet
    Fernet(dek)  # sanity: la dek e' valida per Fernet

    vault.lock(str(workspace), str(vault_dir), "password-vault")

    dek_again = envelope.unwrap_dek_with_password(str(vault_dir), "password-vault")
    count = vault.unlock(str(vault_dir), str(restored), dek_again)

    assert count == 2
    assert (restored / "main.py").read_text() == "print('segreto PLC')"
    assert (restored / "sub" / "lib.py").read_text() == "x = 1"


def test_unlock_wrong_password_fails(tmp_path):
    workspace = tmp_path / "workspace"
    vault_dir = tmp_path / "vault"
    _write(workspace / "main.py", "codice")
    vault.lock(str(workspace), str(vault_dir), "password-corretta")

    with pytest.raises(DecryptionError):
        envelope.unwrap_dek_with_password(str(vault_dir), "password-sbagliata")


def test_unlock_refuses_to_overwrite_nonempty_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    vault_dir = tmp_path / "vault"
    _write(workspace / "main.py", "codice")
    vault.lock(str(workspace), str(vault_dir), "pw")
    dek = envelope.unwrap_dek_with_password(str(vault_dir), "pw")

    _write(workspace / "altro.txt", "gia' presente")
    with pytest.raises(FileExistsError):
        vault.unlock(str(vault_dir), str(workspace), dek)


def test_admin_can_unlock_with_master_key_if_password_forgotten(tmp_path):
    workspace = tmp_path / "workspace"
    vault_dir = tmp_path / "vault"
    restored = tmp_path / "restored"
    _write(workspace / "main.py", "codice riservato del collega")

    private_pem, public_pem = keys.generate_master_keypair("passphrase-admin")
    pub_path = tmp_path / "master_public.pem"
    priv_path = tmp_path / "master_private.pem"
    pub_path.write_bytes(public_pem)
    priv_path.write_bytes(private_pem)

    vault.lock(str(workspace), str(vault_dir), "password-dimenticata", master_public_key_path=str(pub_path))

    dek = envelope.unwrap_dek_with_master_key(str(vault_dir), str(priv_path), "passphrase-admin")
    count = vault.unlock(str(vault_dir), str(restored), dek)

    assert count == 1
    assert (restored / "main.py").read_text() == "codice riservato del collega"


def test_relock_replaces_previous_snapshot(tmp_path):
    workspace = tmp_path / "workspace"
    vault_dir = tmp_path / "vault"
    _write(workspace / "a.txt", "uno")
    vault.lock(str(workspace), str(vault_dir), "pw")

    _write(workspace / "a.txt", "due")
    _write(workspace / "b.txt", "tre")
    vault.lock(str(workspace), str(vault_dir), "pw")

    dek = envelope.unwrap_dek_with_password(str(vault_dir), "pw")
    restored = tmp_path / "restored"
    count = vault.unlock(str(vault_dir), str(restored), dek)

    assert count == 2
    assert (restored / "a.txt").read_text() == "due"
    assert (restored / "b.txt").read_text() == "tre"
