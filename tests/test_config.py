import pytest

from filesync.config import load_jobs, load_vaults


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
    from filesync.config import Vault

    v = Vault(name="V", workspace="/a", vault="/b", password_env="TEST_VAULT_PW")
    assert v.resolve_password() is None

    monkeypatch.setenv("TEST_VAULT_PW", "segreta")
    assert v.resolve_password() == "segreta"
