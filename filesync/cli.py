"""CLI: python -m filesync <sync|encrypt|decrypt|master-keygen|recover|open> ..."""

from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from cryptography.fernet import Fernet

from . import crypto, envelope, keys, mailer, vault
from . import protect as protect_module
from . import sync as sync_module
from .config import load_jobs
from .sync import run_job


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _run_one(job, dry_run: bool) -> bool:
    """Esegue un job. Ritorna True se c'e' stato un errore."""
    try:
        run_job(job, dry_run=dry_run)
        return False
    except Exception as exc:  # noqa: BLE001 - un job che fallisce non deve fermare gli altri
        logging.getLogger("filesync.cli").error("Job '%s' fallito: %s", job.name, exc)
        return True


def cmd_sync(args: argparse.Namespace) -> int:
    jobs = load_jobs(args.config)
    if not jobs:
        print(f"Nessun job trovato in '{args.config}' (chiave 'jobs' mancante o vuota).", file=sys.stderr)
        return 1
    if args.job:
        jobs = [j for j in jobs if j.name == args.job]
        if not jobs:
            print(f"Nessun job chiamato '{args.job}' trovato in {args.config}", file=sys.stderr)
            return 1

    def run_all() -> bool:
        if args.sequential or len(jobs) <= 1:
            return any(_run_one(job, args.dry_run) for job in jobs)

        # Piu' cartelle vengono sincronizzate in parallelo verso il server:
        # l'operazione e' quasi tutta I/O (rete/disco), quindi i thread bastano.
        any_error = False
        max_workers = min(len(jobs), args.max_parallel)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(_run_one, job, args.dry_run) for job in jobs]
            for future in as_completed(futures):
                any_error = future.result() or any_error
        return any_error

    if args.watch:
        print(f"Modalita' watch attiva (intervallo {args.interval}s). CTRL+C per fermare.")
        try:
            while True:
                run_all()
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nInterrotto dall'utente.")
            return 0
    else:
        return 1 if run_all() else 0


def cmd_encrypt(args: argparse.Namespace) -> int:
    password = args.password or getpass.getpass("Password di cifratura: ")
    if not args.password:
        confirm = getpass.getpass("Conferma password: ")
        if confirm != password:
            print("Le password non coincidono.", file=sys.stderr)
            return 1

    count = crypto.encrypt_folder(args.source, args.destination, password)
    print(f"Cifrati {count} file in '{args.destination}'.")
    return 0


def cmd_decrypt(args: argparse.Namespace) -> int:
    password = args.password or getpass.getpass("Password di cifratura: ")
    try:
        count = crypto.decrypt_folder(args.source, args.destination, password)
    except crypto.DecryptionError as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1
    print(f"Decifrati {count} file in '{args.destination}'.")
    return 0


def cmd_master_keygen(args: argparse.Namespace) -> int:
    passphrase = args.passphrase or getpass.getpass(
        "Passphrase per proteggere la chiave master (solo tu la devi conoscere): "
    )
    if not args.passphrase:
        confirm = getpass.getpass("Conferma passphrase: ")
        if confirm != passphrase:
            print("Le passphrase non coincidono.", file=sys.stderr)
            return 1

    os.makedirs(args.out_dir, exist_ok=True)
    private_path = os.path.join(args.out_dir, "master_private.pem")
    public_path = os.path.join(args.out_dir, "master_public.pem")
    if os.path.exists(private_path) or os.path.exists(public_path):
        print(f"Errore: esistono gia' dei file in '{args.out_dir}'. Rimuovili o scegli un'altra cartella.", file=sys.stderr)
        return 1

    private_pem, public_pem = keys.generate_master_keypair(passphrase)
    with open(private_path, "wb") as f:
        f.write(private_pem)
    with open(public_path, "wb") as f:
        f.write(public_pem)

    print(f"Creata coppia di chiavi master in '{args.out_dir}':")
    print(f"  - {public_path}  (da distribuire ai colleghi/config, NON e' un segreto)")
    print(f"  - {private_path}  (SOLO PER TE: conservala offline, es. su una chiavetta USB "
          "in un cassetto, MAI su git o sul server di backup)")
    print("Senza questo file + la passphrase nessuno puo' usare la chiave master, nemmeno tu se li perdi.")
    return 0


def cmd_recover(args: argparse.Namespace) -> int:
    try:
        if args.recovery_key:
            dek = envelope.unwrap_dek_with_recovery_key(args.destination, args.recovery_key)
            source_desc = "chiave di recovery"
        else:
            passphrase = args.master_passphrase or getpass.getpass("Passphrase della chiave master: ")
            dek = envelope.unwrap_dek_with_master_key(args.destination, args.master_private_key, passphrase)
            source_desc = "chiave master"
    except (crypto.DecryptionError, FileNotFoundError) as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1

    new_password = args.new_password or getpass.getpass("Nuova password personale per questo backup: ")
    envelope.reset_user_password(args.destination, dek, new_password)
    print(f"Accesso recuperato tramite {source_desc}. Password personale aggiornata per '{args.destination}'.")
    print("Aggiorna anche la variabile d'ambiente / il secret usato da questo job con la nuova password.")
    return 0


def cmd_open(args: argparse.Namespace) -> int:
    try:
        if args.recovery_key:
            dek = envelope.unwrap_dek_with_recovery_key(args.destination, args.recovery_key)
        elif args.master_private_key:
            passphrase = args.master_passphrase or getpass.getpass("Passphrase della chiave master: ")
            dek = envelope.unwrap_dek_with_master_key(args.destination, args.master_private_key, passphrase)
        else:
            password = args.password or getpass.getpass("Password personale: ")
            dek = envelope.unwrap_dek_with_password(args.destination, password)
    except (crypto.DecryptionError, FileNotFoundError) as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1

    cipher = Fernet(dek)
    count = envelope.decrypt_all(args.destination, args.output, cipher)
    print(f"Ripristinati {count} file in chiaro in '{args.output}'.")
    return 0


def cmd_protect(args: argparse.Namespace) -> int:
    try:
        if protect_module.is_windows():
            protect_module.protect_windows(args.folder)
            print(f"Accesso ristretto al solo utente corrente su '{args.folder}' (icacls).")
        else:
            count = protect_module.protect_posix(args.folder)
            print(f"Permessi 'solo proprietario' applicati a {count} file in '{args.folder}'.")
    except OSError as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1
    print("NOTA: non e' cifratura, e' un controllo accessi del sistema operativo. "
          "Un amministratore/root della macchina puo' comunque bypassarlo. "
          "Usa 'filesync unprotect' per tornare ai permessi precedenti.")
    return 0


def cmd_unprotect(args: argparse.Namespace) -> int:
    try:
        if protect_module.is_windows():
            protect_module.unprotect_windows(args.folder)
            print(f"Permessi ereditati ripristinati per '{args.folder}'.")
        else:
            count = protect_module.unprotect_posix(args.folder)
            print(f"Permessi originali ripristinati per {count} elementi in '{args.folder}'.")
    except (FileNotFoundError, OSError) as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_lock(args: argparse.Namespace) -> int:
    password = args.password or getpass.getpass("Password del vault: ")
    if not args.password:
        confirm = getpass.getpass("Conferma password: ")
        if confirm != password:
            print("Le password non coincidono.", file=sys.stderr)
            return 1

    first_time = not envelope.envelope_exists(args.vault)
    recovery_key = keys.generate_recovery_key() if (first_time and args.recovery_email) else None

    try:
        count = vault.lock(
            args.workspace,
            args.vault,
            password,
            master_public_key_path=args.master_public_key,
            recovery_key=recovery_key,
        )
    except (FileNotFoundError, RuntimeError, crypto.DecryptionError) as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1

    print(f"Bloccati {count} file: '{args.workspace}' e' stata cancellata, il contenuto esiste solo cifrato in '{args.vault}'.")

    if recovery_key and args.recovery_email:
        try:
            mailer.send_recovery_email(args.recovery_email, os.path.basename(args.vault.rstrip(os.sep)), args.vault, recovery_key)
            print(f"Chiave di recovery inviata a {args.recovery_email}.")
        except Exception as exc:  # noqa: BLE001
            print(
                f"ATTENZIONE: invio email fallito ({exc}). CONSERVA SUBITO questa chiave, non verra' rigenerata: {recovery_key}",
                file=sys.stderr,
            )
    return 0


def cmd_unlock(args: argparse.Namespace) -> int:
    try:
        if args.recovery_key:
            dek = envelope.unwrap_dek_with_recovery_key(args.vault, args.recovery_key)
        elif args.master_private_key:
            passphrase = args.master_passphrase or getpass.getpass("Passphrase della chiave master: ")
            dek = envelope.unwrap_dek_with_master_key(args.vault, args.master_private_key, passphrase)
        else:
            password = args.password or getpass.getpass("Password del vault: ")
            dek = envelope.unwrap_dek_with_password(args.vault, password)
    except (crypto.DecryptionError, FileNotFoundError) as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1

    try:
        count = vault.unlock(args.vault, args.workspace, dek)
    except (FileNotFoundError, FileExistsError) as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1

    print(f"Sbloccati {count} file in '{args.workspace}'. Ricorda 'filesync lock' quando hai finito di lavorarci.")
    return 0


def cmd_versions(args: argparse.Namespace) -> int:
    versions = sync_module.list_versions(args.destination, args.rel_path)
    if not versions:
        print(f"Nessuna versione storica trovata per '{args.rel_path}' in '{args.destination}'.")
        return 0
    for v in versions:
        print(v)
    return 0


def cmd_restore_version(args: argparse.Namespace) -> int:
    is_encrypted = args.rel_path.endswith(crypto.ENCRYPTED_SUFFIX)
    cipher = None

    if is_encrypted:
        try:
            if args.recovery_key:
                dek = envelope.unwrap_dek_with_recovery_key(args.destination, args.recovery_key)
            elif args.master_private_key:
                passphrase = args.master_passphrase or getpass.getpass("Passphrase della chiave master: ")
                dek = envelope.unwrap_dek_with_master_key(args.destination, args.master_private_key, passphrase)
            else:
                password = args.password or getpass.getpass("Password personale: ")
                dek = envelope.unwrap_dek_with_password(args.destination, password)
        except (crypto.DecryptionError, FileNotFoundError) as exc:
            print(f"Errore: {exc}", file=sys.stderr)
            return 1
        cipher = Fernet(dek)

    try:
        sync_module.restore_version(args.destination, args.rel_path, args.version, args.output, cipher=cipher)
    except FileNotFoundError as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1

    print(f"Versione '{args.version}' di '{args.rel_path}' ripristinata in '{args.output}'.")
    return 0


def cmd_tray(args: argparse.Namespace) -> int:
    from . import tray as tray_module  # import lazy: pystray/Pillow servono solo qui

    app = tray_module.TrayApp(args.config, interval=args.interval)
    app.run()
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    try:
        from . import setup_gui  # import lazy: tkinter servono solo qui
    except ImportError:
        print(
            "Manca Tkinter, richiesto dalla finestra di configurazione.\n"
            "Su Windows/macOS e' incluso nell'installer ufficiale di Python "
            "(reinstalla Python selezionando 'tcl/tk and IDLE'); su Linux minimale "
            "installa il pacchetto di sistema 'python3-tk'.",
            file=sys.stderr,
        )
        return 1

    setup_gui.ensure_config_exists(args.config)
    try:
        setup_gui.open_manage_window(args.config)
    except Exception as exc:  # noqa: BLE001 - su una sessione senza display Tk fallisce qui, non all'import
        print(f"Impossibile aprire la finestra di configurazione: {exc}", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="filesync", description="Sincronizzazione cartelle con cifratura opzionale.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Log dettagliato")
    sub = parser.add_subparsers(dest="command", required=True)

    p_sync = sub.add_parser("sync", help="Esegue i job definiti in un file di configurazione YAML")
    p_sync.add_argument("-c", "--config", required=True, help="Percorso del file config.yaml")
    p_sync.add_argument("--job", help="Esegue solo il job con questo nome")
    p_sync.add_argument("--watch", action="store_true", help="Esegue in loop continuo")
    p_sync.add_argument("--interval", type=int, default=60, help="Secondi tra un ciclo e l'altro in modalita' --watch (default 60)")
    p_sync.add_argument("--dry-run", action="store_true", help="Mostra cosa verrebbe fatto senza modificare nulla")
    p_sync.add_argument("--sequential", action="store_true", help="Esegue i job uno alla volta invece che in parallelo")
    p_sync.add_argument("--max-parallel", type=int, default=4, help="Numero massimo di job eseguiti in parallelo (default 4)")
    p_sync.set_defaults(func=cmd_sync)

    p_enc = sub.add_parser("encrypt", help="Cifra tutti i file di una cartella in un'altra (uso manuale, solo password)")
    p_enc.add_argument("source", help="Cartella sorgente in chiaro")
    p_enc.add_argument("destination", help="Cartella di destinazione per i file cifrati")
    p_enc.add_argument("--password", help="Password (se omessa viene richiesta in modo sicuro)")
    p_enc.set_defaults(func=cmd_encrypt)

    p_dec = sub.add_parser("decrypt", help="Decifra tutti i file di una cartella in un'altra (uso manuale, solo password)")
    p_dec.add_argument("source", help="Cartella sorgente con i file cifrati (*.enc)")
    p_dec.add_argument("destination", help="Cartella di destinazione per i file decifrati")
    p_dec.add_argument("--password", help="Password (se omessa viene richiesta in modo sicuro)")
    p_dec.set_defaults(func=cmd_decrypt)

    p_keygen = sub.add_parser("master-keygen", help="Genera la coppia di chiavi master (da fare UNA SOLA VOLTA, solo l'amministratore)")
    p_keygen.add_argument("--out-dir", default="./master_keys", help="Cartella dove salvare le chiavi (default ./master_keys)")
    p_keygen.add_argument("--passphrase", help="Passphrase della chiave privata (se omessa viene richiesta in modo sicuro)")
    p_keygen.set_defaults(func=cmd_master_keygen)

    p_recover = sub.add_parser(
        "recover",
        help="Recupera l'accesso a un job cifrato (password dimenticata) impostando una nuova password personale",
    )
    p_recover.add_argument("destination", help="Cartella di destinazione del job cifrato (sul server)")
    p_recover.add_argument("--new-password", help="Nuova password personale (se omessa viene richiesta in modo sicuro)")
    group = p_recover.add_mutually_exclusive_group(required=True)
    group.add_argument("--recovery-key", help="Chiave di recovery ricevuta via email (uso normale)")
    group.add_argument("--master-private-key", help="Percorso di master_private.pem (solo amministratore)")
    p_recover.add_argument("--master-passphrase", help="Passphrase della chiave master (se serve --master-private-key)")
    p_recover.set_defaults(func=cmd_recover)

    p_open = sub.add_parser(
        "open",
        help="Decifra l'intero backup cifrato di un job in una cartella in chiaro (es. ripristino dopo un guasto)",
    )
    p_open.add_argument("destination", help="Cartella di destinazione del job cifrato (sul server)")
    p_open.add_argument("output", help="Cartella dove scrivere i file ripristinati in chiaro")
    auth_group = p_open.add_mutually_exclusive_group()
    auth_group.add_argument("--password", help="Password personale (default: la richiede in modo sicuro)")
    auth_group.add_argument("--recovery-key", help="Usa la chiave di recovery ricevuta via email")
    auth_group.add_argument("--master-private-key", help="Usa la chiave master (solo amministratore)")
    p_open.add_argument("--master-passphrase", help="Passphrase della chiave master (se usi --master-private-key)")
    p_open.set_defaults(func=cmd_open)

    p_protect = sub.add_parser(
        "protect",
        help="Blocca l'accesso a una cartella locale (source) ad altri utenti del sistema operativo",
    )
    p_protect.add_argument("folder", help="Cartella da proteggere (es. la source di un progetto)")
    p_protect.set_defaults(func=cmd_protect)

    p_unprotect = sub.add_parser("unprotect", help="Ripristina i permessi precedenti su una cartella protetta con 'protect'")
    p_unprotect.add_argument("folder", help="Cartella da sbloccare")
    p_unprotect.set_defaults(func=cmd_unprotect)

    p_lock = sub.add_parser(
        "lock",
        help="Cifra la cartella di lavoro in un vault e CANCELLA i file in chiaro (chiudi prima IDE/TIA Portal!)",
    )
    p_lock.add_argument("workspace", help="Cartella di lavoro in chiaro da bloccare")
    p_lock.add_argument("vault", help="Cartella vault dove finisce il contenuto cifrato")
    p_lock.add_argument("--password", help="Password del vault (se omessa viene richiesta in modo sicuro)")
    p_lock.add_argument("--master-public-key", help="Chiave pubblica master (permette il recupero da parte dell'amministratore)")
    p_lock.add_argument("--recovery-email", help="Email a cui mandare la chiave di recovery (solo alla prima creazione del vault)")
    p_lock.set_defaults(func=cmd_lock)

    p_unlock = sub.add_parser("unlock", help="Decifra un vault nella cartella di lavoro, pronta per l'IDE")
    p_unlock.add_argument("vault", help="Cartella vault cifrata")
    p_unlock.add_argument("workspace", help="Cartella di lavoro da ricreare in chiaro (deve non esistere o essere vuota)")
    auth_group2 = p_unlock.add_mutually_exclusive_group()
    auth_group2.add_argument("--password", help="Password del vault (default: la richiede in modo sicuro)")
    auth_group2.add_argument("--recovery-key", help="Usa la chiave di recovery ricevuta via email")
    auth_group2.add_argument("--master-private-key", help="Usa la chiave master (solo amministratore)")
    p_unlock.add_argument("--master-passphrase", help="Passphrase della chiave master (se usi --master-private-key)")
    p_unlock.set_defaults(func=cmd_unlock)

    p_tray = sub.add_parser(
        "tray",
        help="Avvia l'icona nella system tray: sync automatica in background + blocco/sblocco vault dal menu "
             "(richiede 'pip install pystray Pillow')",
    )
    p_tray.add_argument("-c", "--config", required=True, help="Percorso del file config.yaml (jobs: e/o vaults:)")
    p_tray.add_argument("--interval", type=int, default=300, help="Secondi tra un ciclo di sync automatico e l'altro (default 300)")
    p_tray.set_defaults(func=cmd_tray)

    p_versions = sub.add_parser(
        "versions",
        help="Elenca le versioni storiche salvate di un file nel backup (protezione da ransomware/errori)",
    )
    p_versions.add_argument("destination", help="Cartella di destinazione del job")
    p_versions.add_argument("rel_path", help="Percorso relativo del file cosi' come appare in destinazione (aggiungi '.enc' se il job e' cifrato)")
    p_versions.set_defaults(func=cmd_versions)

    p_restore_version = sub.add_parser(
        "restore-version",
        help="Ripristina una versione storica precedente di un file (es. dopo che il file corrente e' stato corrotto da un ransomware)",
    )
    p_restore_version.add_argument("destination", help="Cartella di destinazione del job")
    p_restore_version.add_argument("rel_path", help="Percorso relativo del file (con '.enc' se cifrato)")
    p_restore_version.add_argument("version", help="Timestamp della versione (vedi 'filesync versions')")
    p_restore_version.add_argument("output", help="File dove scrivere la versione ripristinata")
    auth_group3 = p_restore_version.add_mutually_exclusive_group()
    auth_group3.add_argument("--password", help="Password personale (solo se il file e' cifrato)")
    auth_group3.add_argument("--recovery-key", help="Chiave di recovery (solo se il file e' cifrato)")
    auth_group3.add_argument("--master-private-key", help="Chiave master, solo amministratore (solo se il file e' cifrato)")
    p_restore_version.add_argument("--master-passphrase", help="Passphrase della chiave master")
    p_restore_version.set_defaults(func=cmd_restore_version)

    p_setup = sub.add_parser(
        "setup",
        help="Apre la finestra di configurazione visuale (aggiungi/rimuovi progetti scegliendo le cartelle, senza editare YAML)",
    )
    p_setup.add_argument("-c", "--config", required=True, help="Percorso del file config.yaml (creato se non esiste)")
    p_setup.set_defaults(func=cmd_setup)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
