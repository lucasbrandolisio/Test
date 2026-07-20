"""Coppia di chiavi 'master' per il recupero amministrativo (solo il titolare).

Genera una coppia di chiavi RSA-4096: la chiave PUBBLICA puo' essere
distribuita ai colleghi (non e' un segreto, serve solo a "chiudere il
lucchetto" durante la cifratura). La chiave PRIVATA resta solo a chi
amministra il backup, protetta da una passphrase nota solo a lui: senza
chiave privata + passphrase nessun altro puo' usarla per decifrare.
"""

from __future__ import annotations

import base64
import secrets

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from .crypto import DecryptionError

RSA_KEY_SIZE = 4096

_OAEP = padding.OAEP(
    mgf=padding.MGF1(algorithm=hashes.SHA256()),
    algorithm=hashes.SHA256(),
    label=None,
)


def generate_master_keypair(passphrase: str) -> tuple[bytes, bytes]:
    """Genera (private_pem, public_pem). La chiave privata e' cifrata con passphrase."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=RSA_KEY_SIZE)
    public_key = private_key.public_key()

    encryption = (
        serialization.BestAvailableEncryption(passphrase.encode("utf-8"))
        if passphrase
        else serialization.NoEncryption()
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=encryption,
    )
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def load_public_key(path: str):
    with open(path, "rb") as f:
        return serialization.load_pem_public_key(f.read())


def load_private_key(path: str, passphrase: str):
    with open(path, "rb") as f:
        data = f.read()
    try:
        return serialization.load_pem_private_key(
            data, password=passphrase.encode("utf-8") if passphrase else None
        )
    except (TypeError, ValueError) as exc:
        raise DecryptionError("Chiave master o passphrase errata.") from exc


def rsa_wrap(dek: bytes, public_key) -> str:
    ciphertext = public_key.encrypt(dek, _OAEP)
    return base64.b64encode(ciphertext).decode("ascii")


def rsa_unwrap(token_b64: str, private_key) -> bytes:
    ciphertext = base64.b64decode(token_b64)
    try:
        return private_key.decrypt(ciphertext, _OAEP)
    except ValueError as exc:
        raise DecryptionError("Chiave master errata per questo progetto.") from exc


def generate_recovery_key() -> str:
    """Genera una chiave di recovery leggibile, es. 'XJ4R2-9KLMN-QW3ZT-...'."""
    raw = secrets.token_bytes(20)
    b32 = base64.b32encode(raw).decode("ascii").rstrip("=")
    groups = [b32[i : i + 5] for i in range(0, len(b32), 5)]
    return "-".join(groups)
