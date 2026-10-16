"""Address search: typo-tolerant lookup of current addresses by what a person would type.

Addresses carry a normalized search_text, written at ingest by address_search_text, and queries
go through the same normalize, so "South Boulder Road" and "S BOULDER RD" are the same words on
both sides. Postgres trigram word similarity (pg_trgm) then copes with typos and partial input,
using a GIN index on search_text.

The GIN index makes specific queries ("1172 valley") take about a millisecond countywide. Broad
ones take a few hundred: "boulder" is in most addresses' jurisdiction, so tens of thousands of
rows match and are all ranked.
"""

import re

from django.contrib.postgres.search import (
    # Django has had it since 3.2; the django-types stubs haven't caught up.
    TrigramWordSimilarity,  # pyright: ignore[reportAttributeAccessIssue]
)
from django.db.models import Case, F, Value, When
from django.db.models.functions import Length

from wuixpose.core.models import Address

# Each word maps to its canonical form, chosen to match how the county publishes most addresses
# (abbreviated types and directionals), so most stored text is unchanged. Collisions are
# harmless as long as both sides go through the same table: SAINT and STREET both become ST.
WORDS = {
    # Directionals. The county writes them out inside names ("SOUTH BOULDER RD").
    "NORTH": "N",
    "SOUTH": "S",
    "EAST": "E",
    "WEST": "W",
    "NORTHEAST": "NE",
    "NORTHWEST": "NW",
    "SOUTHEAST": "SE",
    "SOUTHWEST": "SW",
    # Street types.
    "ALY": "ALLEY",
    "AV": "AVE",
    "AVENUE": "AVE",
    "BOULEVARD": "BLVD",
    "CIRCLE": "CIR",
    "COURT": "CT",
    "DRIVE": "DR",
    "HIGHWAY": "HWY",
    "LANE": "LN",
    "PARKWAY": "PKWY",
    "PLACE": "PL",
    "ROAD": "RD",
    "ROUTE": "RTE",
    "SQUARE": "SQ",
    "STREET": "ST",
    "TERRACE": "TER",
    "TRAIL": "TRL",
    # Words in names.
    "FORT": "FT",
    "MOUNT": "MT",
    "SAINT": "ST",
    # Spelled-out ordinals, as in "FOURTH OF JULY RD"; the county mostly uses "2ND".
    "FIRST": "1ST",
    "SECOND": "2ND",
    "THIRD": "3RD",
    "FOURTH": "4TH",
    "FIFTH": "5TH",
    "SIXTH": "6TH",
    "SEVENTH": "7TH",
    "EIGHTH": "8TH",
    "NINTH": "9TH",
    "TENTH": "10TH",
    "ELEVENTH": "11TH",
    "TWELFTH": "12TH",
    # "CR 84W" is how people write "COUNTY ROAD 84W".
    "CR": "COUNTY RD",
    "COLORADO": "CO",
}

# Unit designators are dropped, leaving the unit itself, so "#206", "APT 206" and "UNIT 206" all
# match. The county uses APT, UNIT, STE and "#" (no designator) seemingly interchangeably.
UNIT_WORDS = frozenset({"APT", "APARTMENT", "UNIT", "STE", "SUITE"})

# Shorter queries match too much of the county to be worth ranking.
MIN_QUERY_LENGTH = 3
MAX_RESULTS = 10
# Added to the similarity of addresses whose house number starts with the number typed, so
# "117 valley" puts 1172 Valley Ln ahead of 2117 Valley Ln while the number is still being typed.
NUMBER_PREFIX_BOOST = 0.2


def normalize(text: str) -> str:
    """Upper-case words with abbreviations, ordinals and unit designators made canonical.

    "1172 South Boulder Road, Apt. #206" -> "1172 S BOULDER RD 206".
    """
    # Apostrophes and periods join ("O'NEIL" -> "ONEIL", "ST." -> "ST"); other punctuation splits.
    text = re.sub(r"['.]", "", text.upper())
    words = re.sub(r"[^A-Z0-9/]+", " ", text).split()
    return " ".join(WORDS.get(word, word) for word in words if word not in UNIT_WORDS)


def address_search_text(
    number: str, street: str, unit: str, jurisdiction: str, state: str, zip_code: str
) -> str:
    """The normalized text an address is searched by.

    "1172 VALLEY LN UNINCORPORATED BOULDER COUNTY CO 80302". State and ZIP come last so a pasted
    "1172 Valley Ln, Boulder, CO 80302" still matches; without them its unmatched words sink
    its similarity below the threshold.
    """
    return normalize(f"{number} {street} {unit} {jurisdiction} {state} {zip_code}")


def _leading_number(query: str) -> str | None:
    """The house number a normalized query starts with, if it starts with one."""
    first = query.split(" ", 1)[0]
    return first if first[:1].isdigit() else None


def search_addresses(query: str, limit: int = MAX_RESULTS) -> list[Address]:
    """The current addresses best matching query, best first. Empty if query is too short."""
    query = normalize(query)
    if len(query) < MIN_QUERY_LENGTH:
        return []

    number_boost = Value(0.0)
    if number := _leading_number(query):
        number_boost = Case(
            When(number__startswith=number, then=Value(NUMBER_PREFIX_BOOST)), default=Value(0.0)
        )
    return list(
        Address.objects.current()
        # trigram_word_similar (pg_trgm's %>) is what the GIN index serves; the similarity it
        # thresholds on is computed again for ranking.
        .filter(search_text__trigram_word_similar=query)
        .annotate(rank=TrigramWordSimilarity(query, "search_text") + number_boost)
        # Ties (every unit at one address, every address on a street) go in street order, with
        # house numbers in numeric order: shorter numbers first.
        .order_by(
            F("rank").desc(), "street", Length("number"), "number", Length("unit"), "unit", "pk"
        )[:limit]
    )
