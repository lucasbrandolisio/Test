import os

import pytest

from filesync import envelope, keys, mailer
from filesync.config import Job
from filesync.sync import run_job


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def test_run_job_creates_envelope_on_first_run(tmp_path, monkeypatch):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _write(src / "main.st", "PROGRAM Main; END_PROGRAM")

    monkeypatch.setenv("TEST_PW", "password-progetto")
    job = Job(name="PLC1", source=str(src), destination=str(dst), encrypt=True, password_env="TEST_PW")

    run_job(job)

    assert envelope.envelope_exists(str(dst))
    assert (dst / "main.st.enc").exists()

    # una seconda sync riusa lo stesso envelope invece di ricrearne uno nuovo
    envelope_before = envelope.load_envelope(str(dst))
    result = run_job(job)
    envelope_after = envelope.load_envelope(str(dst))
    assert envelope_before == envelope_after
    assert result.skipped == 1


def test_run_job_sends_recovery_email_once(tmp_path, monkeypatch):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _write(src / "main.st", "codice")

    monkeypatch.setenv("TEST_PW", "password-progetto")
    sent = []
    monkeypatch.setattr(mailer, "send_recovery_email", lambda *a, **k: sent.append(a))

    job = Job(
        name="PLC1",
        source=str(src),
        destination=str(dst),
        encrypt=True,
        password_env="TEST_PW",
        recovery_email="collega@azienda.it",
    )

    run_job(job)
    assert len(sent) == 1
    assert sent[0][0] == "collega@azienda.it"

    run_job(job)  # secondo run: l'envelope esiste gia', niente nuova email
    assert len(sent) == 1


def test_run_job_email_failure_does_not_break_sync(tmp_path, monkeypatch):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _write(src / "main.st", "codice")

    monkeypatch.setenv("TEST_PW", "password-progetto")

    def _boom(*a, **k):
        raise RuntimeError("SMTP non raggiungibile")

    monkeypatch.setattr(mailer, "send_recovery_email", _boom)

    job = Job(
        name="PLC1",
        source=str(src),
        destination=str(dst),
        encrypt=True,
        password_env="TEST_PW",
        recovery_email="collega@azienda.it",
    )

    result = run_job(job)  # non deve sollevare eccezioni
    assert result.copied == ["main.st"]
    assert envelope.envelope_exists(str(dst))


def test_admin_recovers_after_colleague_forgets_password(tmp_path, monkeypatch):
    """Simula lo scenario chiave: un collega perde la password E la chiave di
    recovery (es. ha lasciato l'azienda), l'amministratore recupera comunque
    l'accesso con la chiave master, senza mai aver saputo la password del collega."""
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _write(src / "main.st", "codice riservato")

    private_pem, public_pem = keys.generate_master_keypair("passphrase-solo-admin")
    pub_path = tmp_path / "master_public.pem"
    priv_path = tmp_path / "master_private.pem"
    pub_path.write_bytes(public_pem)
    priv_path.write_bytes(private_pem)

    monkeypatch.setenv("TEST_PW", "password-che-il-collega-dimentichera")
    job = Job(
        name="PLC1",
        source=str(src),
        destination=str(dst),
        encrypt=True,
        password_env="TEST_PW",
        master_public_key=str(pub_path),
    )
    run_job(job)

    dek = envelope.unwrap_dek_with_master_key(str(dst), str(priv_path), "passphrase-solo-admin")
    envelope.reset_user_password(str(dst), dek, "password-nuova-assegnata-dall-admin")

    # da questo momento la vecchia password del collega non funziona piu'...
    from filesync.crypto import DecryptionError
    with pytest.raises(DecryptionError):
        envelope.unwrap_dek_with_password(str(dst), "password-che-il-collega-dimentichera")

    # ...ma i file restano leggibili con la nuova password, senza aver perso nulla
    output = tmp_path / "restored"
    from cryptography.fernet import Fernet
    new_dek = envelope.unwrap_dek_with_password(str(dst), "password-nuova-assegnata-dall-admin")
    count = envelope.decrypt_all(str(dst), str(output), Fernet(new_dek))
    assert count == 1
    assert (output / "main.st").read_text() == "codice riservato"
