"""CLI: python -m filesync <sync|encrypt|decrypt> ..."""

from __future__ import annotations

import argparse
import getpass
import logging
import sys
import time

from . import crypto
from .config import load_jobs
from .sync import run_job


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def cmd_sync(args: argparse.Namespace) -> int:
    jobs = load_jobs(args.config)
    if args.job:
        jobs = [j for j in jobs if j.name == args.job]
        if not jobs:
            print(f"Nessun job chiamato '{args.job}' trovato in {args.config}", file=sys.stderr)
            return 1

    def run_all() -> bool:
        any_error = False
        for job in jobs:
            try:
                run_job(job, dry_run=args.dry_run)
            except Exception as exc:  # noqa: BLE001 - vogliamo continuare con gli altri job
                logging.getLogger("filesync.cli").error("Job '%s' fallito: %s", job.name, exc)
                any_error = True
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
    p_sync.set_defaults(func=cmd_sync)

    p_enc = sub.add_parser("encrypt", help="Cifra tutti i file di una cartella in un'altra")
    p_enc.add_argument("source", help="Cartella sorgente in chiaro")
    p_enc.add_argument("destination", help="Cartella di destinazione per i file cifrati")
    p_enc.add_argument("--password", help="Password (se omessa viene richiesta in modo sicuro)")
    p_enc.set_defaults(func=cmd_encrypt)

    p_dec = sub.add_parser("decrypt", help="Decifra tutti i file di una cartella in un'altra")
    p_dec.add_argument("source", help="Cartella sorgente con i file cifrati (*.enc)")
    p_dec.add_argument("destination", help="Cartella di destinazione per i file decifrati")
    p_dec.add_argument("--password", help="Password (se omessa viene richiesta in modo sicuro)")
    p_dec.set_defaults(func=cmd_decrypt)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
