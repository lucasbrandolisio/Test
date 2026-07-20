import os
import time

from filesync import crypto
from filesync.sync import sync_directory


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def test_basic_copy(tmp_path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _write(src / "a.txt", "hello")
    _write(src / "sub" / "b.txt", "world")

    result = sync_directory(str(src), str(dst))

    assert set(result.copied) == {"a.txt", os.path.join("sub", "b.txt")}
    assert (dst / "a.txt").read_text() == "hello"
    assert (dst / "sub" / "b.txt").read_text() == "world"


def test_skips_unchanged_files(tmp_path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _write(src / "a.txt", "hello")

    sync_directory(str(src), str(dst))
    result = sync_directory(str(src), str(dst))

    assert result.copied == []
    assert result.skipped == 1


def test_updates_modified_file(tmp_path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _write(src / "a.txt", "hello")
    sync_directory(str(src), str(dst))

    time.sleep(1.1)  # garantisce un mtime diverso (risoluzione al secondo)
    _write(src / "a.txt", "hello world")
    result = sync_directory(str(src), str(dst))

    assert result.copied == ["a.txt"]
    assert (dst / "a.txt").read_text() == "hello world"


def test_mirror_deletes_removed_files(tmp_path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _write(src / "a.txt", "hello")
    _write(src / "b.txt", "world")
    sync_directory(str(src), str(dst), mirror=True)

    os.remove(src / "b.txt")
    result = sync_directory(str(src), str(dst), mirror=True)

    assert result.deleted == ["b.txt"]
    assert not (dst / "b.txt").exists()
    assert (dst / "a.txt").exists()


def test_non_mirror_keeps_removed_files(tmp_path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _write(src / "a.txt", "hello")
    _write(src / "b.txt", "world")
    sync_directory(str(src), str(dst), mirror=False)

    os.remove(src / "b.txt")
    result = sync_directory(str(src), str(dst), mirror=False)

    assert result.deleted == []
    assert (dst / "b.txt").exists()


def test_exclude_patterns(tmp_path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _write(src / "keep.txt", "keep")
    _write(src / "ignore.tmp", "ignore")
    _write(src / ".git" / "config", "ignore")

    sync_directory(str(src), str(dst), exclude=["*.tmp", ".git"])

    assert (dst / "keep.txt").exists()
    assert not (dst / "ignore.tmp").exists()
    assert not (dst / ".git").exists()


def test_dry_run_changes_nothing(tmp_path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _write(src / "a.txt", "hello")

    result = sync_directory(str(src), str(dst), dry_run=True)

    assert result.copied == ["a.txt"]
    assert not (dst / "a.txt").exists()


def test_sync_with_encryption_round_trip(tmp_path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _write(src / "secret.txt", "codice sorgente segreto")

    cipher = crypto.make_cipher("supersegreta", str(dst))
    result = sync_directory(str(src), str(dst), cipher=cipher)

    assert result.copied == ["secret.txt"]
    enc_path = dst / "secret.txt.enc"
    assert enc_path.exists()
    assert b"codice sorgente segreto" not in enc_path.read_bytes()

    plaintext = crypto.decrypt_bytes(cipher, enc_path.read_bytes())
    assert plaintext.decode("utf-8") == "codice sorgente segreto"


def test_sync_with_encryption_skips_unchanged(tmp_path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _write(src / "secret.txt", "dato")

    cipher = crypto.make_cipher("pw", str(dst))
    sync_directory(str(src), str(dst), cipher=cipher)
    result = sync_directory(str(src), str(dst), cipher=cipher)

    assert result.copied == []
    assert result.skipped == 1
