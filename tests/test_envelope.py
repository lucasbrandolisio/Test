import pytest

from filesync import envelope, keys
from filesync.crypto import DecryptionError, decrypt_bytes, encrypt_bytes


def test_user_password_round_trip(tmp_path):
    dest = tmp_path / "dest"
    dek = envelope.create_envelope(str(dest), "Progetto", user_password="password-utente")

    unwrapped = envelope.unwrap_dek_with_password(str(dest), "password-utente")
    assert unwrapped == dek


def test_wrong_password_fails(tmp_path):
    dest = tmp_path / "dest"
    envelope.create_envelope(str(dest), "Progetto", user_password="password-corretta")

    with pytest.raises(DecryptionError):
        envelope.unwrap_dek_with_password(str(dest), "password-sbagliata")


def test_recovery_key_unlocks_same_dek(tmp_path):
    dest = tmp_path / "dest"
    dek = envelope.create_envelope(
        str(dest), "Progetto", user_password="password-utente", recovery_key="CHIAVE-RECOVERY-123"
    )

    via_recovery = envelope.unwrap_dek_with_recovery_key(str(dest), "CHIAVE-RECOVERY-123")
    assert via_recovery == dek

    # la chiave di recovery funziona anche passata al percorso "password"
    via_password_path = envelope.unwrap_dek_with_password(str(dest), "CHIAVE-RECOVERY-123")
    assert via_password_path == dek


def test_master_key_unlocks_same_dek_independently_of_user_password(tmp_path):
    dest = tmp_path / "dest"
    private_pem, public_pem = keys.generate_master_keypair("passphrase-admin")
    pub_path = tmp_path / "master_public.pem"
    priv_path = tmp_path / "master_private.pem"
    pub_path.write_bytes(public_pem)
    priv_path.write_bytes(private_pem)

    dek = envelope.create_envelope(
        str(dest), "Progetto", user_password="password-utente-dimenticata", master_public_key_path=str(pub_path)
    )

    via_master = envelope.unwrap_dek_with_master_key(str(dest), str(priv_path), "passphrase-admin")
    assert via_master == dek


def test_reset_user_password_preserves_dek_and_encrypted_files(tmp_path):
    """Il punto chiave del recovery: resettare la password NON tocca i file gia' cifrati."""
    dest = tmp_path / "dest"
    dek = envelope.create_envelope(
        str(dest), "Progetto", user_password="vecchia-password", recovery_key="CHIAVE-XYZ"
    )

    from cryptography.fernet import Fernet
    cipher = Fernet(dek)
    token = encrypt_bytes(cipher, b"codice sorgente PLC")

    # utente dimentica la password, si auto-recupera con la chiave ricevuta via email
    recovered_dek = envelope.unwrap_dek_with_recovery_key(str(dest), "CHIAVE-XYZ")
    envelope.reset_user_password(str(dest), recovered_dek, "nuova-password")

    # la vecchia password non funziona piu'...
    with pytest.raises(DecryptionError):
        envelope.unwrap_dek_with_password(str(dest), "vecchia-password")

    # ...ma la nuova sblocca la STESSA dek, quindi i file gia' cifrati restano leggibili
    new_dek = envelope.unwrap_dek_with_password(str(dest), "nuova-password")
    assert new_dek == dek
    assert decrypt_bytes(Fernet(new_dek), token) == b"codice sorgente PLC"


def test_decrypt_all_restores_full_backup(tmp_path):
    from cryptography.fernet import Fernet

    dest = tmp_path / "dest"
    output = tmp_path / "restored"
    dek = envelope.create_envelope(str(dest), "Progetto", user_password="pw")
    cipher = Fernet(dek)

    (dest / "sub").mkdir(parents=True)
    (dest / "main.st.enc").write_bytes(encrypt_bytes(cipher, b"PROGRAM Main; END_PROGRAM"))
    (dest / "sub" / "lib.st.enc").write_bytes(encrypt_bytes(cipher, b"FUNCTION_BLOCK fb"))

    count = envelope.decrypt_all(str(dest), str(output), cipher)

    assert count == 2
    assert (output / "main.st").read_bytes() == b"PROGRAM Main; END_PROGRAM"
    assert (output / "sub" / "lib.st").read_bytes() == b"FUNCTION_BLOCK fb"
