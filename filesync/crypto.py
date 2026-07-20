"""Cifratura/decifratura di cartelle con AES (Fernet) derivato da password.

Ogni file viene cifrato singolarmente con una chiave derivata dalla password
tramite PBKDF2-HMAC-SHA256. Il salt e' unico per cartella cifrata e viene
salvato in chiaro accanto ai file (il salt non e' un segreto: senza la
password non permette comunque di decifrare nulla).
"""

from __future__ import annotations

import base64
import os
from typing import Callable, Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

KDF_ITERATIONS = 480_000
SALT_FILENAME = ".filesync_salt"
ENCRYPTED_SUFFIX = ".enc"


class DecryptionError(Exception):
    """Sollevata quando un file non puo' essere decifrato (password errata o dato corrotto)."""


def derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=KDF_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def load_or_create_salt(root_dir: str) -> bytes:
    os.makedirs(root_dir, exist_ok=True)
    salt_path = os.path.join(root_dir, SALT_FILENAME)
    if os.path.exists(salt_path):
        with open(salt_path, "rb") as f:
            return f.read()
    salt = os.urandom(16)
    with open(salt_path, "wb") as f:
        f.write(salt)
    return salt


def make_cipher(password: str, salt_root_dir: str) -> Fernet:
    """Crea un oggetto Fernet leggendo/creando il salt in salt_root_dir."""
    salt = load_or_create_salt(salt_root_dir)
    return Fernet(derive_key(password, salt))


def generate_dek() -> bytes:
    """Genera una nuova Data Encryption Key (chiave Fernet a 32 byte)."""
    return Fernet.generate_key()


def pbkdf2_wrap_dek(dek: bytes, passphrase: str) -> dict:
    """Cifra (wrappa) una DEK con una chiave derivata da una password/passphrase.

    Usato per proteggere la DEK sia con la password personale sia con la
    chiave di recovery: stesso meccanismo, passphrase diversa.
    """
    salt = os.urandom(16)
    key = derive_key(passphrase, salt)
    token = Fernet(key).encrypt(dek)
    return {
        "method": "pbkdf2",
        "salt": base64.b64encode(salt).decode("ascii"),
        "token": base64.b64encode(token).decode("ascii"),
    }


def pbkdf2_unwrap_dek(wrap: dict, passphrase: str) -> bytes:
    salt = base64.b64decode(wrap["salt"])
    token = base64.b64decode(wrap["token"])
    key = derive_key(passphrase, salt)
    try:
        return Fernet(key).decrypt(token)
    except InvalidToken as exc:
        raise DecryptionError("Password o chiave di recovery errata.") from exc


def encrypt_bytes(cipher: Fernet, data: bytes) -> bytes:
    return cipher.encrypt(data)


def decrypt_bytes(cipher: Fernet, token: bytes) -> bytes:
    try:
        return cipher.decrypt(token)
    except InvalidToken as exc:
        raise DecryptionError("Password errata o file corrotto.") from exc


def _iter_files(root_dir: str, exclude_names: Optional[set] = None):
    exclude_names = exclude_names or set()
    for dirpath, _dirnames, filenames in os.walk(root_dir):
        for filename in filenames:
            if filename in exclude_names:
                continue
            full_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(full_path, root_dir)
            yield rel_path


def encrypt_folder(
    source_dir: str,
    dest_dir: str,
    password: str,
    on_file: Optional[Callable[[str], None]] = None,
) -> int:
    """Cifra tutti i file di source_dir in dest_dir, preservando la struttura.

    Ogni file <rel> diventa <rel>.enc in dest_dir. Il salt viene generato in
    dest_dir. Ritorna il numero di file cifrati.
    """
    os.makedirs(dest_dir, exist_ok=True)
    cipher = make_cipher(password, dest_dir)

    count = 0
    for rel_path in _iter_files(source_dir, exclude_names={SALT_FILENAME}):
        src_path = os.path.join(source_dir, rel_path)
        dst_path = os.path.join(dest_dir, rel_path + ENCRYPTED_SUFFIX)
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)

        with open(src_path, "rb") as f:
            plaintext = f.read()
        token = encrypt_bytes(cipher, plaintext)
        with open(dst_path, "wb") as f:
            f.write(token)

        st = os.stat(src_path)
        os.utime(dst_path, (st.st_atime, st.st_mtime))

        count += 1
        if on_file:
            on_file(rel_path)

    return count


def decrypt_folder(
    source_dir: str,
    dest_dir: str,
    password: str,
    on_file: Optional[Callable[[str], None]] = None,
) -> int:
    """Decifra tutti i file *.enc di source_dir in dest_dir.

    Ritorna il numero di file decifrati.
    """
    cipher = make_cipher(password, source_dir)

    count = 0
    for rel_path in _iter_files(source_dir, exclude_names={SALT_FILENAME}):
        if not rel_path.endswith(ENCRYPTED_SUFFIX):
            continue
        src_path = os.path.join(source_dir, rel_path)
        dst_rel = rel_path[: -len(ENCRYPTED_SUFFIX)]
        dst_path = os.path.join(dest_dir, dst_rel)
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)

        with open(src_path, "rb") as f:
            token = f.read()
        plaintext = decrypt_bytes(cipher, token)
        with open(dst_path, "wb") as f:
            f.write(plaintext)

        st = os.stat(src_path)
        os.utime(dst_path, (st.st_atime, st.st_mtime))

        count += 1
        if on_file:
            on_file(dst_rel)

    return count
