from typing import TYPE_CHECKING

from django.contrib.gis.db import models
from django.db.models import F, Q
from django.db.models.functions import Now
from django.utils import timezone

from wuixpose.core.constants import STORAGE_SRID

if TYPE_CHECKING:
    # RelatedManager exists only in the type stubs.
    from django.db.models.manager import RelatedManager

    from .addresses import Address
    from .structures import Structure


class Tract(models.Model):
    """Any defined area of land under management on which mitigation can be performed or delegated."""

    geom = models.MultiPolygonField(srid=STORAGE_SRID)
    # When this row's geometry last changed. Maintained by a database trigger (migration 0003),
    # so every writer gets it, including bulk updates and raw SQL; values written from Python
    # are ignored. Jobs that depend on geometry use it to find what changed since their last run.
    geom_updated_at = models.DateTimeField(db_default=Now(), db_index=True, editable=False)

    # Reverse relations, declared for the type checker; Django adds them at runtime.
    addresses: "RelatedManager[Address]"
    identifiers: "RelatedManager[TractIdentifier]"
    structures: "RelatedManager[Structure]"

    def __str__(self) -> str:
        return f"Tract {self.pk}"


class TractIdentifier(models.Model):
    """An external identifier a tract has carried (county APN first). A tract may have none or many."""

    class Scheme(models.TextChoices):
        COUNTY_APN = "county_apn", "County APN"

    tract = models.ForeignKey(Tract, on_delete=models.CASCADE, related_name="identifiers")
    tract_id: int
    scheme = models.CharField(max_length=32, choices=Scheme.choices, db_collation="C")
    county_fips = models.CharField(max_length=5, db_collation="C")
    value = models.CharField(max_length=64, db_collation="C")
    # WUIXpose's own dates, not the county's dates of record: an identifier is tracked from the
    # day we loaded it until the day an ingest no longer finds it. Ingests pass their run date so
    # every row from one run shares it; the default covers anything else that creates rows.
    tracked_from = models.DateField(default=timezone.localdate)
    tracked_to = models.DateField(null=True, blank=True)  # null = current

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=("scheme", "county_fips", "value"),
                condition=Q(tracked_to__isnull=True),
                name="uniq_current_tract_identifier",
            ),
            models.CheckConstraint(
                condition=Q(county_fips__regex=r"^\d{5}$"),
                name="tract_identifier_fips_format",
            ),
            models.CheckConstraint(
                condition=Q(tracked_to__isnull=True) | Q(tracked_to__gte=F("tracked_from")),
                name="tract_identifier_tracked_range",
            ),
        )
        indexes = (
            # Historical rows only; the unique constraint above covers current ones.
            models.Index(
                fields=("scheme", "county_fips", "value"),
                condition=Q(tracked_to__isnull=False),
                name="tract_identifier_history",
            ),
        )

    def __str__(self) -> str:
        return f"{self.scheme}:{self.county_fips}:{self.value}"
