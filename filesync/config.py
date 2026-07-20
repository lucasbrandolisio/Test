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
    master_public_key: Optional[str] = None
    recovery_email: Optional[str] = None

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


@dataclass
class Vault:
    name: str
    workspace: str
    vault: str
    password_env: Optional[str] = None
    warn_after_minutes: int = 30

    def resolve_password(self) -> Optional[str]:
        """Legge la password dalla variabile d'ambiente, se configurata.

        Puo' essere None: in quel caso chi usa il vault (es. la tray app)
        dovra' chiederla interattivamente.
        """
        if not self.password_env:
            return None
        return os.environ.get(self.password_env) or None


def _read_yaml(config_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_jobs(config_path: str) -> List[Job]:
    """Carica i job di sync da 'jobs:'. Ritorna una lista vuota se la chiave manca
    (un config.yaml puo' contenere solo 'vaults:', vedi load_vaults)."""
    raw = _read_yaml(config_path)
    jobs_raw = raw.get("jobs", [])

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
                    master_public_key=entry.get("master_public_key"),
                    recovery_email=entry.get("recovery_email"),
                )
            )
        except KeyError as exc:
            raise ValueError(f"Job malformato in '{config_path}': manca il campo {exc}.") from exc

    return jobs


def load_vaults(config_path: str) -> List[Vault]:
    """Carica i vault locali da 'vaults:'. Ritorna una lista vuota se la chiave manca."""
    raw = _read_yaml(config_path)
    vaults_raw = raw.get("vaults", [])

    vaults = []
    for entry in vaults_raw:
        try:
            vaults.append(
                Vault(
                    name=entry["name"],
                    workspace=entry["workspace"],
                    vault=entry["vault"],
                    password_env=entry.get("password_env"),
                    warn_after_minutes=entry.get("warn_after_minutes", 30),
                )
            )
        except KeyError as exc:
            raise ValueError(f"Vault malformato in '{config_path}': manca il campo {exc}.") from exc

    return vaults
