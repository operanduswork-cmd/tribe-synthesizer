"""Run ledger and monthly budget guard (D12, CLAUDE.md "Money").

Every GPU or CPU run writes two small JSON files on the `tribe-runs` volume:

    ledger/<YYYY-MM>/<run_id>.started.json    before any paid work starts
    ledger/<YYYY-MM>/<run_id>.finished.json   after it ends (done, failed or timeout)

One file per event, so two containers never write the same file (Modal volumes
are last-write-wins per file).

Month-to-date spend counts a finished run at its estimated cost, and a run with
no finished file at its worst case (timeout x rate). So a run that died or hung
still counts against the cap. The guard fails closed: a blank, zero or unreadable
cap, or a resource with no rate, refuses the run.

Pure Python on purpose. The caller reloads the volume before reading and commits
it after writing.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

CAP_ENV = "MONTHLY_BUDGET_CAP_USD"


class BudgetError(RuntimeError):
    """Raised when a run must not start. Never caught silently."""


@dataclass(frozen=True)
class Rates:
    checked: str
    gpu_usd_per_s: dict[str, float]
    cpu_usd_per_core_s: float
    memory_usd_per_gib_s: float

    @classmethod
    def load(cls, path: str | Path) -> "Rates":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        rates = cls(
            checked=raw["checked"],
            gpu_usd_per_s={k: float(v) for k, v in raw["gpu_usd_per_s"].items()},
            cpu_usd_per_core_s=float(raw["cpu_usd_per_core_s"]),
            memory_usd_per_gib_s=float(raw["memory_usd_per_gib_s"]),
        )
        if rates.cpu_usd_per_core_s <= 0 or rates.memory_usd_per_gib_s <= 0:
            raise BudgetError(f"rates file {path} has a zero or negative CPU/memory rate")
        return rates

    def usd_per_s(self, gpu: str | None, cpu_cores: float, memory_gib: float) -> float:
        """Billed rate for one container: GPU (if any) + reserved CPU + reserved memory."""
        rate = cpu_cores * self.cpu_usd_per_core_s + memory_gib * self.memory_usd_per_gib_s
        if gpu is not None:
            if gpu not in self.gpu_usd_per_s or self.gpu_usd_per_s[gpu] <= 0:
                raise BudgetError(f"no rate for GPU {gpu!r} in rates.json; refusing to run")
            rate += self.gpu_usd_per_s[gpu]
        return rate


def read_cap() -> float:
    """The monthly cap in USD, from the `tribe-config` secret. Fails closed."""
    raw = os.environ.get(CAP_ENV, "").strip()
    try:
        cap = float(raw)
    except ValueError:
        raise BudgetError(
            f"{CAP_ENV} is missing or unreadable ({raw!r}). Set it in Modal secret "
            "'tribe-config'. No run starts without a cap."
        ) from None
    if not math.isfinite(cap) or cap <= 0:
        raise BudgetError(f"{CAP_ENV} is {cap}. No run starts without a finite, positive cap.")
    return cap


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def month_key(when: dt.datetime) -> str:
    return when.strftime("%Y-%m")


def month_of(row: dict) -> str:
    """The ledger month folder a started row was filed in."""
    return month_key(dt.datetime.fromisoformat(row["created_at"]))


def _month_dir(ledger_root: Path, when: dt.datetime) -> Path:
    return ledger_root / month_key(when)


def month_to_date_usd(ledger_root: str | Path, when: dt.datetime | None = None) -> float:
    """Spend so far this month. Unfinished runs count at their worst case."""
    month_dir = _month_dir(Path(ledger_root), when or utc_now())
    if not month_dir.exists():
        return 0.0
    started: dict[str, dict] = {}
    finished: dict[str, dict] = {}
    for f in month_dir.glob("*.json"):
        row = json.loads(f.read_text(encoding="utf-8"))
        target = finished if row["event"] == "finished" else started
        target[row["run_id"]] = row
    total = 0.0
    for run_id, row in started.items():
        done = finished.get(run_id)
        total += float(done["estimated_usd"]) if done else float(row["worst_case_usd"])
    # A finished row with no started row should not exist; count it anyway.
    for run_id, row in finished.items():
        if run_id not in started:
            total += float(row["estimated_usd"])
    return total


def start_run(
    ledger_root: str | Path,
    *,
    run_id: str,
    kind: str,
    rates: Rates,
    gpu: str | None,
    cpu_cores: float,
    memory_gib: float,
    timeout_s: int,
    extra: dict | None = None,
) -> dict:
    """Check the cap, then write the started row. Raises BudgetError to refuse.

    The check includes this run's own worst case, so a run can only start if it
    cannot push the month over the cap even if it hangs until its timeout.
    """
    cap = read_cap()
    now = utc_now()
    rate = rates.usd_per_s(gpu, cpu_cores, memory_gib)
    worst = rate * timeout_s
    spent = month_to_date_usd(ledger_root, now)
    if spent + worst > cap:
        raise BudgetError(
            f"refused_budget: month to date ${spent:.2f} + this run's worst case "
            f"${worst:.2f} would pass the ${cap:.2f} cap ({CAP_ENV})."
        )
    row = {
        "event": "started",
        "run_id": run_id,
        "kind": kind,
        "created_at": now.isoformat(),
        "gpu_type": gpu,
        "cpu_cores": cpu_cores,
        "memory_gib": memory_gib,
        "rate_usd_per_s": rate,
        "rates_checked": rates.checked,
        "timeout_s": timeout_s,
        "worst_case_usd": worst,
        "month_to_date_usd_before": spent,
        "monthly_cap_usd": cap,
        **(extra or {}),
    }
    path = _month_dir(Path(ledger_root), now) / f"{run_id}.started.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row, indent=1), encoding="utf-8")
    return row


def finish_run(
    ledger_root: str | Path,
    started_row: dict,
    *,
    status: str,
    billed_seconds: float,
    extra: dict | None = None,
) -> dict:
    """Write the finished row. Call it on success, failure and timeout alike."""
    if status not in {"done", "failed", "timeout"}:
        raise ValueError(f"unknown status {status!r}")
    now = utc_now()
    row = {
        "event": "finished",
        "run_id": started_row["run_id"],
        "kind": started_row["kind"],
        "finished_at": now.isoformat(),
        "status": status,
        "gpu_type": started_row["gpu_type"],
        "billed_seconds": round(billed_seconds, 1),
        "rate_usd_per_s": started_row["rate_usd_per_s"],
        "estimated_usd": billed_seconds * started_row["rate_usd_per_s"],
        **(extra or {}),
    }
    # File the row in the month the run started, so the pair stays together.
    started_at = dt.datetime.fromisoformat(started_row["created_at"])
    path = _month_dir(Path(ledger_root), started_at) / f"{row['run_id']}.finished.json"
    path.write_text(json.dumps(row, indent=1), encoding="utf-8")
    return row
