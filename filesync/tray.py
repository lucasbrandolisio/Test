"""Icona nella system tray: sync automatica in background, blocco/sblocco
vault dal menu, notifiche su errori e su vault rimasti sbloccati troppo a
lungo.

Richiede pacchetti extra non necessari al resto di filesync (import fatto
solo quando serve, cosi' la CLI normale non li richiede):

    pip install pystray Pillow

Su Linux minimale potrebbe servire anche il pacchetto di sistema
'python3-tk' (per le finestre di richiesta password) e un ambiente
desktop con supporto system tray (es. su GNOME serve l'estensione
AppIndicator/KStatusNotifierItem).

NOTA: questo modulo e' stato scritto e testato via CLI/unit test, ma non
e' stato verificato visivamente (icona/menu/notifiche) in un ambiente
senza display grafico: va provato su una macchina Windows/desktop vera.
"""

from __future__ import annotations

import logging
import threading
from typing import List, Optional

from . import vault as vault_module
from .config import Vault, load_jobs, load_vaults
from .envelope import unwrap_dek_with_password
from .traylogic import (
    UnlockWarningTracker,
    format_sync_summary,
    is_workspace_unlocked,
    run_sync_cycle,
)

logger = logging.getLogger("filesync.tray")

STATE_COLORS = {
    "ok": (46, 160, 67, 255),
    "warn": (219, 154, 4, 255),
    "error": (207, 34, 46, 255),
}


def _import_ui_deps():
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise SystemExit(
            "Manca Pillow, richiesto dalla system tray. Installa con:\n"
            "    pip install pystray Pillow"
        ) from exc

    try:
        import pystray
    except ImportError as exc:
        raise SystemExit(
            "Manca pystray, richiesto dalla system tray. Installa con:\n"
            "    pip install pystray Pillow"
        ) from exc
    except Exception as exc:  # noqa: BLE001 - su Linux pystray si connette al display gia' all'import
        raise SystemExit(
            "Impossibile inizializzare la system tray: "
            f"{exc}\n"
            "Su Linux serve un ambiente desktop con un display grafico attivo "
            "(non funziona in una sessione senza interfaccia grafica/SSH pura); "
            "su GNOME potrebbe servire anche l'estensione AppIndicator/KStatusNotifierItem."
        ) from exc

    return pystray, Image, ImageDraw


def _ask_password(prompt: str) -> Optional[str]:
    try:
        import tkinter as tk
        from tkinter import simpledialog
    except ImportError:
        logger.error("tkinter non disponibile: impossibile chiedere la password dalla GUI.")
        return None

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    password = simpledialog.askstring("filesync", prompt, show="*", parent=root)
    root.destroy()
    return password


class TrayApp:
    def __init__(self, config_path: str, interval: int = 300):
        self.config_path = config_path
        self.interval = interval
        self._stop = threading.Event()
        self._tracker = UnlockWarningTracker()
        self._icon = None
        self._pystray = None
        self._Image = None
        self._ImageDraw = None
        self._state = "ok"

    def _make_image(self, color):
        size = 64
        image = self._Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = self._ImageDraw.Draw(image)
        draw.ellipse((4, 4, size - 4, size - 4), fill=color)
        return image

    def _set_state(self, state: str):
        if state == self._state:
            return
        self._state = state
        if self._icon is not None:
            self._icon.icon = self._make_image(STATE_COLORS[state])

    def _notify(self, message: str, title: str = "filesync"):
        logger.info("%s: %s", title, message)
        if self._icon is None:
            return
        try:
            self._icon.notify(message, title)
        except NotImplementedError:
            logger.debug("Notifiche di sistema non supportate su questo backend.")
        except Exception:  # noqa: BLE001
            logger.exception("Impossibile mostrare la notifica di sistema.")

    def _safe_load_jobs(self) -> list:
        try:
            return load_jobs(self.config_path)
        except Exception:
            logger.exception("Impossibile leggere i job da '%s'.", self.config_path)
            return []

    def _safe_load_vaults(self) -> List[Vault]:
        try:
            return load_vaults(self.config_path)
        except Exception:
            logger.exception("Impossibile leggere i vault da '%s'.", self.config_path)
            return []

    def sync_now(self, icon=None, item=None):
        outcomes = run_sync_cycle(self._safe_load_jobs())
        self._set_state("error" if any(not o.ok for o in outcomes) else "ok")
        summary = format_sync_summary(outcomes)
        if summary:
            self._notify(summary, title="filesync - sincronizzazione")

    def toggle_vault(self, entry: Vault, icon=None, item=None):
        if is_workspace_unlocked(entry):
            password = entry.resolve_password() or _ask_password(f"Password per bloccare '{entry.name}':")
            if not password:
                return
            try:
                count = vault_module.lock(entry.workspace, entry.vault, password)
                self._notify(f"'{entry.name}' bloccato ({count} file cifrati). Cartella di lavoro cancellata.")
            except Exception as exc:  # noqa: BLE001
                self._notify(f"Errore bloccando '{entry.name}': {exc}", title="filesync - errore")
        else:
            password = entry.resolve_password() or _ask_password(f"Password per sbloccare '{entry.name}':")
            if not password:
                return
            try:
                dek = unwrap_dek_with_password(entry.vault, password)
                count = vault_module.unlock(entry.vault, entry.workspace, dek)
                self._notify(f"'{entry.name}' sbloccato ({count} file). Ricordati di bloccarlo quando hai finito.")
            except Exception as exc:  # noqa: BLE001
                self._notify(f"Errore sbloccando '{entry.name}': {exc}", title="filesync - errore")

    def _background_loop(self):
        while not self._stop.is_set():
            try:
                self.sync_now()
            except Exception:
                logger.exception("Errore durante il ciclo di sync automatico.")

            for entry in self._safe_load_vaults():
                message = self._tracker.check(entry)
                if message:
                    self._notify(message, title="filesync - promemoria")

            self._stop.wait(self.interval)

    def _menu_items(self):
        yield self._pystray.MenuItem("Sincronizza ora", self.sync_now)
        vaults = self._safe_load_vaults()
        if vaults:
            yield self._pystray.Menu.SEPARATOR
            for entry in vaults:
                label = f"Blocca '{entry.name}'" if is_workspace_unlocked(entry) else f"Sblocca '{entry.name}'"
                yield self._pystray.MenuItem(label, lambda icon, item, e=entry: self.toggle_vault(e))
        yield self._pystray.Menu.SEPARATOR
        yield self._pystray.MenuItem("Esci", self._quit)

    def _quit(self, icon, item):
        self._stop.set()
        icon.stop()

    def run(self):
        pystray, Image, ImageDraw = _import_ui_deps()
        self._pystray, self._Image, self._ImageDraw = pystray, Image, ImageDraw

        self._icon = pystray.Icon(
            "filesync",
            self._make_image(STATE_COLORS["ok"]),
            "filesync",
            menu=pystray.Menu(self._menu_items),
        )

        thread = threading.Thread(target=self._background_loop, daemon=True)
        thread.start()

        self._icon.run()
        self._stop.set()
