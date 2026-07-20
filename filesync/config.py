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
    keep_versions: int = 5

    def resolve_password(self) -> Optional[str]:
        """Trova la password di cifratura: prima in 'password_env' (uso
        avanzato/script), altrimenti nel gestore credenziali del sistema
        (dove la salva la GUI di configurazione). La password non va mai
        scritta in chiaro nel file di configurazione.
        """
        if not self.encrypt:
            return None
        if self.password_env:
            password = os.environ.get(self.password_env)
            if password:
                return password
        from . import secrets_store  # import lazy: non serve alla CLI base

        password = secrets_store.get_password(f"job:{self.name}")
        if password:
            return password

        env_hint = f"la variabile d'ambiente '{self.password_env}' o " if self.password_env else ""
        raise ValueError(
            f"Job '{self.name}': nessuna password trovata (controllati {env_hint}"
            "il gestore credenziali del sistema). Configurala di nuovo con 'filesync setup'."
        )


@dataclass
class Vault:
    name: str
    workspace: str
    vault: str
    password_env: Optional[str] = None
    warn_after_minutes: int = 30

    def resolve_password(self) -> Optional[str]:
        """Trova la password: prima 'password_env' (uso avanzato), poi il
        gestore credenziali del sistema (dove la salva la GUI). Puo'
        ritornare None: in quel caso chi usa il vault (CLI o tray) la
        chiedera' interattivamente.
        """
        if self.password_env:
            password = os.environ.get(self.password_env)
            if password:
                return password

        from . import secrets_store  # import lazy: non serve alla CLI base

        return secrets_store.get_password(f"vault:{self.name}")


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
                    keep_versions=entry.get("keep_versions", 5),
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


def _job_to_dict(job: Job) -> dict:
    entry = {"name": job.name, "source": job.source, "destination": job.destination}
    if job.mirror:
        entry["mirror"] = job.mirror
    if job.exclude:
        entry["exclude"] = job.exclude
    if job.encrypt:
        entry["encrypt"] = job.encrypt
    if job.password_env:
        entry["password_env"] = job.password_env
    if job.master_public_key:
        entry["master_public_key"] = job.master_public_key
    if job.recovery_email:
        entry["recovery_email"] = job.recovery_email
    if job.keep_versions != 5:
        entry["keep_versions"] = job.keep_versions
    return entry


def _vault_to_dict(vault: Vault) -> dict:
    entry = {"name": vault.name, "workspace": vault.workspace, "vault": vault.vault}
    if vault.password_env:
        entry["password_env"] = vault.password_env
    if vault.warn_after_minutes != 30:
        entry["warn_after_minutes"] = vault.warn_after_minutes
    return entry


def save_jobs(config_path: str, jobs: List[Job]) -> None:
    """Sovrascrive la sezione 'jobs:' del config, preservando 'vaults:' se presente."""
    raw = _read_yaml(config_path) if os.path.exists(config_path) else {}
    raw["jobs"] = [_job_to_dict(j) for j in jobs]
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, allow_unicode=True, sort_keys=False)


def save_vaults(config_path: str, vaults: List[Vault]) -> None:
    """Sovrascrive la sezione 'vaults:' del config, preservando 'jobs:' se presente."""
    raw = _read_yaml(config_path) if os.path.exists(config_path) else {}
    raw["vaults"] = [_vault_to_dict(v) for v in vaults]
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, allow_unicode=True, sort_keys=False)
