import sys

import pytest

from filesync.config import Job, Vault, load_jobs, load_vaults, save_jobs, save_vaults


def test_load_jobs_returns_empty_list_when_key_missing(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("vaults:\n  - name: V\n    workspace: /a\n    vault: /b\n")

    assert load_jobs(str(config_path)) == []


def test_load_vaults_returns_empty_list_when_key_missing(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("jobs:\n  - name: J\n    source: /a\n    destination: /b\n")

    assert load_vaults(str(config_path)) == []


def test_load_vaults_parses_fields_with_defaults(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "vaults:\n"
        "  - name: PLC1\n"
        "    workspace: /home/utente/PLC1\n"
        "    vault: /home/utente/PLC1.vault\n"
        "    password_env: FILESYNC_PW\n"
        "    warn_after_minutes: 15\n"
        "  - name: PLC2\n"
        "    workspace: /home/utente/PLC2\n"
        "    vault: /home/utente/PLC2.vault\n"
    )

    vaults = load_vaults(str(config_path))

    assert len(vaults) == 2
    assert vaults[0].name == "PLC1"
    assert vaults[0].password_env == "FILESYNC_PW"
    assert vaults[0].warn_after_minutes == 15
    assert vaults[1].warn_after_minutes == 30  # default


def test_load_vaults_missing_field_raises(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("vaults:\n  - name: PLC1\n    workspace: /a\n")

    with pytest.raises(ValueError):
        load_vaults(str(config_path))


def test_vault_resolve_password_from_env(tmp_path, monkeypatch):
    v = Vault(name="V", workspace="/a", vault="/b", password_env="TEST_VAULT_PW")
    assert v.resolve_password() is None

    monkeypatch.setenv("TEST_VAULT_PW", "segreta")
    assert v.resolve_password() == "segreta"


class _FakeKeyring:
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


def test_vault_resolve_password_falls_back_to_keyring(fake_keyring):
    from filesync import secrets_store

    v = Vault(name="ProgettoPython", workspace="/a", vault="/b")
    assert v.resolve_password() is None

    secrets_store.set_password("vault:ProgettoPython", "dalla-gui")
    assert v.resolve_password() == "dalla-gui"


def test_job_resolve_password_env_wins_over_keyring(fake_keyring, monkeypatch):
    from filesync import secrets_store

    secrets_store.set_password("job:PLC1", "dalla-gui")
    j = Job(name="PLC1", source="/a", destination="/b", encrypt=True, password_env="TEST_JOB_PW")

    monkeypatch.setenv("TEST_JOB_PW", "da-env")
    assert j.resolve_password() == "da-env"


def test_job_resolve_password_falls_back_to_keyring_when_no_env(fake_keyring):
    from filesync import secrets_store

    secrets_store.set_password("job:PLC1", "dalla-gui")
    j = Job(name="PLC1", source="/a", destination="/b", encrypt=True)
    assert j.resolve_password() == "dalla-gui"


def test_job_resolve_password_raises_when_nothing_found(fake_keyring):
    j = Job(name="PLC1", source="/a", destination="/b", encrypt=True)
    with pytest.raises(ValueError):
        j.resolve_password()


def test_save_jobs_round_trip(tmp_path):
    config_path = tmp_path / "config.yaml"
    jobs = [
        Job(name="PLC1", source="/a", destination="/b", mirror=True, keep_versions=3),
        Job(name="PLC2", source="/c", destination="/d"),
    ]

    save_jobs(str(config_path), jobs)
    loaded = load_jobs(str(config_path))

    assert [j.name for j in loaded] == ["PLC1", "PLC2"]
    assert loaded[0].mirror is True
    assert loaded[0].keep_versions == 3
    assert loaded[1].keep_versions == 5  # default preservato


def test_save_jobs_preserves_existing_vaults_section(tmp_path):
    config_path = tmp_path / "config.yaml"
    save_vaults(str(config_path), [Vault(name="V1", workspace="/a", vault="/b")])

    save_jobs(str(config_path), [Job(name="J1", source="/x", destination="/y")])

    assert [v.name for v in load_vaults(str(config_path))] == ["V1"]
    assert [j.name for j in load_jobs(str(config_path))] == ["J1"]


def test_save_vaults_round_trip(tmp_path):
    config_path = tmp_path / "config.yaml"
    vaults = [Vault(name="V1", workspace="/a", vault="/b", warn_after_minutes=15)]

    save_vaults(str(config_path), vaults)
    loaded = load_vaults(str(config_path))

    assert loaded[0].name == "V1"
    assert loaded[0].warn_after_minutes == 15
