import os
import stat

import pytest

from filesync import protect


def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def test_protect_posix_restricts_permissions(tmp_path):
    folder = tmp_path / "progetto"
    folder.mkdir()
    (folder / "sub").mkdir()
    (folder / "main.py").write_text("print('segreto')")
    (folder / "sub" / "lib.py").write_text("x = 1")

    os.chmod(folder / "main.py", 0o644)
    os.chmod(folder / "sub" / "lib.py", 0o644)
    os.chmod(folder / "sub", 0o755)

    count = protect.protect_posix(str(folder))

    assert count == 2
    assert _mode(folder) == protect.DIR_MODE
    assert _mode(folder / "sub") == protect.DIR_MODE
    assert _mode(folder / "main.py") == protect.FILE_MODE
    assert _mode(folder / "sub" / "lib.py") == protect.FILE_MODE


def test_unprotect_restores_original_permissions(tmp_path):
    folder = tmp_path / "progetto"
    folder.mkdir()
    (folder / "main.py").write_text("print('segreto')")
    os.chmod(folder / "main.py", 0o644)
    os.chmod(folder, 0o755)

    protect.protect_posix(str(folder))
    count = protect.unprotect_posix(str(folder))

    assert count >= 2  # cartella + file
    assert _mode(folder) == 0o755
    assert _mode(folder / "main.py") == 0o644


def test_unprotect_without_prior_protect_raises(tmp_path):
    folder = tmp_path / "progetto"
    folder.mkdir()

    with pytest.raises(FileNotFoundError):
        protect.unprotect_posix(str(folder))
