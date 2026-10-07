from __future__ import annotations

import httpx

from imobhunter.domain.models import SearchRequest
from imobhunter.sources.geosampa import GeoSampaAdapter


def test_geosampa_search_builds_filtered_wfs_request() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [-46.65, -23.57]},
                        "properties": {
                            "cd_setor_fiscal": "010",
                            "cd_quadra_fiscal": "020",
                            "cd_lote": "0030",
                            "cd_digito_sql": "1",
                            "cd_contribuinte": "010.020.0030-1",
                            "nm_logradouro_completo": "R PAMPLONA",
                            "cd_numero_porta": "1578",
                            "qt_area_terreno": "420.5",
                        },
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = GeoSampaAdapter(client=client)

    records = adapter.search(
        SearchRequest(
            address="R Pamplona",
            number="1578",
            city="São Paulo",
            state="SP",
        )
    )

    assert len(records) == 1
    assert records[0].city == "SAO PAULO"
    assert records[0].state == "SP"
    assert records[0].block == "020"
    assert records[0].lot == "0030"
    assert records[0].area_m2 == 420.5
    assert records[0].attributes["sql"] == "010.020.0030-1"
    assert "typeName=geoportal%3Alote_cidadao" in str(captured["url"])
    assert "cd_numero_porta" in str(captured["url"])


def test_geosampa_ignores_non_sao_paulo_states() -> None:
    adapter = GeoSampaAdapter(client=httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"features": []})
    )))

    records = adapter.search(
        SearchRequest(address="Rua Pamplona", number="1578", state="RJ")
    )

    assert records == []
