"""Real Bertioga schema: lot inscription is not a verified address SQL."""
from __future__ import annotations

import json

import pytest

from imobhunter.domain.models import SearchRequest
from imobhunter.sources.sp_bertioga_local import BertiogaLocalStore


def polygon(lon=-46.10, lat=-23.82):
    return {
        "type": "MultiPolygon",
        "coordinates": [[[[
            [lon - .0001, lat - .0001],
            [lon + .0001, lat - .0001],
            [lon + .0001, lat + .0001],
            [lon - .0001, lat + .0001],
            [lon - .0001, lat - .0001],
        ]]],
    }


def lot(number="177", inscription="16.004.022.000", lon=-46.10, extra=None):
    p = {
        "Bairro": "RIO DA PRAIA", "Emplacamento": number,
        "Inscrição": inscription, "Lote": "6", "Loteamento": "JARDIM DAS CANCOES",
        "Matrícula": "2/55391", "Quadra": "4",
    }
    p.update(extra or {})
    return {"type": "Feature", "properties": p,
            "geometry": polygon(lon=lon)}


def line(street="RUA TESTE"):
    return {
        "type": "Feature",
        "properties": {
            "Logardouro": street, "Denominação Oficial": "TESTE",
            "Codigo Logradouro": "42", "CEP": "11250-000",
        },
        "geometry": {
            "type": "LineString", "coordinates": [
                [-46.1003, -23.82008], [-46.0997, -23.82008],
            ],
        },
    }


def zone():
    return {
        "type": "Feature",
        "properties": {
            "sigla": "ZM1", "legenda": "ZM1 - Zona Mista",
            "usos_permitidos": "H1, H2", "cnae": "NOT_FOR_EXPORT",
        },
        "geometry": {
            "type": "MultiPolygon",
            "coordinates": [[[[
                [-46.101, -23.821], [-46.099, -23.821],
                [-46.099, -23.819], [-46.101, -23.819],
                [-46.101, -23.821],
            ]]],
        },
    }


def write(path, name, features):
    path.write_text(json.dumps({
        "type": "FeatureCollection", "name": name, "features": features,
        "crs": {"type": "name",
                "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
    }), encoding="utf-8")
    return path


def setup_store(tmp_path, lots=None):
    folder = tmp_path / "input"
    folder.mkdir()
    lots_path = write(folder / "lotes.geojson", "lotes", lots or [
        lot(extra={"nome_proprietario": "PRIVATE", "valor_iptu": 999}),
        lot(number="178", inscription="03.016.002.###", lon=-46.1002),
    ])
    roads_path = write(folder / "eixoLogradouro.geojson", "eixo_logradouro", [line()])
    zone_path = write(folder / "zoneamento.geojson", "zoneamento", [zone()])
    store = BertiogaLocalStore(tmp_path / "local_db")
    return store, (lots_path, roads_path, zone_path)


def test_three_layer_import_is_persistent_and_searchable_offline(tmp_path):
    store, paths = setup_store(tmp_path)
    assert not store.installed()
    assert store.import_files(*paths) == {
        "lotes": 2, "logradouros": 1, "zonas": 1,
    }
    reopened = BertiogaLocalStore(tmp_path / "local_db")
    assert reopened.installed()
    assert reopened.counts() == {"lotes": 2, "logradouros": 1, "zonas": 1}
    rows, diag = reopened.search(SearchRequest(
        address="Rua Teste", number="177", city="Bertioga", state="SP",
    ))
    assert len(rows) == 1
    rec = rows[0]
    assert rec.block == "4" and rec.lot == "6"
    assert rec.attributes["inscricao_cadastral_do_lote_candidato"] == "16.004.022.000"
    assert rec.attributes["matricula_informada_no_lote"] == "2/55391"
    assert rec.attributes["zoneamento_candidato"][0]["code"] == "ZM1"
    assert rec.attributes["sql"] is None
    assert rec.attributes["municipal_registration_number"] is None
    assert rec.attributes["iptu_registration_number"] is None
    assert rec.attributes["cadastre_match"] == "spatial_candidate_not_address_confirmed"
    assert rec.area_m2 is None  # No official cadastral area exists in the source
    assert rec.provenance[0].confidence < 0.5
    assert diag["matching_road_segments"] == 1
    assert diag["spatial_candidates"] == 1
    assert diag["registration_by_address_verified"] is False
    assert "PRIVATE" not in str(rec)
    assert "999" not in str(rec)


def test_incomplete_inscription_is_not_claimed_as_tax_sql(tmp_path):
    store, paths = setup_store(tmp_path)
    store.import_files(*paths)
    results, _ = store.search(SearchRequest(
        address="Rua Teste", number="178", city="Bertioga", state="SP",
    ))
    assert len(results) == 1
    assert results[0].attributes["inscricao_status"] == "incompleta_ou_ausente"
    assert results[0].attributes["inscricao_cadastral_do_lote_candidato"] == (
        "03.016.002.###"
    )
    assert results[0].attributes["sql"] is None


def test_wrong_number_or_unrelated_road_never_yields_inscription(tmp_path):
    store, paths = setup_store(tmp_path)
    store.import_files(*paths)
    for street, number in (
        ("Rua Teste", "900"), ("Rua Inexistente", "177"),
        ("Rua Teste", "177 OR 1=1"),
    ):
        results, diag = store.search(SearchRequest(
            address=street, number=number, city="Bertioga", state="SP",
        ))
        assert results == []
        assert diag["result"] != "spatial_lot_candidates"


def test_ambiguous_same_door_returns_candidates_not_certified_sql(tmp_path):
    store, paths = setup_store(tmp_path, lots=[
        lot(lon=-46.1), lot(inscription="16.004.029.000", lon=-46.1003),
    ])
    store.import_files(*paths)
    results, diag = store.search(SearchRequest(
        address="Rua Teste", number="177", city="Bertioga", state="SP",
    ))
    assert len(results) == 2
    assert diag["spatial_candidates"] == 2
    assert all(record.attributes["sql"] is None for record in results)


def test_import_rejects_mixed_layers_and_preserves_old_database(tmp_path):
    store, paths = setup_store(tmp_path)
    store.import_files(*paths)
    with pytest.raises(ValueError, match="colunas municipais"):
        store.import_files(paths[1], paths[0], paths[2])
    assert store.counts() == {"lotes": 2, "logradouros": 1, "zonas": 1}


def test_missing_bundle_and_address_without_number_are_not_false_no_lot(tmp_path):
    store = BertiogaLocalStore(tmp_path / "empty")
    rows, diag = store.search(SearchRequest(
        address="Rua Teste", number="177", city="Bertioga", state="SP",
    ))
    assert rows == [] and diag["result"] == "local_bundle_not_imported"
    store, paths = setup_store(tmp_path / "second")
    store.import_files(*paths)
    rows, diag = store.search(SearchRequest(
        address="Rua Teste", city="Bertioga", state="SP",
    ))
    assert rows == [] and diag["result"] == "street_and_numeric_number_required"
