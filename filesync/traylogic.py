"""Logica di stato per l'app di system tray, senza dipendenze grafiche.

Separata da tray.py apposta: questo modulo e' testabile senza un display
(pystray/Tkinter richiedono un ambiente desktop), tray.py invece si limita
a disegnare l'icona/menu/notifiche usando queste funzioni.
"""

from __future__ import annotations

import datetime
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .config import Job, Vault
from .sync import SyncResult, run_job


@dataclass
class JobOutcome:
    job_name: str
    ok: bool
    result: Optional[SyncResult] = None
    error: Optional[str] = None


def run_sync_cycle(jobs: List[Job], dry_run: bool = False) -> List[JobOutcome]:
    """Esegue tutti i job, senza fermarsi al primo errore."""
    outcomes = []
    for job in jobs:
        try:
            result = run_job(job, dry_run=dry_run)
            outcomes.append(JobOutcome(job.name, True, result=result))
        except Exception as exc:  # noqa: BLE001 - un job che fallisce non deve fermare gli altri
            outcomes.append(JobOutcome(job.name, False, error=str(exc)))
    return outcomes


def format_sync_summary(outcomes: List[JobOutcome]) -> Optional[str]:
    """Messaggio da notificare, o None se non c'e' nulla di rilevante da segnalare
    (nessun errore e nessun file trasferito: sync "silenziosa" come atteso)."""
    lines = []
    for o in outcomes:
        if not o.ok:
            lines.append(f"Errore in '{o.job_name}': {o.error}")
        elif o.result and o.result.changed:
            lines.append(f"'{o.job_name}': {len(o.result.copied)} copiati, {len(o.result.archived)} archiviati")

    return "\n".join(lines) if lines else None


def is_workspace_unlocked(vault: Vault) -> bool:
    """Un vault e' considerato 'sbloccato' se la cartella di lavoro esiste e non e' vuota."""
    return os.path.isdir(vault.workspace) and bool(os.listdir(vault.workspace))


@dataclass
class UnlockWarningTracker:
    """Segue da quanto tempo ogni vault e' sbloccato, per ripetere un
    promemoria ogni 'warn_after_minutes' finche' non viene ribloccato."""

    unlocked_since: Dict[str, datetime.datetime] = field(default_factory=dict)
    last_warned: Dict[str, datetime.datetime] = field(default_factory=dict)

    def check(self, vault: Vault, now: Optional[datetime.datetime] = None) -> Optional[str]:
        now = now or datetime.datetime.now()

        if not is_workspace_unlocked(vault):
            self.unlocked_since.pop(vault.name, None)
            self.last_warned.pop(vault.name, None)
            return None

        since = self.unlocked_since.setdefault(vault.name, now)
        elapsed_minutes = (now - since).total_seconds() / 60
        warn_after = max(vault.warn_after_minutes, 1)

        if elapsed_minutes < warn_after:
            return None

        last = self.last_warned.get(vault.name)
        if last is not None and (now - last).total_seconds() / 60 < warn_after:
            return None

        self.last_warned[vault.name] = now
        return (
            f"'{vault.name}' e' sbloccato da oltre {int(elapsed_minutes)} minuti: "
            "chiudi l'editor/TIA Portal e blocca il vault se ti allontani dal PC."
        )
