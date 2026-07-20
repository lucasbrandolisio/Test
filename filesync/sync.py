"""Sincronizzazione incrementale di cartelle (locale, share di rete, cartelle
condivise VMware, ecc.) con cifratura opzionale dei file in destinazione.

Le cartelle condivise VMware (VMware Shared Folders) compaiono come normali
percorsi del filesystem una volta montate nel guest (es. su Windows guest
"\\\\vmware-host\\Shared Folders\\...", su Linux guest sotto "/mnt/hgfs/...").
Per questo motivo non serve nessuna integrazione speciale: basta puntare
'source' o 'destination' al percorso montato.
"""

from __future__ import annotations

import datetime
import fnmatch
import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from typing import List, Optional

from cryptography.fernet import Fernet

from . import crypto, envelope, keys, mailer
from .config import Job

logger = logging.getLogger("filesync.sync")

META_SUFFIX = ".meta.json"
TRASH_DIR = ".filesync_trash"
VERSIONS_DIR = ".filesync_versions"

# Cartelle "tecniche" dentro la destinazione che la sync non deve mai
# considerare file dell'utente ne' toccare durante la pulizia mirror.
RESERVED_DEST_DIRS = {TRASH_DIR, VERSIONS_DIR, envelope.ENVELOPE_DIR}


@dataclass
class SyncResult:
    copied: List[str] = field(default_factory=list)
    archived: List[str] = field(default_factory=list)
    skipped: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.copied or self.archived)


def _is_excluded(rel_path: str, patterns: List[str]) -> bool:
    parts = rel_path.replace(os.sep, "/").split("/")
    for pattern in patterns:
        if fnmatch.fnmatch(rel_path.replace(os.sep, "/"), pattern):
            return True
        if any(fnmatch.fnmatch(part, pattern) for part in parts):
            return True
    return False


def _iter_source_files(source_dir: str, exclude: List[str]):
    for dirpath, dirnames, filenames in os.walk(source_dir):
        rel_dir = os.path.relpath(dirpath, source_dir)
        dirnames[:] = [
            d for d in dirnames
            if not _is_excluded(os.path.normpath(os.path.join(rel_dir, d)), exclude)
        ]
        for filename in filenames:
            rel_path = os.path.normpath(
                os.path.join(rel_dir, filename) if rel_dir != "." else filename
            )
            if _is_excluded(rel_path, exclude):
                continue
            yield rel_path


def sync_directory(
    source: str,
    destination: str,
    mirror: bool = False,
    exclude: Optional[List[str]] = None,
    cipher=None,
    dry_run: bool = False,
    keep_versions: int = 0,
) -> SyncResult:
    """Sincronizza source -> destination.

    - Copia i file nuovi o modificati (confronto su dimensione e mtime).
    - Se mirror=True, i file non piu' presenti in source vengono SPOSTATI
      (mai cancellati) in '<destination>/.filesync_trash/<timestamp>/...',
      cosi' anche in caso di rinomina/cancellazione accidentale nulla va
      mai perso dal backup. Con mirror=False (default) i file rimossi dalla
      sorgente restano semplicemente dove sono in destinazione.
    - Se cipher e' fornito (oggetto Fernet), i file vengono cifrati in
      destinazione con suffisso '.enc' e viene mantenuto un piccolo sidecar
      '.meta.json' con dimensione/mtime originali, usato per rilevare le
      modifiche senza dover decifrare nulla.
    - Se keep_versions > 0, prima di SOVRASCRIVERE un file esistente in
      destinazione (perche' e' cambiato in sorgente) la versione precedente
      viene salvata in '<destination>/.filesync_versions/<percorso>/<timestamp>',
      tenendo solo le ultime 'keep_versions' per file. Protegge dal caso in
      cui un ransomware cifri/corrompa i file in locale: la sync propaga
      comunque la versione compromessa, ma quelle buone precedenti restano
      recuperabili con 'filesync versions'/'restore-version'.
    """
    exclude = exclude or []
    result = SyncResult()

    if not os.path.isdir(source):
        raise FileNotFoundError(f"Cartella sorgente non trovata: {source}")

    os.makedirs(destination, exist_ok=True)
    run_ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")

    expected_dest_files = set()

    for rel_path in _iter_source_files(source, exclude):
        src_path = os.path.join(source, rel_path)
        st = os.stat(src_path)

        if cipher is not None:
            dest_rel = rel_path + crypto.ENCRYPTED_SUFFIX
            dest_path = os.path.join(destination, dest_rel)
            meta_path = dest_path + META_SUFFIX
            expected_dest_files.add(dest_rel)
            expected_dest_files.add(dest_rel + META_SUFFIX)

            needs_copy = True
            if os.path.exists(dest_path) and os.path.exists(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    if meta.get("size") == st.st_size and meta.get("mtime") == st.st_mtime:
                        needs_copy = False
                except (OSError, json.JSONDecodeError):
                    needs_copy = True

            if needs_copy:
                if not dry_run:
                    if keep_versions > 0 and os.path.exists(dest_path):
                        _save_version(destination, dest_rel, dest_path, run_ts)
                        _prune_versions(destination, dest_rel, keep_versions)
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    with open(src_path, "rb") as f:
                        plaintext = f.read()
                    token = crypto.encrypt_bytes(cipher, plaintext)
                    with open(dest_path, "wb") as f:
                        f.write(token)
                    with open(meta_path, "w", encoding="utf-8") as f:
                        json.dump({"size": st.st_size, "mtime": st.st_mtime, "rel_path": rel_path}, f)
                    os.utime(dest_path, (st.st_atime, st.st_mtime))
                result.copied.append(rel_path)
            else:
                result.skipped += 1
        else:
            dest_path = os.path.join(destination, rel_path)
            expected_dest_files.add(rel_path)

            needs_copy = True
            if os.path.exists(dest_path):
                dst_st = os.stat(dest_path)
                if dst_st.st_size == st.st_size and int(dst_st.st_mtime) == int(st.st_mtime):
                    needs_copy = False

            if needs_copy:
                if not dry_run:
                    if keep_versions > 0 and os.path.exists(dest_path):
                        _save_version(destination, rel_path, dest_path, run_ts)
                        _prune_versions(destination, rel_path, keep_versions)
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    shutil.copy2(src_path, dest_path)
                result.copied.append(rel_path)
            else:
                result.skipped += 1

    if mirror:
        expected_norm = {p.replace(os.sep, "/") for p in expected_dest_files}

        for dirpath, dirnames, filenames in os.walk(destination):
            rel_dir = os.path.relpath(dirpath, destination)
            if rel_dir == ".":
                dirnames[:] = [d for d in dirnames if d not in RESERVED_DEST_DIRS]
            for filename in filenames:
                if rel_dir == "." and filename == crypto.SALT_FILENAME:
                    continue
                dest_full = os.path.join(dirpath, filename)
                rel_dest = os.path.relpath(dest_full, destination)
                if rel_dest.replace(os.sep, "/") not in expected_norm:
                    result.archived.append(rel_dest)
                    if not dry_run:
                        _move_to_trash(destination, rel_dest, run_ts)

        if not dry_run:
            _prune_empty_dirs(destination)

    return result


def _move_to_trash(destination: str, rel_path: str, run_ts: str) -> None:
    src = os.path.join(destination, rel_path)
    dst = os.path.join(destination, TRASH_DIR, run_ts, rel_path)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(src, dst)


def _version_dir(destination: str, rel_path: str) -> str:
    return os.path.join(destination, VERSIONS_DIR, rel_path)


def _save_version(destination: str, rel_path: str, current_path: str, run_ts: str) -> None:
    """Salva una copia del file ATTUALE (prima di sovrascriverlo) come nuova versione storica."""
    version_dir = _version_dir(destination, rel_path)
    os.makedirs(version_dir, exist_ok=True)
    shutil.copy2(current_path, os.path.join(version_dir, run_ts))


def _prune_versions(destination: str, rel_path: str, keep: int) -> None:
    version_dir = _version_dir(destination, rel_path)
    if not os.path.isdir(version_dir):
        return
    versions = sorted(os.listdir(version_dir))  # i nomi sono timestamp "AAAAMMGG-hhmmss", ordinabili come stringhe
    for old in versions[:-keep] if keep > 0 else versions:
        os.remove(os.path.join(version_dir, old))
    if not os.listdir(version_dir):
        os.rmdir(version_dir)


def list_versions(destination: str, rel_path: str) -> List[str]:
    """Ritorna i timestamp delle versioni storiche disponibili per un file (piu' vecchia -> piu' recente)."""
    version_dir = _version_dir(destination, rel_path)
    if not os.path.isdir(version_dir):
        return []
    return sorted(os.listdir(version_dir))


def restore_version(destination: str, rel_path: str, version_ts: str, output_path: str, cipher=None) -> None:
    """Ripristina una versione storica di un file in output_path.

    Se il file era cifrato (rel_path finisce per '.enc'), passa il cipher
    (vedi envelope.py) per decifrarla; altrimenti None per una copia diretta.
    """
    version_path = os.path.join(_version_dir(destination, rel_path), version_ts)
    if not os.path.exists(version_path):
        raise FileNotFoundError(f"Versione '{version_ts}' non trovata per '{rel_path}' in '{destination}'.")

    with open(version_path, "rb") as f:
        data = f.read()
    if cipher is not None:
        data = crypto.decrypt_bytes(cipher, data)

    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(data)


def _prune_empty_dirs(root: str) -> None:
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        if dirpath == root:
            continue
        rel_dir = os.path.relpath(dirpath, root)
        if rel_dir.replace(os.sep, "/").split("/")[0] in RESERVED_DEST_DIRS:
            continue
        if not dirnames and not filenames:
            os.rmdir(dirpath)


def _get_or_create_cipher(job: Job):
    """Ottiene il cipher del job leggendo l'envelope esistente, oppure ne crea uno nuovo al primo utilizzo."""
    password = job.resolve_password()
    os.makedirs(job.destination, exist_ok=True)

    if envelope.envelope_exists(job.destination):
        return envelope.open_cipher_with_password(job.destination, password)

    logger.info(
        "Job '%s': nessuna configurazione di cifratura trovata in '%s', la creo ora.",
        job.name, job.destination,
    )
    recovery_key = keys.generate_recovery_key() if job.recovery_email else None
    dek = envelope.create_envelope(
        job.destination,
        job.name,
        password,
        master_public_key_path=job.master_public_key,
        recovery_key=recovery_key,
    )

    if recovery_key and job.recovery_email:
        try:
            mailer.send_recovery_email(job.recovery_email, job.name, job.destination, recovery_key)
            logger.info("Job '%s': email con la chiave di recovery inviata a %s.", job.name, job.recovery_email)
        except Exception as exc:  # noqa: BLE001 - non deve bloccare la sync, ma va segnalato forte
            logger.error(
                "Job '%s': invio email di recovery fallito (%s). CONSERVA SUBITO questa chiave "
                "in un posto sicuro, non potra' essere recuperata di nuovo: %s",
                job.name, exc, recovery_key,
            )

    return Fernet(dek)


def run_job(job: Job, dry_run: bool = False) -> SyncResult:
    cipher = _get_or_create_cipher(job) if job.encrypt else None

    logger.info("Sync job '%s': %s -> %s", job.name, job.source, job.destination)
    result = sync_directory(
        source=job.source,
        destination=job.destination,
        mirror=job.mirror,
        exclude=job.exclude,
        cipher=cipher,
        dry_run=dry_run,
        keep_versions=job.keep_versions,
    )
    logger.info(
        "Job '%s': %d copiati, %d archiviati nel cestino, %d invariati",
        job.name, len(result.copied), len(result.archived), result.skipped,
    )
    return result
