from django.contrib.gis.db import models
from django.db.models import F, Q

# Geometries are stored as longitude/latitude in degrees (SRID 4326, the GPS standard).
# A degree is not a fixed distance: it's ~364,000 ft north-south everywhere, but east-west
# it shrinks toward the poles (~280,000 ft in Colorado). So never buffer or measure
# directly on these geometries, e.g. geom.buffer(5) means 5 *degrees*, not 5 feet.
# For distances, first convert the geometry to a projected coordinate system that
# uses meters (geom.transform(<local UTM SRID>)), or cast to PostGIS `geography`,
# which measures in meters on the Earth's surface.
STORAGE_SRID = 4326


class Tract(models.Model):
    """Any defined area of land under management on which mitigation can be performed or delegated."""
    geom = models.MultiPolygonField(srid=STORAGE_SRID)

    def __str__(self) -> str:
        return f"Tract {self.pk}"


class TractIdentifierQuerySet(models.QuerySet):
    def lookup(self, county_fips: str, value: str, scheme: str = "county_apn", *, include_history=False):
        """Find identifiers by (scheme, county, value) in a form that can use the partial indexes.

        Postgres only uses a partial index when the WHERE clause implies its predicate, so a bare
        (scheme, county_fips, value) filter uses neither index below. Spelling out both validity
        cases lets the planner BitmapOr the two.
        """
        key = Q(scheme=scheme, county_fips=county_fips, value=value)

        if not include_history:
            return self.filter(key, valid_to__isnull=True)
        return self.filter((key & Q(valid_to__isnull=True)) | (key & Q(valid_to__isnull=False)))


class TractIdentifier(models.Model):
    """An external identifier a tract has carried (county APN first). A tract may have none or many."""

    class Scheme(models.TextChoices):
        COUNTY_APN = "county_apn", "County APN"

    tract = models.ForeignKey(Tract, on_delete=models.CASCADE, related_name="identifiers")
    scheme = models.CharField(max_length=32, choices=Scheme.choices, db_collation="C")
    county_fips = models.CharField(max_length=5, db_collation="C")
    value = models.CharField(max_length=64, db_collation="C")
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)  # null = current

    objects = TractIdentifierQuerySet.as_manager()

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=("scheme", "county_fips", "value"),
                condition=Q(valid_to__isnull=True),
                name="uniq_current_tract_identifier",
            ),
            models.CheckConstraint(
                condition=Q(county_fips__regex=r"^\d{5}$"),
                name="tract_identifier_fips_format",
            ),
            models.CheckConstraint(
                condition=Q(valid_from__isnull=True) | Q(valid_to__isnull=True) | Q(valid_to__gte=F("valid_from")),
                name="tract_identifier_valid_range",
            ),
        )
        indexes = (
            # Historical rows only; the unique constraint above covers current ones.
            models.Index(
                fields=("scheme", "county_fips", "value"),
                condition=Q(valid_to__isnull=False),
                name="tract_identifier_history",
            ),
        )

    def __str__(self) -> str:
        return f"{self.scheme}:{self.county_fips}:{self.value}"
