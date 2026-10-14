from django.db import models


class RejectedFeature(models.Model):
    """A feature from an upstream layer that an ingest couldn't load, kept for someone to look into.

    One row per distinct feature content per layer. Rejecting the same feature again on a later
    run only brings last_seen_at (and reason, if the rules changed) up to date; once the provider
    fixes it, the fixed feature loads and the old row stops being seen. Written in the load's
    transaction, so a load that fails records nothing.
    """

    class Layer(models.TextChoices):
        BOCO_PARCELS = "boco_parcels", "Boulder County parcels"
        BOCO_FOOTPRINTS = "boco_footprints", "Boulder County building footprints"

    class Reason(models.TextChoices):
        MISSING_ID = "missing_id", "No source ID"
        UNREADABLE_GEOMETRY = "unreadable_geometry", "Geometry can't be parsed or repaired"
        NOT_POLYGONAL = "not_polygonal", "Nothing polygonal left after repair"

    layer = models.CharField(max_length=32, choices=Layer.choices, db_collation="C")
    source_id = models.CharField(max_length=64, null=True, blank=True, db_collation="C")
    reason = models.CharField(max_length=32, choices=Reason.choices, db_collation="C")
    detail = models.TextField(blank=True)  # e.g. the GDAL/GEOS error
    feature = models.JSONField()  # the GeoJSON feature as received
    feature_hash = models.CharField(max_length=64, db_collation="C")  # SHA-256 of `feature`
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()

    class Meta:
        constraints = (models.UniqueConstraint(fields=("layer", "feature_hash"), name="uniq_rejected_feature"),)

    def __str__(self) -> str:
        return f"{self.layer}:{self.source_id or '?'} ({self.reason})"
