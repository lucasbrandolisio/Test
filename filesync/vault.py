"""Vault locale cifrato per la cartella di lavoro (workspace).

A differenza di 'protect' (che lascia i file in chiaro e si affida ai
permessi del sistema operativo), il vault offre protezione reale: quando
'lock' viene eseguito, ogni file del workspace viene cifrato con nome
casuale (nessuna traccia dei nomi/struttura originali) dentro il vault, e
la cartella di lavoro in chiaro viene CANCELLATA solo dopo aver verificato
che ogni blob scritto ridecifra esattamente all'originale.

Il risultato e' che, a vault chiuso, chi apre quella cartella non trova
niente da leggere: ne' contenuto ne' nomi di file riconoscibili. Il prezzo
e' che devi chiudere l'IDE/TIA Portal prima di bloccare, e riaprire con
'unlock' (password/chiave) prima di poter tornare a lavorarci.

Il vault, essendo gia' cifrato, puo' essere usato direttamente come
'source' di un job di sync (senza 'encrypt: true') per finire sul server:
i file sono gia' ciphertext, non serve cifrarli una seconda volta.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
from typing import Optional

from cryptography.fernet import Fernet

from . import crypto, envelope

MANIFEST_FILE = "manifest.enc"
BLOB_SUFFIX = ".blob"


def _iter_workspace_files(workspace: str):
    for dirpath, _dirnames, filenames in os.walk(workspace):
        for filename in filenames:
            full = os.path.join(dirpath, filename)
            yield os.path.relpath(full, workspace), full


def _existing_blob_ids(vault_dir: str) -> set:
    if not os.path.isdir(vault_dir):
        return set()
    return {
        name[: -len(BLOB_SUFFIX)]
        for name in os.listdir(vault_dir)
        if name.endswith(BLOB_SUFFIX)
    }


def lock(
    workspace: str,
    vault_dir: str,
    password: str,
    master_public_key_path: Optional[str] = None,
    recovery_key: Optional[str] = None,
) -> int:
    """Cifra tutto il contenuto di workspace dentro vault_dir e cancella workspace.

    Nomi file e struttura delle cartelle vengono nascosti (sostituiti da
    identificativi casuali + un manifest cifrato). Non cancella NULLA dal
    workspace finche' non ha verificato che ogni blob scritto ridecifra
    esattamente all'originale.

    Ritorna il numero di file bloccati.
    """
    if not os.path.isdir(workspace):
        raise FileNotFoundError(f"Cartella di lavoro non trovata: {workspace}")

    os.makedirs(vault_dir, exist_ok=True)
    if envelope.envelope_exists(vault_dir):
        dek = envelope.unwrap_dek_with_password(vault_dir, password)
    else:
        dek = envelope.create_envelope(
            vault_dir,
            os.path.basename(os.path.normpath(workspace)),
            password,
            master_public_key_path=master_public_key_path,
            recovery_key=recovery_key,
        )
    cipher = Fernet(dek)

    entries = list(_iter_workspace_files(workspace))
    manifest = {}
    checks = []

    for rel_path, full_path in entries:
        with open(full_path, "rb") as f:
            plaintext = f.read()
        blob_id = secrets.token_hex(16)
        token = crypto.encrypt_bytes(cipher, plaintext)
        blob_path = os.path.join(vault_dir, blob_id + BLOB_SUFFIX)
        with open(blob_path, "wb") as f:
            f.write(token)
        manifest[blob_id] = rel_path
        checks.append((blob_path, hashlib.sha256(plaintext).hexdigest()))

    manifest_token = crypto.encrypt_bytes(cipher, json.dumps(manifest).encode("utf-8"))
    manifest_path = os.path.join(vault_dir, MANIFEST_FILE)
    with open(manifest_path, "wb") as f:
        f.write(manifest_token)

    # Verifica ogni blob PRIMA di cancellare qualunque cosa: se anche un solo
    # file non ridecifra correttamente, il workspace in chiaro non viene toccato.
    for blob_path, expected_sha in checks:
        with open(blob_path, "rb") as f:
            token = f.read()
        actual = crypto.decrypt_bytes(cipher, token)
        if hashlib.sha256(actual).hexdigest() != expected_sha:
            raise RuntimeError(
                f"Verifica fallita per un file cifrato in '{vault_dir}': "
                "il workspace NON e' stato cancellato per sicurezza. Riprova."
            )

    # Rimuove i blob di una sessione precedente non piu' referenziati dal nuovo manifest.
    for old_id in _existing_blob_ids(vault_dir) - set(manifest.keys()):
        os.remove(os.path.join(vault_dir, old_id + BLOB_SUFFIX))

    shutil.rmtree(workspace)
    return len(entries)


def unlock(vault_dir: str, workspace: str, dek: bytes) -> int:
    """Decifra il vault dentro workspace (che deve non esistere o essere vuota)."""
    cipher = Fernet(dek)
    manifest_path = os.path.join(vault_dir, MANIFEST_FILE)
    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"Nessun contenuto bloccato trovato in '{vault_dir}'.")

    with open(manifest_path, "rb") as f:
        manifest = json.loads(crypto.decrypt_bytes(cipher, f.read()).decode("utf-8"))

    if os.path.exists(workspace) and os.listdir(workspace):
        raise FileExistsError(
            f"'{workspace}' esiste gia' e non e' vuota: per sicurezza non viene sovrascritta. "
            "Spostala o rimuovila prima di sbloccare."
        )

    count = 0
    for blob_id, rel_path in manifest.items():
        blob_path = os.path.join(vault_dir, blob_id + BLOB_SUFFIX)
        with open(blob_path, "rb") as f:
            token = f.read()
        plaintext = crypto.decrypt_bytes(cipher, token)
        dst_path = os.path.join(workspace, rel_path)
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        with open(dst_path, "wb") as f:
            f.write(plaintext)
        count += 1

    return count
