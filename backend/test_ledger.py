"""Local tests for the budget guard. Run: python -m pytest backend/test_ledger.py
(or plain: python backend/test_ledger.py). No Modal, no network, no spend."""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ledger  # noqa: E402

RATES_FILE = Path(__file__).parent / "rates.json"


def _rates():
    return ledger.Rates.load(RATES_FILE)


def _gpu_run(root, run_id, timeout_s=1800):
    return ledger.start_run(
        root, run_id=run_id, kind="predict", rates=_rates(), gpu="A10G",
        cpu_cores=4, memory_gib=24, timeout_s=timeout_s,
    )


def _expect_refused(fn):
    try:
        fn()
    except ledger.BudgetError as e:
        return str(e)
    raise AssertionError("expected BudgetError")


def test_blank_zero_and_garbage_cap_refuse():
    with tempfile.TemporaryDirectory() as root:
        for value in ["", "0", "-5", "abc", "nan", "inf", "Infinity"]:
            os.environ[ledger.CAP_ENV] = value
            _expect_refused(lambda: _gpu_run(root, "r1"))
        os.environ.pop(ledger.CAP_ENV)
        _expect_refused(lambda: _gpu_run(root, "r1"))
        assert not any(Path(root).rglob("*.json")), "a refused run must not write a row"


def test_unknown_gpu_refuses():
    os.environ[ledger.CAP_ENV] = "30"
    with tempfile.TemporaryDirectory() as root:
        msg = _expect_refused(lambda: ledger.start_run(
            root, run_id="r1", kind="predict", rates=_rates(), gpu="B200",
            cpu_cores=4, memory_gib=24, timeout_s=1800))
        assert "B200" in msg


def test_unfinished_run_counts_at_worst_case_and_finished_at_estimate():
    os.environ[ledger.CAP_ENV] = "30"
    with tempfile.TemporaryDirectory() as root:
        row = _gpu_run(root, "r1")
        assert abs(ledger.month_to_date_usd(root) - row["worst_case_usd"]) < 1e-9
        ledger.finish_run(root, row, status="done", billed_seconds=600)
        assert abs(ledger.month_to_date_usd(root) - 600 * row["rate_usd_per_s"]) < 1e-9


def test_failed_run_still_costs():
    os.environ[ledger.CAP_ENV] = "30"
    with tempfile.TemporaryDirectory() as root:
        row = _gpu_run(root, "r1")
        ledger.finish_run(root, row, status="failed", billed_seconds=120)
        assert ledger.month_to_date_usd(root) > 0


def test_cap_includes_this_runs_worst_case():
    with tempfile.TemporaryDirectory() as root:
        rate = _rates().usd_per_s("A10G", 4, 24)
        # Cap just under one worst case: refuse before anything is spent.
        os.environ[ledger.CAP_ENV] = str(rate * 1800 * 0.99)
        _expect_refused(lambda: _gpu_run(root, "r1"))
        # Cap fits one worst case but not two: second run refused while the first is unfinished.
        os.environ[ledger.CAP_ENV] = str(rate * 1800 * 1.5)
        _gpu_run(root, "r1")
        _expect_refused(lambda: _gpu_run(root, "r2"))


def test_rows_are_valid_json_files_per_event():
    os.environ[ledger.CAP_ENV] = "30"
    with tempfile.TemporaryDirectory() as root:
        row = _gpu_run(root, "r1")
        ledger.finish_run(root, row, status="timeout", billed_seconds=1800)
        files = sorted(p.name for p in Path(root).rglob("*.json"))
        assert files == ["r1.finished.json", "r1.started.json"]
        for p in Path(root).rglob("*.json"):
            json.loads(p.read_text(encoding="utf-8"))


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
