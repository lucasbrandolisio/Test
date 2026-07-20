"""Finestra di configurazione visuale: aggiungere/rimuovere progetti
scegliendo le cartelle con un selettore, invece di editare config.yaml a
mano. Pensata per essere usabile da un collega senza esperienza tecnica.

Usa solo Tkinter (incluso nell'installer ufficiale di Python su Windows e
macOS; su Linux minimale serve il pacchetto di sistema 'python3-tk') e
'keyring' per salvare le password nel gestore di credenziali del sistema
operativo invece che nel file di configurazione.

NOTA: scritta e controllata a livello di sintassi/logica, ma non e' stata
verificata visivamente in questo ambiente di sviluppo (nessun display
grafico disponibile). Vedi anche tray.py per la stessa nota.
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Callable, Optional

from . import secrets_store
from .config import Job, Vault, load_jobs, load_vaults, save_jobs, save_vaults


class AddVaultDialog(tk.Toplevel):
    """Finestra 'Aggiungi vault locale' (protezione cartella con lock/unlock)."""

    def __init__(self, parent: tk.Misc, on_saved: Callable[[Vault], None]):
        super().__init__(parent)
        self.title("Aggiungi vault locale")
        self.resizable(False, False)
        self.on_saved = on_saved

        self.name_var = tk.StringVar()
        self.workspace_var = tk.StringVar()
        self.vault_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.confirm_var = tk.StringVar()

        pad = {"padx": 8, "pady": 4}
        tk.Label(self, text="Protegge una cartella locale: quando la blocchi, i file\n"
                             "vengono cifrati (nomi compresi) e la cartella in chiaro cancellata.",
                 justify="left").grid(row=0, column=0, columnspan=3, sticky="w", **pad)

        tk.Label(self, text="Nome progetto:").grid(row=1, column=0, sticky="w", **pad)
        tk.Entry(self, textvariable=self.name_var, width=42).grid(row=1, column=1, columnspan=2, **pad)

        tk.Label(self, text="Cartella di lavoro:").grid(row=2, column=0, sticky="w", **pad)
        tk.Entry(self, textvariable=self.workspace_var, width=42).grid(row=2, column=1, **pad)
        tk.Button(self, text="Sfoglia...", command=self._browse_workspace).grid(row=2, column=2, **pad)

        tk.Label(self, text="Cartella vault (cifrata):").grid(row=3, column=0, sticky="w", **pad)
        tk.Entry(self, textvariable=self.vault_var, width=42).grid(row=3, column=1, **pad)
        tk.Button(self, text="Sfoglia...", command=self._browse_vault).grid(row=3, column=2, **pad)

        tk.Label(self, text="Password:").grid(row=4, column=0, sticky="w", **pad)
        tk.Entry(self, textvariable=self.password_var, show="*", width=42).grid(row=4, column=1, columnspan=2, **pad)

        tk.Label(self, text="Conferma password:").grid(row=5, column=0, sticky="w", **pad)
        tk.Entry(self, textvariable=self.confirm_var, show="*", width=42).grid(row=5, column=1, columnspan=2, **pad)

        tk.Button(self, text="Salva", command=self._save).grid(row=6, column=1, sticky="e", **pad)
        tk.Button(self, text="Annulla", command=self.destroy).grid(row=6, column=2, **pad)

        self.grab_set()

    def _browse_workspace(self):
        path = filedialog.askdirectory(title="Scegli la cartella di lavoro da proteggere", parent=self)
        if path:
            self.workspace_var.set(path)
            if not self.vault_var.get():
                self.vault_var.set(path.rstrip("/\\") + ".vault")

    def _browse_vault(self):
        path = filedialog.askdirectory(title="Scegli (o crea) la cartella vault", parent=self)
        if path:
            self.vault_var.set(path)

    def _save(self):
        name = self.name_var.get().strip()
        workspace = self.workspace_var.get().strip()
        vault_path = self.vault_var.get().strip()
        password = self.password_var.get()
        confirm = self.confirm_var.get()

        if not name or not workspace or not vault_path:
            messagebox.showerror("filesync", "Nome, cartella di lavoro e cartella vault sono obbligatori.", parent=self)
            return
        if not password:
            messagebox.showerror("filesync", "Inserisci una password.", parent=self)
            return
        if password != confirm:
            messagebox.showerror("filesync", "Le password non coincidono.", parent=self)
            return

        try:
            secrets_store.set_password(f"vault:{name}", password)
        except RuntimeError as exc:
            messagebox.showerror("filesync", str(exc), parent=self)
            return

        self.on_saved(Vault(name=name, workspace=workspace, vault=vault_path))
        messagebox.showinfo("filesync", f"Vault '{name}' aggiunto. Bloccalo dal menu quando ti allontani dal PC.", parent=self.master)
        self.destroy()


class AddJobDialog(tk.Toplevel):
    """Finestra 'Aggiungi backup verso il server'."""

    def __init__(self, parent: tk.Misc, on_saved: Callable[[Job], None]):
        super().__init__(parent)
        self.title("Aggiungi backup verso il server")
        self.resizable(False, False)
        self.on_saved = on_saved

        self.name_var = tk.StringVar()
        self.source_var = tk.StringVar()
        self.destination_var = tk.StringVar()
        self.mirror_var = tk.BooleanVar(value=False)
        self.encrypt_var = tk.BooleanVar(value=True)
        self.password_var = tk.StringVar()
        self.confirm_var = tk.StringVar()
        self.recovery_email_var = tk.StringVar()

        pad = {"padx": 8, "pady": 4}
        tk.Label(self, text="Nome progetto:").grid(row=0, column=0, sticky="w", **pad)
        tk.Entry(self, textvariable=self.name_var, width=42).grid(row=0, column=1, columnspan=2, **pad)

        tk.Label(self, text="Cartella sorgente (locale):").grid(row=1, column=0, sticky="w", **pad)
        tk.Entry(self, textvariable=self.source_var, width=42).grid(row=1, column=1, **pad)
        tk.Button(self, text="Sfoglia...", command=self._browse_source).grid(row=1, column=2, **pad)

        tk.Label(self, text="Cartella destinazione (server):").grid(row=2, column=0, sticky="w", **pad)
        tk.Entry(self, textvariable=self.destination_var, width=42).grid(row=2, column=1, **pad)
        tk.Button(self, text="Sfoglia...", command=self._browse_destination).grid(row=2, column=2, **pad)

        tk.Checkbutton(
            self, text="Elimina dal backup i file rimossi dalla sorgente (mirror, sconsigliato)",
            variable=self.mirror_var,
        ).grid(row=3, column=0, columnspan=3, sticky="w", **pad)

        tk.Checkbutton(self, text="Cifra prima di mandarla al server", variable=self.encrypt_var,
                        command=self._toggle_password_fields).grid(row=4, column=0, columnspan=3, sticky="w", **pad)

        self.password_label = tk.Label(self, text="Password:")
        self.password_label.grid(row=5, column=0, sticky="w", **pad)
        self.password_entry = tk.Entry(self, textvariable=self.password_var, show="*", width=42)
        self.password_entry.grid(row=5, column=1, columnspan=2, **pad)

        self.confirm_label = tk.Label(self, text="Conferma password:")
        self.confirm_label.grid(row=6, column=0, sticky="w", **pad)
        self.confirm_entry = tk.Entry(self, textvariable=self.confirm_var, show="*", width=42)
        self.confirm_entry.grid(row=6, column=1, columnspan=2, **pad)

        tk.Label(self, text="Email per recupero password (opzionale):").grid(row=7, column=0, sticky="w", **pad)
        tk.Entry(self, textvariable=self.recovery_email_var, width=42).grid(row=7, column=1, columnspan=2, **pad)

        tk.Button(self, text="Salva", command=self._save).grid(row=8, column=1, sticky="e", **pad)
        tk.Button(self, text="Annulla", command=self.destroy).grid(row=8, column=2, **pad)

        self.grab_set()

    def _toggle_password_fields(self):
        state = "normal" if self.encrypt_var.get() else "disabled"
        for widget in (self.password_label, self.password_entry, self.confirm_label, self.confirm_entry):
            widget.configure(state=state)

    def _browse_source(self):
        path = filedialog.askdirectory(title="Scegli la cartella sorgente", parent=self)
        if path:
            self.source_var.set(path)

    def _browse_destination(self):
        path = filedialog.askdirectory(title="Scegli la cartella di destinazione sul server", parent=self)
        if path:
            self.destination_var.set(path)

    def _save(self):
        name = self.name_var.get().strip()
        source = self.source_var.get().strip()
        destination = self.destination_var.get().strip()

        if not name or not source or not destination:
            messagebox.showerror("filesync", "Nome, cartella sorgente e destinazione sono obbligatori.", parent=self)
            return

        encrypt = self.encrypt_var.get()
        if encrypt:
            password = self.password_var.get()
            confirm = self.confirm_var.get()
            if not password:
                messagebox.showerror("filesync", "Inserisci una password (oppure disattiva 'Cifra').", parent=self)
                return
            if password != confirm:
                messagebox.showerror("filesync", "Le password non coincidono.", parent=self)
                return
            try:
                secrets_store.set_password(f"job:{name}", password)
            except RuntimeError as exc:
                messagebox.showerror("filesync", str(exc), parent=self)
                return

        job = Job(
            name=name,
            source=source,
            destination=destination,
            mirror=self.mirror_var.get(),
            encrypt=encrypt,
            recovery_email=self.recovery_email_var.get().strip() or None,
        )
        self.on_saved(job)
        messagebox.showinfo("filesync", f"Backup '{name}' aggiunto.", parent=self.master)
        self.destroy()


def open_manage_window(config_path: str, on_change: Optional[Callable[[], None]] = None) -> None:
    """Apre la finestra di gestione progetti (bloccante finche' non viene chiusa)."""
    root = tk.Tk()
    root.title("filesync - Gestione progetti")

    listbox = tk.Listbox(root, width=70, height=10)
    listbox.grid(row=0, column=0, columnspan=3, padx=8, pady=8)

    entries: list = []

    def refresh():
        listbox.delete(0, tk.END)
        entries.clear()
        for j in load_jobs(config_path):
            cifrato = " [cifrato]" if j.encrypt else ""
            listbox.insert(tk.END, f"[backup server] {j.name}{cifrato}  {j.source} -> {j.destination}")
            entries.append(("job", j))
        for v in load_vaults(config_path):
            listbox.insert(tk.END, f"[vault locale]  {v.name}  {v.workspace}")
            entries.append(("vault", v))
        if not entries:
            listbox.insert(tk.END, "(nessun progetto configurato: usa i pulsanti sotto per aggiungerne uno)")

    def remove_selected():
        selection = listbox.curselection()
        if not selection or not entries:
            return
        kind, obj = entries[selection[0]]
        if not messagebox.askyesno(
            "filesync",
            f"Rimuovere '{obj.name}' dalla configurazione?\n\n"
            "La cartella e i suoi file NON vengono toccati, solo la voce di configurazione.",
            parent=root,
        ):
            return
        if kind == "job":
            save_jobs(config_path, [j for j in load_jobs(config_path) if j.name != obj.name])
            secrets_store.delete_password(f"job:{obj.name}")
        else:
            save_vaults(config_path, [v for v in load_vaults(config_path) if v.name != obj.name])
            secrets_store.delete_password(f"vault:{obj.name}")
        refresh()
        if on_change:
            on_change()

    def add_vault():
        def _on_saved(vault_entry: Vault):
            vaults = load_vaults(config_path)
            vaults.append(vault_entry)
            save_vaults(config_path, vaults)
            refresh()
            if on_change:
                on_change()

        AddVaultDialog(root, _on_saved)

    def add_job():
        def _on_saved(job: Job):
            jobs = load_jobs(config_path)
            jobs.append(job)
            save_jobs(config_path, jobs)
            refresh()
            if on_change:
                on_change()

        AddJobDialog(root, _on_saved)

    tk.Button(root, text="Aggiungi vault locale...", command=add_vault).grid(row=1, column=0, padx=8, pady=8)
    tk.Button(root, text="Aggiungi backup su server...", command=add_job).grid(row=1, column=1, padx=8, pady=8)
    tk.Button(root, text="Rimuovi selezionato", command=remove_selected).grid(row=1, column=2, padx=8, pady=8)

    refresh()
    root.mainloop()


def ensure_config_exists(config_path: str) -> None:
    if not os.path.exists(config_path):
        with open(config_path, "w", encoding="utf-8") as f:
            f.write("jobs: []\nvaults: []\n")
