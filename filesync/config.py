"""Caricamento della configurazione dei job di sincronizzazione da YAML."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

import yaml


@dataclass
class Job:
    name: str
    source: str
    destination: str
    mirror: bool = False
    exclude: List[str] = field(default_factory=list)
    encrypt: bool = False
    password_env: Optional[str] = None

    def resolve_password(self) -> Optional[str]:
        """Legge la password di cifratura da una variabile d'ambiente.

        La password non va mai scritta in chiaro nel file di configurazione.
        """
        if not self.encrypt:
            return None
        if not self.password_env:
            raise ValueError(
                f"Job '{self.name}': 'encrypt: true' richiede 'password_env' "
                "(nome della variabile d'ambiente che contiene la password)."
            )
        password = os.environ.get(self.password_env)
        if not password:
            raise ValueError(
                f"Job '{self.name}': variabile d'ambiente '{self.password_env}' "
                "non impostata o vuota."
            )
        return password


def load_jobs(config_path: str) -> List[Job]:
    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    jobs_raw = raw.get("jobs", [])
    if not jobs_raw:
        raise ValueError(f"Nessun job trovato in '{config_path}' (chiave 'jobs' mancante o vuota).")

    jobs = []
    for entry in jobs_raw:
        try:
            jobs.append(
                Job(
                    name=entry["name"],
                    source=entry["source"],
                    destination=entry["destination"],
                    mirror=entry.get("mirror", False),
                    exclude=entry.get("exclude", []) or [],
                    encrypt=entry.get("encrypt", False),
                    password_env=entry.get("password_env"),
                )
            )
        except KeyError as exc:
            raise ValueError(f"Job malformato in '{config_path}': manca il campo {exc}.") from exc

    return jobs
