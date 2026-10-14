import re

from django.contrib.gis.db import models
from django.db.models import Q

from .tracts import STORAGE_SRID

DIRECTIONALS = frozenset({"N", "S", "E", "W", "NE", "NW", "SE", "SW"})
ORDINAL = re.compile(r"^(\d+)(ST|ND|RD|TH)$")


def _display_case(text: str) -> str:
    """Title-case an address as the county publishes it (upper case) for display.

    "S 2ND ST" -> "S 2nd St", "COUNTY ROAD 128J" -> "County Road 128J", "MCCASLIN" -> "McCaslin".
    Other names with inner capitals come out wrong ("DEVINNEY" stays "Devinney" even where it
    should be "DeVinney"); the stored text stays as published.
    """
    words = []
    for word in text.split():
        if word in DIRECTIONALS:
            words.append(word)
        elif ordinal := ORDINAL.match(word):
            words.append(ordinal[1] + ordinal[2].lower())
        elif word[0].isdigit():
            words.append(word)
        elif word.startswith("MC") and len(word) > 2 and word[2].isalpha():
            words.append("Mc" + word[2:].title())
        else:
            words.append(word.title())
    return " ".join(words)


class Address(models.Model):
    """A site address: a point a street address is assigned to, as an addressing authority keeps it.

    Text is stored as the source publishes it (Boulder County: upper case, unabbreviated city
    names); display_* methods format it.
    """

    class Source(models.TextChoices):
        BOCO_ADDRESS_POINTS = "boco_address_points", "Boulder County address points"

    geom = models.PointField(srid=STORAGE_SRID)
    # Where the address came from and its ID there, as on Structure.
    source = models.CharField(max_length=32, choices=Source.choices, null=True, blank=True, db_collation="C")
    source_id = models.CharField(max_length=64, null=True, blank=True, db_collation="C")

    number = models.CharField(max_length=32)  # "1172", "1172 1/2", "MM40.7" (a highway mile marker)
    street = models.CharField(max_length=128)  # "S BOULDER RD", "COUNTY ROAD 128J"
    unit = models.CharField(max_length=32, blank=True)  # "APT 106", "#206"
    # The city the address is in, or e.g. "UNINCORPORATED BOULDER COUNTY". Not always the city
    # the post office uses: a Gold Hill address is unincorporated with a Boulder mailing address.
    jurisdiction = models.CharField(max_length=64, blank=True)
    state = models.CharField(max_length=2)
    zip_code = models.CharField(max_length=5, blank=True)

    # The parcel the source says the address is on, matched against TractIdentifier to find the
    # tract. Kept as published, so a parcel number we don't track yet can match later.
    county_fips = models.CharField(max_length=5, null=True, blank=True, db_collation="C")
    county_apn = models.CharField(max_length=64, null=True, blank=True, db_collation="C")
    # Derived from county_apn, falling back to location (see ingest.boulder.link_address_tracts).
    tract = models.ForeignKey(
        "core.Tract",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="addresses",
    )

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
        )

    def __str__(self) -> str:
        return self.display_line1()

    def display_line1(self) -> str:
        """Number, street and unit: "1172 Valley Ln", "2211 Pratt St #206"."""
        line = _display_case(f"{self.number} {self.street}")
        if self.unit:
            line += f" {_display_case(str(self.unit))}"
        return line

    def display_line2(self) -> str:
        """Jurisdiction, state and ZIP: "Unincorporated Boulder County, CO 80302"."""
        state_zip = f"{self.state} {self.zip_code}".strip()
        return ", ".join(part for part in (_display_case(str(self.jurisdiction)), state_zip) if part)
