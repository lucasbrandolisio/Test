"""Blocco locale di una cartella tramite permessi del sistema operativo.

Non e' cifratura: impedisce che ALTRI ACCOUNT dello stesso PC/VM possano
leggere o scrivere nella cartella, senza l'attrito di dover "sbloccarla"
ogni volta che apri un editor/IDE (i file restano normali file in chiaro,
utilizzabili subito). Un amministratore/root della macchina puo' comunque
aggirare questa protezione: per quel livello servirebbe cifrare anche la
cartella locale, ma allora andrebbe "smontata/rimontata" ad ogni utilizzo,
rendendo scomodo lavorarci con un IDE — per questo qui si usa il controllo
accessi del sistema operativo, che e' la soluzione standard per proteggere
una cartella di lavoro attiva da altri utenti locali.

ATTENZIONE: su alcune cartelle condivise VMware (mount vmhgfs-fuse) i
permessi POSIX non sono realmente applicati dall'host Windows: in quel
caso 'protect' potrebbe non avere alcun effetto reale. Verificalo prima
di fidartene su una cartella condivisa.
"""

from __future__ import annotations

import json
import os
import platform
import stat
import subprocess

STATE_DIR = ".filesync_protect"
STATE_FILE = "original_perms.json"

DIR_MODE = 0o700
FILE_MODE = 0o600


def is_windows() -> bool:
    return platform.system() == "Windows"


def _state_path(folder: str) -> str:
    return os.path.join(folder, STATE_DIR, STATE_FILE)


def protect_posix(folder: str) -> int:
    """Imposta permessi 'solo proprietario' su tutta la cartella. Ritorna il numero di file modificati."""
    original = {}
    count = 0
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if d != STATE_DIR]
        rel_dir = os.path.relpath(dirpath, folder)
        st = os.stat(dirpath)
        original[rel_dir] = stat.S_IMODE(st.st_mode)
        os.chmod(dirpath, DIR_MODE)

        for filename in filenames:
            path = os.path.join(dirpath, filename)
            rel = os.path.relpath(path, folder)
            st = os.stat(path)
            original[rel] = stat.S_IMODE(st.st_mode)
            os.chmod(path, FILE_MODE)
            count += 1

    state_dir = os.path.join(folder, STATE_DIR)
    os.makedirs(state_dir, exist_ok=True)
    with open(_state_path(folder), "w", encoding="utf-8") as f:
        json.dump(original, f, indent=2)
    os.chmod(state_dir, DIR_MODE)
    return count


def unprotect_posix(folder: str) -> int:
    """Ripristina i permessi originali salvati da protect_posix. Ritorna il numero di elementi ripristinati."""
    path = _state_path(folder)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Nessuno stato salvato in '{folder}': non risulta protetta da filesync "
            "(o lo stato e' stato cancellato)."
        )
    with open(path, "r", encoding="utf-8") as f:
        original = json.load(f)

    count = 0
    for rel, mode in original.items():
        full = os.path.join(folder, rel)
        if os.path.exists(full):
            os.chmod(full, mode)
            count += 1

    os.remove(path)
    try:
        os.rmdir(os.path.join(folder, STATE_DIR))
    except OSError:
        pass
    return count


def protect_windows(folder: str) -> None:
    user = os.environ.get("USERNAME") or os.environ.get("USER")
    if not user:
        raise RuntimeError("Impossibile determinare l'utente corrente (variabile USERNAME non impostata).")
    subprocess.run(
        ["icacls", folder, "/inheritance:r", "/grant:r", f"{user}:(OI)(CI)F", "/T", "/Q"],
        check=True,
    )


def unprotect_windows(folder: str) -> None:
    subprocess.run(["icacls", folder, "/reset", "/T", "/Q"], check=True)


def protect(folder: str) -> None:
    if is_windows():
        protect_windows(folder)
    else:
        protect_posix(folder)


def unprotect(folder: str) -> None:
    if is_windows():
        unprotect_windows(folder)
    else:
        unprotect_posix(folder)
