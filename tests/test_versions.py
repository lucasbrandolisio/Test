import os
import time

from cryptography.fernet import Fernet

from filesync import crypto
from filesync.sync import list_versions, restore_version, sync_directory


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def test_no_version_saved_for_brand_new_file(tmp_path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _write(src / "a.txt", "v1")

    sync_directory(str(src), str(dst), keep_versions=5)

    assert list_versions(str(dst), "a.txt") == []


def test_version_saved_on_overwrite_and_restorable(tmp_path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _write(src / "a.txt", "versione buona")
    sync_directory(str(src), str(dst), keep_versions=5)

    time.sleep(1.1)
    _write(src / "a.txt", "versione modificata")
    sync_directory(str(src), str(dst), keep_versions=5)

    versions = list_versions(str(dst), "a.txt")
    assert len(versions) == 1

    output = tmp_path / "restored.txt"
    restore_version(str(dst), "a.txt", versions[0], str(output))
    assert output.read_text() == "versione buona"

    # il file "attuale" in destinazione e' quello nuovo
    assert (dst / "a.txt").read_text() == "versione modificata"


def test_ransomware_scenario_old_good_version_survives(tmp_path):
    """Simula un ransomware che sovrascrive il file sorgente: la sync
    propaga inevitabilmente il contenuto compromesso, ma la versione buona
    precedente resta recuperabile."""
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _write(src / "progetto.st", "PROGRAM Main; codice PLC buono END_PROGRAM")
    sync_directory(str(src), str(dst), keep_versions=5)

    time.sleep(1.1)
    _write(src / "progetto.st", "***CIFRATO DAL RANSOMWARE, PAGA IL RISCATTO***")
    sync_directory(str(src), str(dst), keep_versions=5)

    # il backup "corrente" e' purtroppo compromesso...
    assert "RANSOMWARE" in (dst / "progetto.st").read_text()

    # ...ma la versione precedente e' ancora li', recuperabile
    versions = list_versions(str(dst), "progetto.st")
    assert len(versions) == 1
    output = tmp_path / "recuperato.st"
    restore_version(str(dst), "progetto.st", versions[0], str(output))
    assert output.read_text() == "PROGRAM Main; codice PLC buono END_PROGRAM"


def test_prunes_to_keep_only_last_n_versions(tmp_path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _write(src / "a.txt", "v1")
    sync_directory(str(src), str(dst), keep_versions=2)

    for v in ("v2", "v3", "v4"):
        time.sleep(1.1)
        _write(src / "a.txt", v)
        sync_directory(str(src), str(dst), keep_versions=2)

    # 3 sovrascritture (v1->v2, v2->v3, v3->v4) ma se ne tengono solo 2
    versions = list_versions(str(dst), "a.txt")
    assert len(versions) == 2

    output = tmp_path / "restored.txt"
    restore_version(str(dst), "a.txt", versions[-1], str(output))
    assert output.read_text() == "v3"  # la penultima versione salvata, non v1 (scartata)


def test_keep_versions_zero_disables_versioning(tmp_path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _write(src / "a.txt", "v1")
    sync_directory(str(src), str(dst), keep_versions=0)

    time.sleep(1.1)
    _write(src / "a.txt", "v2")
    sync_directory(str(src), str(dst), keep_versions=0)

    assert list_versions(str(dst), "a.txt") == []
    assert (dst / "a.txt").read_text() == "v2"


def test_version_restore_with_encryption(tmp_path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _write(src / "segreto.py", "print('versione buona')")

    dek = Fernet.generate_key()
    cipher = Fernet(dek)
    sync_directory(str(src), str(dst), cipher=cipher, keep_versions=3)

    time.sleep(1.1)
    _write(src / "segreto.py", "print('versione modificata')")
    sync_directory(str(src), str(dst), cipher=cipher, keep_versions=3)

    versions = list_versions(str(dst), "segreto.py.enc")
    assert len(versions) == 1

    output = tmp_path / "restored.py"
    restore_version(str(dst), "segreto.py.enc", versions[0], str(output), cipher=cipher)
    assert output.read_text() == "print('versione buona')"
