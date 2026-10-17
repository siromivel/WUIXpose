import pytest
from django.urls import reverse

from wuixpose.core import assignment
from wuixpose.core.display import address_line1
from wuixpose.core.ingest import boulder
from wuixpose.core.models import Address
from wuixpose.core.search import address_search_text, normalize, search_addresses

from .factories import ORIGIN, address_props, box, feature, point_feature

# Normalization: these cases are the spec for search.WORDS and search.UNIT_WORDS.


@pytest.mark.parametrize(
    ("text", "normalized"),
    [
        # Directionals and street types collapse both ways.
        ("South Boulder Road", "S BOULDER RD"),
        ("S BOULDER RD", "S BOULDER RD"),
        ("1172 E. South Boulder Rd.", "1172 E S BOULDER RD"),
        ("North Foothills Highway", "N FOOTHILLS HWY"),
        ("Pearl Street", "PEARL ST"),
        ("Valmont Avenue", "VALMONT AVE"),
        # Ordinals, spelled out or not.
        ("Second Avenue", "2ND AVE"),
        ("2nd Ave", "2ND AVE"),
        ("Fourth of July Road", "4TH OF JULY RD"),
        # Units: the designator is dropped, whatever it is.
        ("2211 Pratt St #206", "2211 PRATT ST 206"),
        ("2211 Pratt St Apt 206", "2211 PRATT ST 206"),
        ("2211 Pratt St, Apt. #206", "2211 PRATT ST 206"),
        ("2211 Pratt St Unit 206", "2211 PRATT ST 206"),
        ("2211 Pratt St Suite 206", "2211 PRATT ST 206"),
        ("2211 PRATT ST STE 206", "2211 PRATT ST 206"),
        # Words in names.
        ("Mount Sanitas Ave", "MT SANITAS AVE"),
        ("Saint Vrain Dr", "ST VRAIN DR"),
        ("CR 84W", "COUNTY RD 84W"),
        ("County Road 84W", "COUNTY RD 84W"),
        # Punctuation, spacing and case.
        ("40 O'Neil Way", "40 ONEIL WAY"),
        ("1172 1/2 Valley Ln", "1172 1/2 VALLEY LN"),
        ("  1172   valley,ln ", "1172 VALLEY LN"),
        ("Boulder, Colorado 80302", "BOULDER CO 80302"),
    ],
)
def test_normalize(text, normalized):
    assert normalize(text) == normalized


def test_address_search_text_is_the_whole_address_normalized():
    text = address_search_text("1172", "SOUTH BOULDER RD", "APT 2", "LOUISVILLE", "CO", "80027")

    assert text == "1172 S BOULDER RD 2 LOUISVILLE CO 80027"


# Searching


def load(*addresses: tuple[str, str, str, dict]) -> None:
    """Load addresses given as (id, number, street name, other county fields), all at ORIGIN."""
    boulder.load_addresses(
        [point_feature(address_props(aid, number, street, **extra), 0, 0) for aid, number, street, extra in addresses]
    )


def found(query: str) -> list[str]:
    return [address_line1(a) for a in search_addresses(query)]


@pytest.fixture
def addresses():
    load(
        ("1", "1172", "VALLEY", {"STREETTYPE": "LN", "CITY": "UNINCORPORATED", "ZIPCODE": "80302"}),
        ("2", "1000", "SOUTH BOULDER", {"PREFIX": "E", "STREETTYPE": "RD", "CITY": "LOUISVILLE"}),
        ("3", "2211", "PRATT", {"STREETTYPE": "ST", "UNIT": "206", "CITY": "LONGMONT"}),
        ("4", "2211", "PRATT", {"STREETTYPE": "ST", "UNIT": "207", "CITY": "LONGMONT"}),
        ("5", "232", "FOURTH OF JULY", {"STREETTYPE": "RD", "CITY": "UNINCORPORATED"}),
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("query", "first"),
    [
        ("1172 Valley Ln", "1172 Valley Ln"),
        ("1172 valley", "1172 Valley Ln"),  # partial
        ("1172 vally ln", "1172 Valley Ln"),  # typo
        ("1172 Valley Lane, Boulder, CO 80302", "1172 Valley Ln"),  # pasted, with a mailing city
        ("1000 E S Boulder Road", "1000 E South Boulder Rd"),
        ("1000 east south bolder rd", "1000 E South Boulder Rd"),  # typo
        ("2211 Pratt Apt 206", "2211 Pratt St #206"),
        ("2211 Pratt Street Unit 207", "2211 Pratt St #207"),
        ("232 4th of july", "232 Fourth Of July Rd"),
    ],
)
def test_search_finds_the_address(addresses, query, first):
    assert found(query)[0] == first


@pytest.mark.django_db
def test_search_ignores_short_and_unmatched_queries(addresses):
    assert found("") == []
    assert found("11") == []
    assert found("#") == []
    assert found("9999 nowhere blvd") == []


@pytest.mark.django_db
def test_search_leaves_out_retired_addresses(addresses):
    boulder.load_addresses([point_feature(address_props("1", "1", "X", STATUS="RETIRED"), 0, 0)])

    assert found("1172 valley ln") == []


@pytest.mark.django_db
def test_search_returns_at_most_the_limit():
    load(*((str(n), str(n), "MAIN", {"STREETTYPE": "ST"}) for n in range(1, 15)))

    assert len(search_addresses("main st")) == 10
    assert len(search_addresses("main st", limit=3)) == 3


@pytest.mark.django_db
def test_equal_matches_are_in_street_and_numeric_order():
    load(
        ("1", "100", "MAIN", {"STREETTYPE": "ST"}),
        ("2", "9", "MAIN", {"STREETTYPE": "ST"}),
        ("3", "10", "MAIN", {"STREETTYPE": "ST", "UNIT": "2"}),
        ("4", "10", "MAIN", {"STREETTYPE": "ST"}),
    )

    assert found("main st") == ["9 Main St", "10 Main St", "10 Main St #2", "100 Main St"]


@pytest.mark.django_db
def test_a_house_number_matching_from_the_start_ranks_first():
    # By trigrams alone 2117 matches "117" better, but someone typing "117" may be on their way
    # to 1172.
    load(("1", "2117", "VALLEY", {"STREETTYPE": "LN"}), ("2", "1172", "VALLEY", {"STREETTYPE": "LN"}))

    assert found("117 valley") == ["1172 Valley Ln", "2117 Valley Ln"]


# Keeping search_text current


@pytest.mark.django_db
def test_loading_writes_search_text(addresses):
    assert Address.objects.get(source_id="1").search_text == "1172 VALLEY LN UNINCORPORATED BOULDER COUNTY CO 80302"


@pytest.mark.django_db
def test_reloading_rewrites_stale_search_text():
    features = [point_feature(address_props("1", "12", "MAIN", STREETTYPE="ST"), 0, 0)]
    boulder.load_addresses(features)
    # As if normalization changed since the address was written.
    Address.objects.update(search_text="STALE")

    result = boulder.load_addresses(features)

    assert result.updated == 1
    assert Address.objects.get().search_text == "12 MAIN ST CO"


# API


@pytest.mark.django_db
def test_search_api(client):
    boulder.load_tracts([feature({"PARCEL_NO": "A"}, box(0, 0, 0.001, 0.001))])
    boulder.load_addresses(
        [
            point_feature(
                address_props("1", "1172", "VALLEY", "A", STREETTYPE="LN", ZIPCODE="80302"),
                0.0005,
                0.0005,
            )
        ]
    )
    assignment.link_address_tracts()
    address = Address.objects.get()

    data = client.get(reverse("search"), {"q": "1172 valley"}).json()

    assert data == {
        "results": [
            {
                "id": address.pk,
                "line1": "1172 Valley Ln",
                "line2": "CO 80302",
                "lon": pytest.approx(ORIGIN[0] + 0.0005),
                "lat": pytest.approx(ORIGIN[1] + 0.0005),
                "tract": address.tract_id,
            }
        ]
    }
    assert address.tract_id is not None


@pytest.mark.django_db
def test_search_api_without_a_query(client):
    assert client.get(reverse("search")).json() == {"results": []}
