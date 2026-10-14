import pytest
from django.contrib.gis.geos import Point

from wuixpose.core.ingest import boulder
from wuixpose.core.models import Address
from wuixpose.core.models.tracts import STORAGE_SRID, TractIdentifier

from .factories import ORIGIN, address_props, box, feature, point_feature

# Display


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
def test_display_line1(number, street, unit, line1):
    assert Address(number=number, street=street, unit=unit).display_line1() == line1


@pytest.mark.parametrize(
    ("jurisdiction", "zip_code", "line2"),
    [
        ("UNINCORPORATED BOULDER COUNTY", "80302", "Unincorporated Boulder County, CO 80302"),
        ("LONGMONT", "80501", "Longmont, CO 80501"),
        ("", "", "CO"),
    ],
)
def test_display_line2(jurisdiction, zip_code, line2):
    assert Address(jurisdiction=jurisdiction, state="CO", zip_code=zip_code).display_line2() == line2


# Loading


@pytest.mark.django_db
def test_load_addresses_normalizes_county_fields():
    result = boulder.load_addresses(
        [
            point_feature(
                address_props(
                    "100",
                    "1172 ",
                    "VALLEY",
                    "146102000067",
                    PREFIX="",
                    STREETTYPE="LN",
                    SUFFIX=None,
                    UNITTYPE="APT",
                    UNIT="2",
                    CITY="UNINCORPORATED",
                    ZIPCODE="80302",
                ),
                0.0001,
                0.0001,
            ),
            point_feature(
                address_props("101", "2211", "PRATT", None, STREETTYPE="ST", UNIT="206", CITY="LONGMONT", ZIPCODE=" "),
                0.0002,
                0.0001,
            ),
        ]
    )

    assert (result.created, result.updated, result.skipped) == (2, 0, 0)
    rural, town = Address.objects.order_by("source_id")
    assert (rural.number, rural.street, rural.unit) == ("1172", "VALLEY LN", "APT 2")
    assert (rural.jurisdiction, rural.state, rural.zip_code) == ("UNINCORPORATED BOULDER COUNTY", "CO", "80302")
    assert (rural.county_fips, rural.county_apn) == ("08013", "146102000067")
    assert rural.geom.equals(Point(ORIGIN[0] + 0.0001, ORIGIN[1] + 0.0001, srid=STORAGE_SRID))
    assert (town.unit, town.zip_code) == ("#206", "")
    assert (town.county_fips, town.county_apn) == (None, None)


@pytest.mark.django_db
def test_load_addresses_skips_points_without_a_street_address():
    result = boulder.load_addresses(
        [
            point_feature(address_props("1", "", "MAIN"), 0, 0),
            point_feature(address_props("2", "12", " "), 0, 0),
            point_feature(address_props(None, "12", "MAIN"), 0, 0),
            {"type": "Feature", "geometry": None, "properties": address_props("3", "12", "MAIN")},
        ]
    )

    assert (result.created, result.skipped) == (0, 4)


@pytest.mark.django_db
def test_reloading_addresses_updates_in_place():
    boulder.load_addresses([point_feature(address_props("1", "12", "MAIN", STREETTYPE="ST"), 0, 0)])
    first = Address.objects.get()

    result = boulder.load_addresses([point_feature(address_props("1", "14", "MAIN", STREETTYPE="ST"), 0.0001, 0)])

    assert (result.created, result.updated) == (0, 1)
    first.refresh_from_db()
    assert first.number == "14"
    assert first.geom.x == pytest.approx(ORIGIN[0] + 0.0001)


# Linking to tracts


@pytest.fixture
def lots():
    """Lots A and B side by side, and two condo parcels C1 and C2 stacked on one outline east of them."""
    boulder.load_tracts(
        [
            feature({"PARCEL_NO": "A"}, box(0, 0, 0.001, 0.001)),
            feature({"PARCEL_NO": "B"}, box(0.001, 0, 0.002, 0.001)),
            feature({"PARCEL_NO": "C1"}, box(0.003, 0, 0.004, 0.001)),
            feature({"PARCEL_NO": "C2"}, box(0.003, 0, 0.004, 0.001)),
        ]
    )
    return dict(TractIdentifier.objects.values_list("value", "tract_id"))


def tract_of() -> dict[str, int | None]:
    return dict(Address.objects.values_list("source_id", "tract_id"))


@pytest.mark.django_db
def test_addresses_link_to_the_tract_carrying_their_parcel_number(lots):
    boulder.load_addresses(
        [
            point_feature(address_props("on-a", "1", "MAIN", "A"), 0.0005, 0.0005),
            # A driveway point on B for a house on A: the parcel number wins.
            point_feature(address_props("driveway", "2", "MAIN", "A"), 0.0015, 0.0005),
            point_feature(address_props("condo", "3", "MAIN", "C2"), 0.0035, 0.0005),
        ]
    )

    changed = boulder.link_address_tracts()

    assert tract_of() == {"on-a": lots["A"], "driveway": lots["A"], "condo": lots["C2"]}
    assert changed == 3
    assert boulder.link_address_tracts() == 0


@pytest.mark.django_db
def test_addresses_without_a_known_parcel_number_fall_back_to_location(lots):
    boulder.load_addresses(
        [
            # Replatted: the county's address still carries a retired parcel number.
            point_feature(address_props("stale", "1", "MAIN", "OLD"), 0.0015, 0.0005),
            point_feature(address_props("no-apn", "2", "MAIN"), 0.0005, 0.0005),
            # Stacked parcels under the point and no number to choose between them.
            point_feature(address_props("stacked", "3", "MAIN", "OLD"), 0.0035, 0.0005),
            point_feature(address_props("nowhere", "4", "MAIN", "OLD"), 0.01, 0.01),
        ]
    )

    boulder.link_address_tracts()

    assert tract_of() == {"stale": lots["B"], "no-apn": lots["A"], "stacked": None, "nowhere": None}


@pytest.mark.django_db
def test_address_links_follow_parcel_numbers_loaded_later():
    boulder.load_addresses([point_feature(address_props("1", "1", "MAIN", "A"), 0.0005, 0.0005)])
    boulder.link_address_tracts()
    assert tract_of() == {"1": None}

    boulder.load_tracts([feature({"PARCEL_NO": "A"}, box(0, 0, 0.001, 0.001))])
    boulder.link_address_tracts()

    assert tract_of() == {"1": TractIdentifier.objects.get().tract_id}
