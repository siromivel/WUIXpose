"""Formatting stored text for people to read.

Text is stored as the source publishes it (Boulder County: upper case); these functions turn it
into what the map shows, leaving the stored text untouched.
"""

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wuixpose.core.models import Address

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


def address_line1(address: "Address") -> str:
    """Number, street and unit: "1172 Valley Ln", "2211 Pratt St #206"."""
    line = _display_case(f"{address.number} {address.street}")
    if address.unit:
        line += f" {_display_case(str(address.unit))}"
    return line


def address_line2(address: "Address") -> str:
    """Jurisdiction, state and ZIP: "Unincorporated Boulder County, CO 80302"."""
    state_zip = f"{address.state} {address.zip_code}".strip()
    return ", ".join(part for part in (_display_case(str(address.jurisdiction)), state_zip) if part)
