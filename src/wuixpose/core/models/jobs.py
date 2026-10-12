from django.db import models
from django.db.models.functions import Now


class JobRun(models.Model):
    """One successful run of a job that processes changes since its previous run.

    A job records its run in the same transaction as its work, so the row exists only if the work
    committed. The latest started_at for a job is its watermark: the next run picks up rows whose
    geom_updated_at is at or after it.
    """

    class Job(models.TextChoices):
        ASSIGN_STRUCTURE_TRACTS = "assign_structure_tracts", "Assign structures to tracts"

    job = models.CharField(max_length=64, choices=Job.choices, db_collation="C")
    # Jobs set this to the database's now() (their transaction's start), the clock the
    # geom_updated_at trigger uses, so it's comparable regardless of the app server's clock. The
    # default is a fallback only: Django's Now() is the statement's time, not the transaction's.
    started_at = models.DateTimeField(db_default=Now())
    full = models.BooleanField(default=False)  # processed everything rather than changes
    rows_changed = models.PositiveIntegerField()

    class Meta:
        indexes = (models.Index(fields=("job", "-started_at"), name="job_run_latest"),)

    def __str__(self) -> str:
        return f"{self.job} at {self.started_at}"
