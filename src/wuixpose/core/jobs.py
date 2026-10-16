"""Jobs that process only what changed since their last successful run (see JobRun)."""

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime

from django.db import connection, transaction
from django.db.backends.utils import CursorWrapper

from wuixpose.core.models import JobRun


@dataclass
class IncrementalRun:
    cursor: CursorWrapper
    since: datetime | None  # None: process everything
    rows_changed: int = 0  # set by the job before the run ends

    @property
    def full(self) -> bool:
        return self.since is None


@contextmanager
def incremental_run(job: JobRun.Job, *, full: bool = False) -> Generator[IncrementalRun]:
    """Run a job's work in one transaction, recording a JobRun if it commits.

    The run's `since` is the job's watermark: the start of its last successful run, or None for
    the first run or with `full`. The job processes rows whose geom_updated_at is at or after it.
    """
    with transaction.atomic(), connection.cursor() as cursor:
        # One run at a time, so two runs can't interleave their watermarks.
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [job])
        # The transaction's start, the same clock the geom_updated_at trigger stamps with.
        cursor.execute("SELECT now()")
        row = cursor.fetchone()
        assert row is not None  # now() always returns a row
        (started_at,) = row
        since = (
            None
            if full
            else JobRun.objects.filter(job=job)
            .order_by("-started_at")
            .values_list("started_at", flat=True)
            .first()
        )
        run = IncrementalRun(cursor=cursor, since=since)
        yield run
        JobRun.objects.create(
            job=job, started_at=started_at, full=run.full, rows_changed=run.rows_changed
        )
