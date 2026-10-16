import pytest

from wuixpose.core.display import address_line1, address_line2
from wuixpose.core.models import Address


@pytest.mark.parametrize(
    ("number", "street", "unit", "line1"),
    [
        ("1172", "VALLEY LN", "", "1172 Valley Ln"),
        ("4500", "S 19TH ST", "APT N304", "4500 S 19th St Apt N304"),
        ("2615", "COUNTY ROAD 128J", "", "2615 County Road 128J"),
        ("2211", "PRATT ST", "#7D", "2211 Pratt St #7D"),
        ("1172 1/2", "MCCASLIN BLVD", "", "1172 1/2 McCaslin Blvd"),
        ("40", "O'NEIL WAY", "", "40 O'Neil Way"),
    ],
)
def test_address_line1(number, street, unit, line1):
    assert address_line1(Address(number=number, street=street, unit=unit)) == line1


@pytest.mark.parametrize(
    ("jurisdiction", "zip_code", "line2"),
    [
        ("UNINCORPORATED BOULDER COUNTY", "80302", "Unincorporated Boulder County, CO 80302"),
        ("LONGMONT", "80501", "Longmont, CO 80501"),
        ("", "", "CO"),
    ],
)
def test_address_line2(jurisdiction, zip_code, line2):
    assert address_line2(Address(jurisdiction=jurisdiction, state="CO", zip_code=zip_code)) == line2


@pytest.mark.parametrize(
    ("unit", "text"),
    [
        ("", "1172 VALLEY LN"),
        ("#206", "1172 VALLEY LN #206"),
    ],
)
def test_str_is_stored_text(unit, text):
    # Models don't import display.py, so __str__ shows the text as stored.
    assert str(Address(number="1172", street="VALLEY LN", unit=unit)) == text
