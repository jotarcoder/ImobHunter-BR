import httpx

from imobhunter.sources.inde import GeospatialService
from scripts.discover_national_municipal_services import (
    is_official_https,
    probe_service,
)


CAPABILITIES = """<?xml version="1.0"?>
<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0">
  <wfs:FeatureTypeList>
    <wfs:FeatureType>
      <wfs:Name>cadastro:lotes_fiscais</wfs:Name>
      <wfs:Title>Lotes fiscais</wfs:Title>
    </wfs:FeatureType>
    <wfs:FeatureType>
      <wfs:Name>base:ruas</wfs:Name>
      <wfs:Title>Eixos de vias</wfs:Title>
    </wfs:FeatureType>
  </wfs:FeatureTypeList>
</wfs:WFS_Capabilities>
"""


def _service(url="https://geo.municipio.gov.br/geoserver/wfs"):
    return GeospatialService(
        service_id="municipal-cadastre",
        title="Cadastro imobiliário municipal",
        provider="Prefeitura Municipal",
        service_type="WFS",
        url=url,
        keywords=("lotes", "quadras"),
    )


def test_official_endpoint_requires_https_and_government_domain():
    assert is_official_https("https://geo.municipio.gov.br/wfs")
    assert is_official_https("https://gov.br/")
    assert not is_official_https("http://geo.municipio.gov.br/wfs")
    assert not is_official_https("https://municipio.example/wfs")
    assert not is_official_https("https://gov.br.attacker.example/wfs")


def test_probe_reports_only_cadastral_layers_from_official_wfs():
    def handler(request):
        assert request.url.params["request"] == "GetCapabilities"
        return httpx.Response(200, text=CAPABILITIES)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe_service(_service(), client=client)

    assert result["status"] == "cadastral_layer_found"
    assert result["layers"] == [{"name": "cadastro:lotes_fiscais", "title": "Lotes fiscais"}]


def test_probe_does_not_request_unverified_host():
    def handler(_request):
        raise AssertionError("unverified host must never be requested")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe_service(_service("https://municipio.example/wfs"), client=client)

    assert result["status"] == "rejected_unverified_host"


def test_probe_records_connection_failure_without_throwing():
    def handler(_request):
        return httpx.Response(503, text="service unavailable")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe_service(_service(), client=client)

    assert result["status"] == "connection_failed"
    assert "HTTPStatusError" in result["diagnostic"]
