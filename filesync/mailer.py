"""Invio email (es. chiave di recovery) via SMTP autenticato.

Configurato di default per Office 365 / Outlook (smtp.office365.com:587,
STARTTLS). Le credenziali NON vanno mai messe nel config.yaml: solo
variabili d'ambiente.

Nota: molti tenant Microsoft 365 disabilitano l'SMTP AUTH "basic" di
default (specie con MFA attiva). Se l'invio fallisce con un errore di
autenticazione, chiedi al tuo amministratore IT di abilitare "Authenticated
SMTP" per la casella usata (Exchange Admin Center > destinatari > casella >
Gestisci app email) e, se l'MFA e' attiva, genera una App Password dedicata
da usare come FILESYNC_SMTP_PASSWORD invece della password normale.
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage


class MailConfigError(Exception):
    """Configurazione SMTP mancante o incompleta."""


def _smtp_settings() -> dict:
    host = os.environ.get("FILESYNC_SMTP_HOST", "smtp.office365.com")
    port = int(os.environ.get("FILESYNC_SMTP_PORT", "587"))
    user = os.environ.get("FILESYNC_SMTP_USER")
    password = os.environ.get("FILESYNC_SMTP_PASSWORD")
    sender = os.environ.get("FILESYNC_SMTP_FROM", user)

    if not user or not password:
        raise MailConfigError(
            "Configurazione SMTP mancante: imposta le variabili d'ambiente "
            "FILESYNC_SMTP_USER e FILESYNC_SMTP_PASSWORD (per Office 365: il "
            "tuo indirizzo e una password applicativa se l'MFA e' attiva)."
        )

    return {"host": host, "port": port, "user": user, "password": password, "sender": sender}


def send_email(to_addr: str, subject: str, body: str) -> None:
    settings = _smtp_settings()

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings["sender"]
    msg["To"] = to_addr
    msg.set_content(body)

    with smtplib.SMTP(settings["host"], settings["port"], timeout=30) as smtp:
        smtp.starttls()
        smtp.login(settings["user"], settings["password"])
        smtp.send_message(msg)


RECOVERY_EMAIL_SUBJECT = "[filesync] Chiave di recovery per '{project}'"

RECOVERY_EMAIL_BODY = """\
E' stata generata una chiave di recovery per il backup cifrato del progetto '{project}'.

Chiave di recovery:
{recovery_key}

Conservala in un posto sicuro (es. un password manager), separata dal
computer che usi normalmente. Se dimentichi la tua password personale,
puoi usare questa chiave per riottenere l'accesso senza perdere i file:

    python -m filesync recover "{destination}" --recovery-key "LA-CHIAVE" --new-password "nuova-password"

Se perdi anche questa chiave, l'amministratore del backup potra' comunque
recuperare l'accesso con la chiave master.
"""


def send_recovery_email(to_addr: str, project: str, destination: str, recovery_key: str) -> None:
    send_email(
        to_addr,
        RECOVERY_EMAIL_SUBJECT.format(project=project),
        RECOVERY_EMAIL_BODY.format(project=project, destination=destination, recovery_key=recovery_key),
    )
