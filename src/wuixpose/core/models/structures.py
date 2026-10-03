from django.contrib.gis.db import models

from .tracts import STORAGE_SRID


class Structure(models.Model):
    """A building, identified by its footprint."""

    geom = models.MultiPolygonField(srid=STORAGE_SRID)
    # Assigned by spatial join at ingest. Null when no single tract is a clear match
    # (footprint straddles a lot line, falls in a gap in the parcel data).
    tract = models.ForeignKey(
        "core.Tract",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="structures",
    )

    def __str__(self) -> str:
        return f"Structure {self.pk}"


class Zone(models.Model):
    """One ring around one structure, computed in code from the structure's footprint.

    Rows are never rewritten when ring rules change: a new rule_version produces new rows, so
    observations taken on old geometry stay attached to that geometry. Not clipped to tracts.
    """

    structure = models.ForeignKey(Structure, on_delete=models.CASCADE, related_name="zones")
    ring_key = models.CharField(max_length=32, db_collation="C")  # e.g. "hiz_0_5"; defined in code
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
