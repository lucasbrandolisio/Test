import datetime
import os

from filesync.config import Job, Vault
from filesync.traylogic import (
    UnlockWarningTracker,
    format_sync_summary,
    is_workspace_unlocked,
    run_sync_cycle,
)


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def test_run_sync_cycle_reports_success_and_failure(tmp_path):
    src_ok = tmp_path / "src_ok"
    dst_ok = tmp_path / "dst_ok"
    _write(src_ok / "a.txt", "ciao")

    jobs = [
        Job(name="OK", source=str(src_ok), destination=str(dst_ok)),
        Job(name="Rotto", source=str(tmp_path / "non_esiste"), destination=str(tmp_path / "dst2")),
    ]

    outcomes = run_sync_cycle(jobs)

    assert outcomes[0].ok is True
    assert outcomes[0].result.copied == ["a.txt"]
    assert outcomes[1].ok is False
    assert "non trovata" in outcomes[1].error


def test_format_sync_summary_none_when_nothing_relevant(tmp_path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _write(src / "a.txt", "ciao")
    jobs = [Job(name="OK", source=str(src), destination=str(dst))]

    run_sync_cycle(jobs)  # primo giro: copia
    outcomes = run_sync_cycle(jobs)  # secondo giro: nulla di nuovo

    assert format_sync_summary(outcomes) is None


def test_format_sync_summary_reports_errors_and_changes(tmp_path):
    src = tmp_path / "src"
    _write(src / "a.txt", "ciao")
    jobs = [
        Job(name="OK", source=str(src), destination=str(tmp_path / "dst")),
        Job(name="Rotto", source=str(tmp_path / "manca"), destination=str(tmp_path / "dst2")),
    ]

    outcomes = run_sync_cycle(jobs)
    summary = format_sync_summary(outcomes)

    assert summary is not None
    assert "Rotto" in summary
    assert "OK" in summary


def test_is_workspace_unlocked(tmp_path):
    v = Vault(name="V", workspace=str(tmp_path / "ws"), vault=str(tmp_path / "vault"))
    assert is_workspace_unlocked(v) is False  # non esiste

    os.makedirs(v.workspace)
    assert is_workspace_unlocked(v) is False  # esiste ma vuota

    _write(os.path.join(v.workspace, "main.py"), "codice")
    assert is_workspace_unlocked(v) is True


def test_unlock_warning_tracker_warns_after_threshold(tmp_path):
    v = Vault(name="V", workspace=str(tmp_path / "ws"), vault=str(tmp_path / "vault"), warn_after_minutes=10)
    _write(os.path.join(v.workspace, "main.py"), "codice")

    tracker = UnlockWarningTracker()
    t0 = datetime.datetime(2026, 1, 1, 12, 0, 0)

    assert tracker.check(v, now=t0) is None  # appena sbloccato, troppo presto
    assert tracker.check(v, now=t0 + datetime.timedelta(minutes=5)) is None

    message = tracker.check(v, now=t0 + datetime.timedelta(minutes=11))
    assert message is not None
    assert "V" in message

    # non ripete subito il promemoria...
    assert tracker.check(v, now=t0 + datetime.timedelta(minutes=15)) is None
    # ...ma lo ripete dopo un altro intervallo di warn_after_minutes
    message2 = tracker.check(v, now=t0 + datetime.timedelta(minutes=22))
    assert message2 is not None


def test_unlock_warning_tracker_resets_when_relocked(tmp_path):
    v = Vault(name="V", workspace=str(tmp_path / "ws"), vault=str(tmp_path / "vault"), warn_after_minutes=10)
    _write(os.path.join(v.workspace, "main.py"), "codice")

    tracker = UnlockWarningTracker()
    t0 = datetime.datetime(2026, 1, 1, 12, 0, 0)
    tracker.check(v, now=t0 + datetime.timedelta(minutes=11))
    assert v.name in tracker.unlocked_since

    import shutil
    shutil.rmtree(v.workspace)  # simula 'lock'

    tracker.check(v, now=t0 + datetime.timedelta(minutes=12))
    assert v.name not in tracker.unlocked_since
    assert v.name not in tracker.last_warned
