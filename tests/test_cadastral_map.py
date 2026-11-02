"""Stage 2 regression tests: true official geometries and honest map labels."""
import json
import math

from imobhunter.application.cadastral_map import (
    CLASSIFICATION_LABELS,
    classification,
    map_center,
    parse_geometry,
    preferred_target,
    prepare_features,
    sql_from_source,
    valid_lon_lat,
)
from imobhunter.domain.models import PropertyRecord, Provenance, SearchRequest

RING = [
    [-46.651, -23.551],
    [-46.650, -23.551],
    [-46.650, -23.550],
    [-46.651, -23.550],
    [-46.651, -23.551],
]
HOLE = [
    [-46.6508, -23.5508],
    [-46.6507, -23.5508],
    [-46.6507, -23.5507],
    [-46.6508, -23.5508],
]


def record(match: str, geometry=None, *, block="020", lot="0030", sql=None):
    attrs = {"house_number_match": match}
    if geometry is not None:
        attrs["geometry_geojson"] = json.dumps(geometry)
    if sql is not None:
        attrs["iptu_registration_number"] = sql
    return PropertyRecord(
        property_id="wfs-feature-id-not-sql",
        address="Rua da Consolação",
        city="São Paulo",
        state="SP",
        block=block,
        lot=lot,
        attributes=attrs,
        provenance=(Provenance("geosampa", confidence=0.8),),
    )


def polygon():
    return {"type": "Polygon", "coordinates": [RING]}


def test_polygon_is_preserved_and_never_inferred_from_street() -> None:
    official = record("exact", polygon())
    without_geom = record("exact")
    features = prepare_features((official, without_geom))
    assert len(features) == 1
    assert features[0].has_official_polygon
    assert features[0].polygons[0][0] == tuple(tuple(pt) for pt in RING)


def test_multipolygon_and_holes_are_retained() -> None:
    geom = {"type": "MultiPolygon", "coordinates": [[RING, HOLE], [RING]]}
    polygons, point = parse_geometry(json.dumps(geom))
    assert point is None
    assert len(polygons) == 2
    assert len(polygons[0]) == 2
    assert len(polygons[1]) == 1


def test_point_only_is_not_labeled_as_official_lot_polygon() -> None:
    point_record = PropertyRecord(
        address="Rua da Consolação",
        city="São Paulo",
        state="SP",
        latitude=-23.55,
        longitude=-46.65,
        attributes={"record_kind": "geocoded_address_only"},
        provenance=(Provenance("geocoder"),),
    )
    features = prepare_features((point_record,))
    assert len(features) == 1
    assert features[0].point == (-46.65, -23.55)
    assert not features[0].has_official_polygon
    assert preferred_target(features) is None


def test_invalid_geojson_and_projected_crs_are_not_drawn_as_wgs84() -> None:
    bad = {"type": "Polygon", "coordinates": [[[300000, 7400000], [300100, 7400000], [300100, 7400100]]]}
    polygons, point = parse_geometry(bad)
    assert not polygons and point is None
    assert prepare_features((record("exact", bad),)) == ()
    for longitude, latitude in ((float("nan"), -23), (-46, math.inf), (300000, 7400000)):
        assert valid_lon_lat(longitude, latitude) is None
    assert parse_geometry("not-json") == ((), None)


def test_spatial_match_is_target_when_exact_absent() -> None:
    neighbor = record("neighboring_parcel", polygon(), lot="0031")
    matched = record("geocoded_spatial_match", polygon(), lot="0030")
    features = prepare_features((neighbor, matched))
    assert preferred_target(features).record is matched
    assert classification(neighbor) == "neighbor"
    assert "conferir" in CLASSIFICATION_LABELS["spatial_match"]
    center = map_center(features)
    assert center is not None
    assert -46.652 < center[0] < -46.649


def test_exact_match_has_priority_but_neighbor_override_is_stronger() -> None:
    spatial = record("geocoded_spatial_match", polygon())
    exact = record("exact", polygon())
    features = prepare_features((spatial, exact))
    assert preferred_target(features).record is exact
    suspicious = PropertyRecord(
        attributes={
            "house_number_match": "exact",
            "parcel_relation": "neighbor_candidate",
        }
    )
    assert classification(suspicious) == "neighbor"


def test_candidate_and_unverified_must_not_be_presented_as_confirmed() -> None:
    candidate = record("geocoded_spatial_candidate", polygon())
    unknown = record("", polygon())
    features = prepare_features((unknown, candidate))
    assert preferred_target(features).record is candidate
    assert "candidato" in CLASSIFICATION_LABELS["candidate"].casefold()
    assert preferred_target(prepare_features((unknown,))) is None


def test_only_explicit_sql_counts_as_iptu_number() -> None:
    wfs_feature = record("exact", polygon())
    assert sql_from_source(wfs_feature) is None
    with_sql = record("exact", polygon(), sql="010.020.0030-1")
    assert sql_from_source(with_sql) == "010.020.0030-1"


def test_polygon_with_unusable_ring_must_not_appear() -> None:
    invalid = {"type": "Polygon", "coordinates": [[[-46.6, -23.5], [-46.6, -23.5], [-46.6, -23.5]]]}
    assert parse_geometry(invalid) == ((), None)
    assert parse_geometry({"type": "GeometryCollection", "geometries": [polygon()]}) == ((), None)


def test_explicit_block_and_lot_search_highlights_official_parcel() -> None:
    """A block/lot search has no house_number_match='exact', yet must find its lot."""
    query = SearchRequest(block="20", lot="30", city="São Paulo", state="SP")
    neighboring = record("", polygon(), block="020", lot="0031")
    cadastral_lot = record("", polygon(), block="020", lot="0030")
    features = prepare_features((neighboring, cadastral_lot), query)
    assert preferred_target(features).record is cadastral_lot
    assert features[1].classification == "parcel_query_match"
    assert features[0].classification == "unverified"
    assert "quadra e lote" in CLASSIFICATION_LABELS["parcel_query_match"].casefold()


def test_block_lot_match_respects_city_and_state() -> None:
    cadastral_lot = record("", polygon(), block="020", lot="0030")
    another_city = SearchRequest(block="20", lot="30", city="Bertioga", state="SP")
    another_state = SearchRequest(block="20", lot="30", city="São Paulo", state="RJ")
    assert classification(cadastral_lot, another_city) == "unverified"
    assert classification(cadastral_lot, another_state) == "unverified"
    assert preferred_target(prepare_features((cadastral_lot,), another_city)) is None



def test_bad_vertex_or_hole_cannot_fabricate_new_parcel_edges() -> None:
    """Invalid vertices must invalidate an entire ring, not join across it."""
    from imobhunter.application.cadastral_map import parse_geometry

    outer = [
        [-46.65, -23.55], [-46.649, -23.55],
        ["not-a-longitude", -23.549],
        [-46.649, -23.549], [-46.65, -23.55],
    ]
    assert parse_geometry({"type": "Polygon", "coordinates": [outer]}) == ((), None)
    complete = [
        [-46.65, -23.55], [-46.649, -23.55],
        [-46.649, -23.549], [-46.65, -23.55],
    ]
    incomplete_hole = [
        [-46.6499, -23.5499], [-46.6498, -23.5499],
        [float("nan"), -23.5498], [-46.6499, -23.5499],
    ]
    assert parse_geometry({
        "type": "Polygon", "coordinates": [complete, incomplete_hole]
    }) == ((), None)
