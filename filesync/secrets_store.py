"""Password salvate nel gestore di credenziali del sistema operativo
(Windows Credential Manager / macOS Keychain / Secret Service su Linux)
tramite la libreria 'keyring', cosi' la GUI di configurazione non deve mai
chiedere a chi la usa di editare config.yaml o impostare variabili
d'ambiente a mano.

Import di 'keyring' fatto solo dentro le funzioni (lazy): il resto di
filesync (CLI, sync via password_env) non la richiede come dipendenza.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("filesync.secrets_store")

SERVICE = "filesync"


def _keyring():
    import keyring  # noqa: PLC0415

    return keyring


def set_password(key: str, password: str) -> None:
    try:
        _keyring().set_password(SERVICE, key, password)
    except ImportError as exc:
        raise RuntimeError(
            "Manca il pacchetto 'keyring' per salvare le password in modo sicuro. Installa con:\n"
            "    pip install keyring"
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"Impossibile salvare la password nel gestore credenziali del sistema: {exc}"
        ) from exc


def get_password(key: str) -> Optional[str]:
    try:
        return _keyring().get_password(SERVICE, key)
    except Exception:  # noqa: BLE001
        logger.debug("Gestore credenziali non disponibile o nessuna password salvata per '%s'.", key)
        return None


def delete_password(key: str) -> None:
    try:
        _keyring().delete_password(SERVICE, key)
    except Exception:  # noqa: BLE001
        logger.debug("Impossibile cancellare la password per '%s' (forse non era mai stata salvata).", key)
