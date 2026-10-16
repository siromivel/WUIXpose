from typing import ClassVar, Self

from django.contrib.gis.db import models
from django.contrib.postgres.indexes import GinIndex
from django.db.models import F, Q
from django.utils import timezone

from wuixpose.core.constants import STORAGE_SRID


class AddressQuerySet(models.QuerySet["Address"]):
    def current(self) -> Self:
        return self.filter(tracked_to__isnull=True)


class Address(models.Model):
    """A site address: a point a street address is assigned to, as an addressing authority keeps it.

    Text is stored as the source publishes it (Boulder County: upper case, unabbreviated city
    names); display.py formats it.

    Retired addresses are kept, with tracked_to set and their details as last published while
    active, so history can refer to them. Most queries want Address.objects.current().
    """

    class Source(models.TextChoices):
        BOCO_ADDRESS_POINTS = "boco_address_points", "Boulder County address points"

    geom = models.PointField(srid=STORAGE_SRID)
    # Where the address came from and its ID there, as on Structure.
    source = models.CharField(
        max_length=32, choices=Source.choices, null=True, blank=True, db_collation="C"
    )
    source_id = models.CharField(max_length=64, null=True, blank=True, db_collation="C")

    number = models.CharField(max_length=32)  # "1172", "1172 1/2", "MM40.7" (a highway mile marker)
    street = models.CharField(max_length=128)  # "S BOULDER RD", "COUNTY ROAD 128J"
    unit = models.CharField(max_length=32, blank=True)  # "APT 106", "#206"
    # The city the address is in, or e.g. "UNINCORPORATED BOULDER COUNTY". Not always the city
    # the post office uses: a Gold Hill address is unincorporated with a Boulder mailing address.
    jurisdiction = models.CharField(max_length=64, blank=True)
    state = models.CharField(max_length=2)
    zip_code = models.CharField(max_length=5, blank=True)
    # Number, street, unit and jurisdiction, normalized for search (search.address_search_text).
    # Derived; written at ingest along with the fields it comes from.
    search_text = models.TextField(blank=True, default="")

    # The parcel the source says the address is on, matched against TractIdentifier to find the
    # tract. Kept as published, so a parcel number we don't track yet can match later.
    county_fips = models.CharField(max_length=5, null=True, blank=True, db_collation="C")
    county_apn = models.CharField(max_length=64, null=True, blank=True, db_collation="C")
    # Derived from county_apn, falling back to location (see assignment.link_address_tracts).
    tract = models.ForeignKey(
        "core.Tract",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="addresses",
    )
    tract_id: int | None

    # WUIXpose's own dates, as on TractIdentifier: from the day we first loaded the address until
    # the day an ingest found it retired or gone. Cleared if it comes back; tracked_from stays.
    tracked_from = models.DateField(default=timezone.localdate)
    tracked_to = models.DateField(null=True, blank=True)  # null = current

    # The stubs type as_manager() as a plain Manager, losing current(). The manager it builds
    # proxies the queryset's methods, and the stubs already model Manager as a QuerySet, so
    # typing it as the queryset lets current() type-check, including after filter() and the like.
    objects: ClassVar[AddressQuerySet] = AddressQuerySet.as_manager()  # pyright: ignore[reportAssignmentType, reportIncompatibleVariableOverride]

    class Meta:
        constraints = (
            models.UniqueConstraint(fields=("source", "source_id"), name="uniq_address_source_id"),
            models.CheckConstraint(
                condition=Q(source__isnull=True, source_id__isnull=True)
                | Q(source__isnull=False, source_id__isnull=False),
                name="address_source_id_paired",
            ),
            models.CheckConstraint(
                condition=Q(county_apn__isnull=True) | Q(county_fips__regex=r"^\d{5}$"),
                name="address_apn_has_county",
            ),
            models.CheckConstraint(
                condition=Q(tracked_to__isnull=True) | Q(tracked_to__gte=F("tracked_from")),
                name="address_tracked_range",
            ),
        )
        indexes = (
            # Trigram matching for search, which only ever looks at current addresses.
            GinIndex(
                fields=["search_text"],
                opclasses=["gin_trgm_ops"],
                condition=Q(tracked_to__isnull=True),
                name="address_search_trgm",
            ),
        )

    def __str__(self) -> str:
        # As stored, not as displayed: models don't import services (display.py formats it).
        return " ".join(part for part in (self.number, self.street, self.unit) if part)
