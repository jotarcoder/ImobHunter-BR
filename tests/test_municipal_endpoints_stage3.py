"""Stage 3.3: one endpoint inventory, correct municipality routing and bounded probes.

All request simulations use MockTransport or monkeypatched adapter methods;
none require municipal services to be online.
"""
from __future__ import annotations

import httpx
import pytest

from imobhunter.application.municipal_endpoints import (
    municipal_endpoints,
    settings_endpoint_rows,
)
from imobhunter.application.source_probe import probe_endpoint
from imobhunter.domain.models import PropertyRecord, SearchRequest
from imobhunter.sources.geosampa import DEFAULT_WFS_URL, GeoSampaAdapter
from imobhunter.sources.official_municipal_services import (
    BLUMENAU_ARCGIS_LAYER,
    DF_ARCGIS_LAYER,
    GOIANIA_ARCGIS_LAYER,
    MUNICIPAL_WFS,
    PORTO_ALEGRE_ARCGIS_LAYER,
    RECIFE_CKAN_API,
    RIO_ARCGIS_LAYER,
    RIO_GEOPAL_LAYER,
    OfficialMunicipalServicesAdapter,
)


def test_settings_list_is_built_from_real_adapter_endpoints() -> None:
    rows = settings_endpoint_rows()
    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids)) == 12
    assert rows[0]["url"] == DEFAULT_WFS_URL
    assert rows[0]["city"] == "São Paulo"
    assert rows[0]["state"] == "SP"
    for id_, city, state in (
        ("praia_grande", "Praia Grande", "SP"),
        ("santos", "Santos", "SP"),
        ("bertioga", "Bertioga", "SP"),
        ("belo_horizonte", "Belo Horizonte", "MG"),
    ):
        row = next(row for row in rows if row["id"] == id_)
        assert row["url"] == MUNICIPAL_WFS[(city.casefold(), state.casefold())]["url"]
        assert row["kind"] == "wfs"
    urls = {row["id"]: row["url"] for row in rows}
    assert urls["rio_territorial"] == RIO_ARCGIS_LAYER
    assert urls["rio_geopal"] == RIO_GEOPAL_LAYER
    assert urls["df"] == DF_ARCGIS_LAYER
    assert urls["goiania"] == GOIANIA_ARCGIS_LAYER
    assert urls["blumenau"] == BLUMENAU_ARCGIS_LAYER
    assert urls["porto_alegre"] == PORTO_ALEGRE_ARCGIS_LAYER
    assert urls["recife"].startswith(f"{RECIFE_CKAN_API}/package_show?id=")
    assert next(row for row in rows if row["id"] == "rio_geopal")["role"] == "fallback"
    assert all(row["url"].startswith("https://") for row in rows)
    assert len(municipal_endpoints()) == len(rows)


@pytest.mark.parametrize(("city", "state"), [
    ("Praia Grande", "SP"), ("Santos", "SP"),
    ("Bertioga", "SP"), ("Belo Horizonte", "MG"),
])
def test_wfs_address_uses_only_configured_municipality(monkeypatch, tmp_path, city, state):
    captured = []
    adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path)
    monkeypatch.setattr(adapter, "_geocode", lambda req: (-23.55, -46.60))
    monkeypatch.setattr(adapter, "_wfs_records", lambda *args: captured.append(args) or [])
    request = SearchRequest(address="Rua Exemplo", number="100", city=city, state=state)
    assert adapter.search(request) == []
    assert len(captured) == 1
    called_city, called_state, url, latitude, longitude, call_req = captured[0]
    assert (called_city, called_state) == (city, state)
    assert url == MUNICIPAL_WFS[(city.casefold(), state.casefold())]["url"]
    assert (latitude, longitude) == (-23.55, -46.60)
    assert call_req is request


@pytest.mark.parametrize(("city", "state", "url"), [
    ("Rio de Janeiro", "RJ", RIO_ARCGIS_LAYER),
    ("Brasília", "DF", DF_ARCGIS_LAYER),
    ("Goiânia", "GO", GOIANIA_ARCGIS_LAYER),
    ("Blumenau", "SC", BLUMENAU_ARCGIS_LAYER),
    ("Porto Alegre", "RS", PORTO_ALEGRE_ARCGIS_LAYER),
])
def test_arcgis_address_selects_its_own_layer(monkeypatch, tmp_path, city, state, url):
    seen = []
    adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path)
    monkeypatch.setattr(adapter, "_geocode", lambda req: (-23.55, -46.60))
    def fake_arcgis(*args, **kwargs):
        seen.append((args, kwargs))
        return [PropertyRecord(city=city, state=state, property_id="official-lot")]
    monkeypatch.setattr(adapter, "_arcgis_records", fake_arcgis)
    request = SearchRequest(address="Rua Exemplo", city=city, state=state)
    assert len(adapter.search(request)) == 1
    assert len(seen) == 1
    assert seen[0][0][0:2] == (city, state)
    assert seen[0][1].get("layer_url", RIO_ARCGIS_LAYER) == url


def test_rio_geopal_is_only_called_if_main_layer_is_empty(monkeypatch, tmp_path):
    adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path)
    calls = []
    monkeypatch.setattr(adapter, "_geocode", lambda req: (-22.9, -43.2))
    monkeypatch.setattr(adapter, "_arcgis_records", lambda *a, **k: calls.append("primary") or [])
    monkeypatch.setattr(adapter, "_rio_geopal_records", lambda *a: calls.append("fallback") or [])
    adapter.search(SearchRequest(address="Av. Rio Branco", city="Rio de Janeiro", state="RJ"))
    assert calls == ["primary", "fallback"]


def test_recife_catalog_lookup_bypasses_other_city_adapters(monkeypatch, tmp_path):
    adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path)
    called = []
    monkeypatch.setattr(adapter, "_recife_records", lambda request: called.append(request.city) or [])
    monkeypatch.setattr(adapter, "_geocode", lambda request: pytest.fail("Recife must use CKAN"))
    assert adapter.search(SearchRequest(address="Av. Boa Vista", city="Recife", state="PE")) == []
    assert called == ["Recife"]


def test_other_city_never_invokes_geosampa_or_wrong_official_source(tmp_path):
    def forbidden(_req):
        raise AssertionError("Wrong municipality was sent to GeoSampa")
    client = httpx.Client(transport=httpx.MockTransport(forbidden))
    try:
        geo = GeoSampaAdapter(client=client)
        assert geo.search(SearchRequest(address="Avenida Anchieta", city="Bertioga", state="SP")) == []
        assert geo.search(SearchRequest(address="Rua X", city="Santos", state="SP")) == []
        adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path, client=client)
        assert adapter.search(SearchRequest(address="Rua X", city="Santos", state="RJ")) == []
        assert adapter.search(SearchRequest(address="Rua X", city="São Paulo", state="SP")) == []
        assert adapter.search(SearchRequest(address="Rua X", city="Praia Grande", state="RJ")) == []
    finally:
        client.close()


def test_wfs_probe_matches_version_fallback_without_disabling_tls():
    attempts = []
    def handler(req):
        version = req.url.params.get("version")
        attempts.append(version)
        if version == "2.0.0":
            return httpx.Response(403)
        return httpx.Response(200, text=(
            '<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/1.1.0">'
            '<wfs:FeatureTypeList /></wfs:WFS_Capabilities>'
        ))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe_endpoint({
            "id": "santos", "url": MUNICIPAL_WFS[("santos", "sp")]["url"],
            "kind": "wfs",
        }, client=client)
    assert result.state == "responded"
    assert attempts == ["2.0.0", "1.1.0"]


def test_geosampa_probe_demands_actual_parcel_layer():
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(
        200, text='<WFS_Capabilities version="1.0.0"></WFS_Capabilities>'
    ))) as client:
        result = probe_endpoint({
            "id": "sao_paulo", "url": DEFAULT_WFS_URL, "kind": "wfs",
        }, client)
    assert result.state == "error"
    assert "camada cadastral" in result.message


def test_probe_arcgis_ckan_and_errors_are_not_property_availability():
    def handler(req):
        if "package_show" in req.url.path:
            return httpx.Response(200, json={"success": True})
        return httpx.Response(200, json={"name": "Lotes fiscais"})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        for kind, url in (
            ("arcgis", RIO_ARCGIS_LAYER),
            ("ckan", settings_endpoint_rows()[-2]["url"]),
        ):
            assert probe_endpoint({"url": url, "kind": kind}, client).state == "responded"
    invalid = probe_endpoint({"url": "http://example.com/wfs", "kind": "wfs"})
    assert invalid.state == "error"
    assert "HTTPS" in invalid.message
    with httpx.Client(transport=httpx.MockTransport(
        lambda req: (_ for _ in ()).throw(httpx.ConnectError("CERTIFICATE_VERIFY_FAILED"))
    )) as client:
        failure = probe_endpoint({
            "url": MUNICIPAL_WFS[("bertioga", "sp")]["url"], "kind": "wfs",
        }, client)
    assert failure.state == "error"
    assert "CERTIFICATE_VERIFY_FAILED" in failure.message
