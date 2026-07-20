"""'Envelope' di cifratura per un job di backup.

Ogni cartella di destinazione cifrata ha una singola DEK (Data Encryption
Key) usata per cifrare tutti i file. La DEK viene salvata cifrata (wrappata)
in fino a tre modi indipendenti dentro '<destinazione>/.filesync_keys/envelope.json':

  - "user":     wrappata con la password personale di chi usa il job.
  - "recovery": wrappata con una passphrase casuale, mandata una volta per
                email a chi ha configurato il job (auto-recupero).
  - "master":   wrappata con la chiave pubblica RSA dell'amministratore:
                solo chi possiede la chiave privata (+ la sua passphrase)
                puo' usarla, indipendentemente dalla password dell'utente.

Qualunque dei tre percorsi sblocchi la DEK, la si puo' usare per cifrare/
decifrare i file del backup. Recuperare l'accesso (password dimenticata,
utente non piu' in azienda, ecc.) significa semplicemente ri-wrappare la
DEK con una nuova password: i file gia' cifrati NON vanno ritoccati.
"""

from __future__ import annotations

import datetime
import fnmatch
import json
import os
from typing import Optional

from cryptography.fernet import Fernet

from . import crypto, keys

ENVELOPE_DIR = ".filesync_keys"
ENVELOPE_FILE = "envelope.json"
RESERVED_DIRS = {ENVELOPE_DIR}


def envelope_path(dest_dir: str) -> str:
    return os.path.join(dest_dir, ENVELOPE_DIR, ENVELOPE_FILE)


def envelope_exists(dest_dir: str) -> bool:
    return os.path.exists(envelope_path(dest_dir))


def load_envelope(dest_dir: str) -> dict:
    with open(envelope_path(dest_dir), "r", encoding="utf-8") as f:
        return json.load(f)


def save_envelope(dest_dir: str, envelope: dict) -> None:
    path = envelope_path(dest_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(envelope, f, indent=2)


def create_envelope(
    dest_dir: str,
    project_name: str,
    user_password: str,
    master_public_key_path: Optional[str] = None,
    recovery_key: Optional[str] = None,
) -> bytes:
    """Crea un nuovo envelope con una DEK nuova. Ritorna la DEK generata."""
    dek = crypto.generate_dek()
    wraps = {"user": crypto.pbkdf2_wrap_dek(dek, user_password)}

    if recovery_key:
        wraps["recovery"] = crypto.pbkdf2_wrap_dek(dek, recovery_key)

    if master_public_key_path:
        public_key = keys.load_public_key(master_public_key_path)
        wraps["master"] = {"method": "rsa-oaep-sha256", "token": keys.rsa_wrap(dek, public_key)}

    envelope = {
        "version": 1,
        "project": project_name,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "wraps": wraps,
    }
    save_envelope(dest_dir, envelope)
    return dek


def unwrap_dek_with_password(dest_dir: str, password: str) -> bytes:
    """Prova a sbloccare la DEK con la password personale o la chiave di recovery."""
    envelope = load_envelope(dest_dir)
    for role in ("user", "recovery"):
        wrap = envelope["wraps"].get(role)
        if not wrap:
            continue
        try:
            return crypto.pbkdf2_unwrap_dek(wrap, password)
        except crypto.DecryptionError:
            continue
    raise crypto.DecryptionError(
        "Password non valida (provata sia come password personale che come chiave di recovery)."
    )

def unwrap_dek_with_recovery_key(dest_dir: str, recovery_key: str) -> bytes:
    envelope = load_envelope(dest_dir)
    wrap = envelope["wraps"].get("recovery")
    if not wrap:
        raise crypto.DecryptionError("Questo progetto non ha una chiave di recovery configurata.")
    return crypto.pbkdf2_unwrap_dek(wrap, recovery_key)


def unwrap_dek_with_master_key(dest_dir: str, master_private_key_path: str, passphrase: str) -> bytes:
    envelope = load_envelope(dest_dir)
    wrap = envelope["wraps"].get("master")
    if not wrap:
        raise crypto.DecryptionError("Questo progetto non ha una chiave master configurata.")
    private_key = keys.load_private_key(master_private_key_path, passphrase)
    return keys.rsa_unwrap(wrap["token"], private_key)


def open_cipher_with_password(dest_dir: str, password: str) -> Fernet:
    return Fernet(unwrap_dek_with_password(dest_dir, password))


def reset_user_password(dest_dir: str, dek: bytes, new_password: str) -> None:
    """Ri-wrappa la DEK esistente con una nuova password personale.

    Non tocca i file gia' cifrati: la DEK resta la stessa, cambia solo
    come viene protetta.
    """
    envelope = load_envelope(dest_dir)
    envelope["wraps"]["user"] = crypto.pbkdf2_wrap_dek(dek, new_password)
    save_envelope(dest_dir, envelope)


def rotate_recovery_key(dest_dir: str, dek: bytes) -> str:
    """Genera una nuova chiave di recovery e la salva nell'envelope. Ritorna la chiave in chiaro (da mandare via email)."""
    recovery_key = keys.generate_recovery_key()
    envelope = load_envelope(dest_dir)
    envelope["wraps"]["recovery"] = crypto.pbkdf2_wrap_dek(dek, recovery_key)
    save_envelope(dest_dir, envelope)
    return recovery_key


def is_reserved_path(rel_path: str) -> bool:
    top = rel_path.replace(os.sep, "/").split("/")[0]
    return top in RESERVED_DIRS or top == crypto.SALT_FILENAME


def decrypt_all(dest_dir: str, output_dir: str, cipher: Fernet, exclude: Optional[list] = None) -> int:
    """Decifra tutti i file *.enc di un envelope in output_dir, per il ripristino completo di un backup."""
    exclude = exclude or []
    count = 0
    for dirpath, dirnames, filenames in os.walk(dest_dir):
        rel_dir = os.path.relpath(dirpath, dest_dir)
        dirnames[:] = [d for d in dirnames if not is_reserved_path(os.path.normpath(os.path.join(rel_dir, d)))]
        for filename in filenames:
            if not filename.endswith(crypto.ENCRYPTED_SUFFIX):
                continue
            rel_path = os.path.normpath(os.path.join(rel_dir, filename) if rel_dir != "." else filename)
            if is_reserved_path(rel_path) or any(fnmatch.fnmatch(rel_path, p) for p in exclude):
                continue

            src_path = os.path.join(dest_dir, rel_path)
            dst_rel = rel_path[: -len(crypto.ENCRYPTED_SUFFIX)]
            dst_path = os.path.join(output_dir, dst_rel)
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)

            with open(src_path, "rb") as f:
                token = f.read()
            plaintext = crypto.decrypt_bytes(cipher, token)
            with open(dst_path, "wb") as f:
                f.write(plaintext)

            st = os.stat(src_path)
            os.utime(dst_path, (st.st_atime, st.st_mtime))
            count += 1

    return count
