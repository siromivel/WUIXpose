from django.contrib.gis.db import models
from django.db.models import Q
from django.db.models.functions import Now

from .tracts import STORAGE_SRID


class Structure(models.Model):
    """A building, identified by its footprint."""

    class Source(models.TextChoices):
        BOCO_FOOTPRINTS = "boco_footprints", "Boulder County building footprints"

    geom = models.MultiPolygonField(srid=STORAGE_SRID)
    # Where the footprint came from and its ID there, so re-ingesting updates rather than
    # duplicates. Both null for structures with no upstream record.
    source = models.CharField(max_length=32, choices=Source.choices, null=True, blank=True, db_collation="C")
    source_id = models.CharField(max_length=64, null=True, blank=True, db_collation="C")
    # Assigned by spatial join at ingest. Null when no single tract is a clear match
    # (footprint straddles a lot line, falls in a gap in the parcel data).
    tract = models.ForeignKey(
        "core.Tract",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="structures",
    )
    # When this row's geometry last changed. Maintained by a database trigger (migration 0003),
    # so every writer gets it, including bulk updates and raw SQL; values written from Python
    # are ignored. Jobs that depend on geometry use it to find what changed since their last run.
    geom_updated_at = models.DateTimeField(db_default=Now(), db_index=True, editable=False)

    class Meta:
        constraints = (
            models.UniqueConstraint(fields=("source", "source_id"), name="uniq_structure_source_id"),
            models.CheckConstraint(
                condition=Q(source__isnull=True, source_id__isnull=True)
                | Q(source__isnull=False, source_id__isnull=False),
                name="structure_source_id_paired",
            ),
        )

    def __str__(self) -> str:
        return f"Structure {self.pk}"


class Zone(models.Model):
    """One ring around one structure, computed in code from the structure's footprint (zones.py).

    Rows are never rewritten when ring rules change: a new rule_version produces new rows, so
    observations taken on old geometry stay attached to that geometry. A row is rewritten when
    its structure's footprint changes. Not clipped to tracts, nor to neighboring structures'
    zones, so zones of nearby structures overlap.
    """

    structure = models.ForeignKey(Structure, on_delete=models.CASCADE, related_name="zones")
    ring_key = models.CharField(max_length=32, db_collation="C")  # e.g. "hiz_0_5"; zones.RINGS
    rule_version = models.PositiveIntegerField()
    geom = models.MultiPolygonField(srid=STORAGE_SRID)

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=("structure", "ring_key", "rule_version"),
                name="uniq_zone_per_structure_ring_version",
            ),
        )

    def __str__(self) -> str:
        return f"{self.ring_key} v{self.rule_version} of structure {self.structure_id}"
