import sys
import types

import pytest

from filesync import secrets_store


class _FakeKeyring:
    """Sostituisce il modulo 'keyring' reale (non disponibile/testabile in
    questo ambiente headless): un dizionario in memoria con la stessa API."""

    def __init__(self):
        self._store = {}

    def set_password(self, service, key, password):
        self._store[(service, key)] = password

    def get_password(self, service, key):
        return self._store.get((service, key))

    def delete_password(self, service, key):
        del self._store[(service, key)]


@pytest.fixture
def fake_keyring(monkeypatch):
    fake_module = _FakeKeyring()
    monkeypatch.setitem(sys.modules, "keyring", fake_module)
    return fake_module


def test_set_and_get_password_round_trip(fake_keyring):
    secrets_store.set_password("job:PLC1", "una-password")
    assert secrets_store.get_password("job:PLC1") == "una-password"


def test_get_password_missing_returns_none(fake_keyring):
    assert secrets_store.get_password("job:NonEsiste") is None


def test_delete_password(fake_keyring):
    secrets_store.set_password("vault:V1", "pw")
    secrets_store.delete_password("vault:V1")
    assert secrets_store.get_password("vault:V1") is None


def test_delete_password_missing_does_not_raise(fake_keyring):
    secrets_store.delete_password("vault:NonEsisteMai")  # non deve sollevare


def test_get_password_when_keyring_module_missing_returns_none(monkeypatch):
    def _boom():
        raise ImportError("no module named keyring")

    monkeypatch.setattr(secrets_store, "_keyring", _boom)
    assert secrets_store.get_password("job:X") is None


def test_set_password_when_keyring_module_missing_raises_friendly_error(monkeypatch):
    def _boom():
        raise ImportError("no module named keyring")

    monkeypatch.setattr(secrets_store, "_keyring", _boom)
    with pytest.raises(RuntimeError, match="keyring"):
        secrets_store.set_password("job:X", "pw")


def test_set_password_backend_failure_raises_friendly_error(monkeypatch):
    class _BrokenKeyring:
        def set_password(self, *a, **k):
            raise RuntimeError("nessun backend disponibile")

    monkeypatch.setattr(secrets_store, "_keyring", lambda: _BrokenKeyring())
    with pytest.raises(RuntimeError):
        secrets_store.set_password("job:X", "pw")
