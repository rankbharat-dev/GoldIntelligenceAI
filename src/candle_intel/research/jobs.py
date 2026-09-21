"""Job queue for long research work (backtest, optimise, validate, holdout).

Jobs are rows in the ledger (``research_jobs``) so the UI can follow them across page
reloads; they run on one worker thread inside the API process — one at a time, in
order, so results never compete for memory and stay reproducible. If the API stops,
running jobs are marked *interrupted* at the next start (they are not resumed: a
partial result is never shown as a finished one).
"""

from __future__ import annotations

import logging
import secrets
import threading
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from candle_intel.research.ledger import Ledger

log = logging.getLogger(__name__)

Work = Callable[[Callable[[float, str], None]], dict[str, Any]]


class Cancelled(Exception):
    pass


class JobRunner:
    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ci-job")
        self.cancel_flags: dict[str, threading.Event] = {}
        n = ledger.jobs_interrupted()
        if n:
            log.warning("%d job(s) were interrupted by the last shutdown", n)

    def submit(self, kind: str, title: str, params: dict[str, Any], work: Work) -> str:
        job_id = f"job_{datetime.now(UTC):%Y%m%dT%H%M%S}_{secrets.token_hex(3)}"
        self.ledger.job_create(job_id, kind, title[:160], params)
        flag = threading.Event()
        self.cancel_flags[job_id] = flag
        self.pool.submit(self._run, job_id, work, flag)
        return job_id

    def cancel(self, job_id: str) -> bool:
        flag = self.cancel_flags.get(job_id)
        if flag is None:
            return False
        flag.set()
        job = self.ledger.job(job_id)
        if job and job["status"] == "queued":
            self.ledger.job_update(
                job_id, status="cancelled", message="cancelled before start", finished_at=_now()
            )
        return True

    def _run(self, job_id: str, work: Work, flag: threading.Event) -> None:
        if flag.is_set():
            return
        self.ledger.job_update(job_id, status="running", started_at=_now(), message="starting")
        last = [0.0]

        def progress(frac: float, msg: str) -> None:
            if flag.is_set():
                raise Cancelled
            frac = max(0.0, min(1.0, float(frac)))
            # throttle writes: every 2 % or a new message
            if frac - last[0] >= 0.02 or frac in (0.0, 1.0):
                last[0] = frac
                self.ledger.job_update(job_id, progress=frac, message=msg[:300])

        try:
            result = work(progress)
            self.ledger.job_update(
                job_id, status="done", progress=1.0, message="done", result=result, finished_at=_now()
            )
        except Cancelled:
            self.ledger.job_update(job_id, status="cancelled", message="cancelled", finished_at=_now())
        except Exception as e:  # noqa: BLE001 — a job failure is reported, never raised into the pool
            log.exception("job %s failed", job_id)
            self.ledger.job_update(
                job_id,
                status="failed",
                message=str(e).splitlines()[0][:300] if str(e) else type(e).__name__,
                error=traceback.format_exc()[-4000:],
                finished_at=_now(),
            )
        finally:
            self.cancel_flags.pop(job_id, None)


def _now() -> datetime:
    return datetime.now(UTC)
