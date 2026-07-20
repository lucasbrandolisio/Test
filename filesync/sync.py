"""Sincronizzazione incrementale di cartelle (locale, share di rete, cartelle
condivise VMware, ecc.) con cifratura opzionale dei file in destinazione.

Le cartelle condivise VMware (VMware Shared Folders) compaiono come normali
percorsi del filesystem una volta montate nel guest (es. su Windows guest
"\\\\vmware-host\\Shared Folders\\...", su Linux guest sotto "/mnt/hgfs/...").
Per questo motivo non serve nessuna integrazione speciale: basta puntare
'source' o 'destination' al percorso montato.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from typing import List, Optional

from . import crypto
from .config import Job

logger = logging.getLogger("filesync.sync")

META_SUFFIX = ".meta.json"


@dataclass
class SyncResult:
    copied: List[str] = field(default_factory=list)
    deleted: List[str] = field(default_factory=list)
    skipped: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.copied or self.deleted)


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
) -> SyncResult:
    """Sincronizza source -> destination.

    - Copia i file nuovi o modificati (confronto su dimensione e mtime).
    - Se mirror=True, elimina in destination i file non piu' presenti in source.
    - Se cipher e' fornito (oggetto Fernet, vedi crypto.make_cipher), i file
      vengono cifrati in destinazione con suffisso '.enc' e viene mantenuto
      un piccolo sidecar '.meta.json' con dimensione/mtime originali, usato
      per rilevare le modifiche senza dover decifrare nulla.
    """
    exclude = exclude or []
    result = SyncResult()

    if not os.path.isdir(source):
        raise FileNotFoundError(f"Cartella sorgente non trovata: {source}")

    os.makedirs(destination, exist_ok=True)

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
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    shutil.copy2(src_path, dest_path)
                result.copied.append(rel_path)
            else:
                result.skipped += 1

    if mirror:
        for dirpath, _dirnames, filenames in os.walk(destination):
            for filename in filenames:
                dest_full = os.path.join(dirpath, filename)
                rel_dest = os.path.relpath(dest_full, destination)
                if rel_dest == crypto.SALT_FILENAME:
                    continue
                if rel_dest.replace(os.sep, "/") not in {p.replace(os.sep, "/") for p in expected_dest_files}:
                    result.deleted.append(rel_dest)
                    if not dry_run:
                        os.remove(dest_full)

        if not dry_run:
            _prune_empty_dirs(destination)

    return result


def _prune_empty_dirs(root: str) -> None:
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        if dirpath == root:
            continue
        if not dirnames and not filenames:
            os.rmdir(dirpath)


def run_job(job: Job, dry_run: bool = False) -> SyncResult:
    cipher = None
    if job.encrypt:
        password = job.resolve_password()
        os.makedirs(job.destination, exist_ok=True)
        cipher = crypto.make_cipher(password, job.destination)

    logger.info("Sync job '%s': %s -> %s", job.name, job.source, job.destination)
    result = sync_directory(
        source=job.source,
        destination=job.destination,
        mirror=job.mirror,
        exclude=job.exclude,
        cipher=cipher,
        dry_run=dry_run,
    )
    logger.info(
        "Job '%s': %d copiati, %d eliminati, %d invariati",
        job.name, len(result.copied), len(result.deleted), result.skipped,
    )
    return result
