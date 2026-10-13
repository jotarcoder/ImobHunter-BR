from pathlib import Path

from imobhunter.application.market_intelligence import MarketIntelligenceStore, haversine_km


def test_haversine_distance_zero_and_known_distance():
    assert haversine_km(-23.55, -46.63, -23.55, -46.63) == 0
    assert 1.0 < haversine_km(-23.55, -46.63, -23.56, -46.63) < 1.2


def test_csv_import_and_radius_search(tmp_path: Path):
    csv_path = tmp_path / "companies.csv"
    csv_path.write_text(
        "name,cnpj,cnae,address,latitude,longitude,revenue_reported,revenue_period,revenue_estimate,estimate_method,source,updated_at\n"
        "Empresa A,123,comercio,Rua A,-23.55,-46.63,100000,2025,90000,modelo teste,base teste,2026-10-01\n"
        "Empresa B,456,servicos,Rua B,-22.90,-43.20,,,,,,\n",
        encoding="utf-8",
    )
    store = MarketIntelligenceStore(tmp_path / "local.sqlite3")
    assert store.import_csv(csv_path) == 2
    found = store.search_radius(-23.55, -46.63, 2)
    assert len(found) == 1
    assert found[0]["name"] == "Empresa A"
    assert found[0]["revenue_status"] == "Divulgado"
    assert found[0]["revenue_estimate"] == 90000


def test_csv_import_is_idempotent_for_same_source_rows(tmp_path: Path):
    csv_path = tmp_path / "companies.csv"
    csv_path.write_text(
        "name,cnpj,cnae,latitude,longitude,source\\n"
        "Empresa A,12.345.678/0001-90,comercio,-23.55,-46.63,Receita aberta\\n",
        encoding="utf-8",
    )
    store = MarketIntelligenceStore(tmp_path / "local.sqlite3")
    assert store.import_csv(csv_path) == 1
    assert store.import_csv(csv_path) == 0
    assert store.count() == 1


def test_import_rejects_missing_coordinates(tmp_path: Path):
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("name,cnpj\nEmpresa A,123\n", encoding="utf-8")
    store = MarketIntelligenceStore(tmp_path / "local.sqlite3")
    try:
        store.import_csv(csv_path)
    except ValueError as exc:
        assert "latitude" in str(exc)
    else:
        raise AssertionError("Expected invalid CSV headers to be rejected")


def test_segment_filters_match_cnae_groups_and_osm_tags(tmp_path: Path):
    csv_path = tmp_path / "segments.csv"
    csv_path.write_text(
        "name,cnae,latitude,longitude\n"
        "Loja,4711301,-23.55,-46.63\n"
        "Serviço,6201500,-23.55,-46.63\n"
        "Fábrica,2511000,-23.55,-46.63\n"
        "Construtora,4120400,-23.55,-46.63\n"
        "Café OSM,amenity cafe,-23.55,-46.63\n"
        "Loja OSM,shop,-23.55,-46.63\n",
        encoding="utf-8",
    )
    store = MarketIntelligenceStore(tmp_path / "segments.sqlite3")
    assert store.import_csv(csv_path) == 6
    assert {x["name"] for x in store.search_radius(-23.55, -46.63, 1, "comércio")} == {"Loja", "Loja OSM"}
    assert {x["name"] for x in store.search_radius(-23.55, -46.63, 1, "serviços")} == {"Serviço", "Café OSM"}
    assert {x["name"] for x in store.search_radius(-23.55, -46.63, 1, "indústria")} == {"Fábrica"}
    assert {x["name"] for x in store.search_radius(-23.55, -46.63, 1, "construção")} == {"Construtora"}
