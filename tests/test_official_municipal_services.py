import json

import httpx

from imobhunter.domain.models import SearchRequest
from imobhunter.sources.official_municipal_services import (
    MUNICIPAL_WFS,
    RIO_ARCGIS_LAYER,
    RIO_GEOPAL_LAYER,
    DF_ARCGIS_LAYER,
    GOIANIA_ARCGIS_LAYER,
    BLUMENAU_ARCGIS_LAYER,
    OfficialMunicipalServicesAdapter,
    _cadastral_layers,
    _official_url,
)


class FakeGeocoder:
    def geocode(self, _query):
        return {"latitude": -19.9227, "longitude": -43.9451}


CAPABILITIES = """<?xml version="1.0"?>
<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0">
  <wfs:FeatureTypeList>
    <wfs:FeatureType>
      <wfs:Name>cadastro:lotes</wfs:Name>
      <wfs:Title>Lotes e quadras cadastrais</wfs:Title>
    </wfs:FeatureType>
    <wfs:FeatureType>
      <wfs:Name>base:ruas</wfs:Name>
      <wfs:Title>Eixos de vias</wfs:Title>
    </wfs:FeatureType>
  </wfs:FeatureTypeList>
</wfs:WFS_Capabilities>
"""


def test_official_endpoints_are_https_government_domains():
    assert _official_url("https://bhmap.pbh.gov.br/v2/api/idebhgeo/wfs")
    assert _official_url("https://pgeo3.rio.rj.gov.br/arcgis/rest/services")
    assert not _official_url("http://bhmap.pbh.gov.br/wfs")
    assert not _official_url("https://example.com/wfs")


def test_known_wfs_municipal_services_are_configured():
    assert MUNICIPAL_WFS[("praia grande", "sp")]["url"] == "https://geoserver.praiagrande.sp.gov.br/ows"
    assert MUNICIPAL_WFS[("belo horizonte", "mg")]["url"] == (
        "https://bhmap.pbh.gov.br/v2/api/idebhgeo/wfs"
    )


def test_belo_horizonte_wfs_returns_geometry_quadra_lote_and_sql(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        if params.get("request") == "GetCapabilities":
            return httpx.Response(200, text=CAPABILITIES)
        assert params.get("typeNames") == "cadastro:lotes"
        assert params.get("bbox", "").endswith("EPSG:4326")
        return httpx.Response(200, json={
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "id": "lotes.7",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [-43.946, -19.923], [-43.944, -19.923],
                        [-43.944, -19.922], [-43.946, -19.923],
                    ]],
                },
                "properties": {
                    "quadra": "07",
                    "NULOTCTM": "42",
                    "AREA_TERRENO": "350.5",
                    "INDICE_CADASTRAL": "001020 001W0042",
                    "CIB": "CIB-123",
                    "NOME_LOGRADOURO": "Rua da Bahia",
                    "NUMERO_IMOVEL": 1000,
                },
            }],
        })

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(
        cache_dir=tmp_path / "cache", client=client, geocoder=FakeGeocoder()
    )
    records = adapter.search(SearchRequest(
        address="Rua da Bahia", number="1000", city="Belo Horizonte", state="MG"
    ))
    client.close()

    assert len(records) == 1
    record = records[0]
    assert record.city == "Belo Horizonte"
    assert record.state == "MG"
    assert record.block == "07"
    assert record.lot == "42"
    assert record.area_m2 == 350.5
    assert record.attributes["sql"] == "001020 001W0042"
    assert record.attributes["sql_status"] == "provided_by_layer"
    assert record.cib == "CIB-123"
    assert record.address == "Rua da Bahia, 1000"
    assert json.loads(record.attributes["geometry_geojson"])["type"] == "Polygon"


def test_rio_arcgis_rest_maps_lot_geometry_and_fields(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        expected_path = RIO_ARCGIS_LAYER.removeprefix("https://pgeo3.rio.rj.gov.br")
        assert request.url.path == expected_path + "/query"
        params = dict(request.url.params)
        assert params["geometryType"] == "esriGeometryPoint"
        assert params["outSR"] == "4326"
        return httpx.Response(200, json={
            "features": [{
                "attributes": {
                    "objectid": 77,
                    "inscricao_imobiliaria": "RJ-123",
                    "quadra": "Q-2",
                    "lote": "L-9",
                    "area_descrita": 420,
                },
                "geometry": {
                    "rings": [[
                        [-43.20, -22.90], [-43.19, -22.90],
                        [-43.19, -22.89], [-43.20, -22.90],
                    ]],
                },
            }],
        })

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(
        cache_dir=tmp_path / "cache", client=client, geocoder=FakeGeocoder()
    )
    records = adapter.search(SearchRequest(
        address="Avenida Rio Branco", number="1", city="Rio de Janeiro", state="RJ"
    ))
    client.close()

    assert len(records) == 1
    record = records[0]
    assert record.city == "Rio de Janeiro"
    assert record.state == "RJ"
    assert record.block == "Q-2"
    assert record.lot == "L-9"
    assert record.area_m2 == 420
    assert record.attributes["sql"] == "RJ-123"
    assert record.attributes["service_type"] == "ArcGIS REST"
    assert json.loads(record.attributes["geometry_geojson"])["type"] == "Polygon"


def test_service_failure_is_exposed_in_status(tmp_path):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="service unavailable")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(
        cache_dir=tmp_path / "cache", client=client, geocoder=FakeGeocoder()
    )
    assert adapter.search(SearchRequest(
        address="Rua da Bahia", number="1000", city="Belo Horizonte", state="MG"
    )) == []
    client.close()
    assert "Belo Horizonte" in (adapter.status().message or "")
    assert "HTTPStatusError" in (adapter.status().message or "")



def test_distrito_federal_arcgis_maps_public_iptu_lot_fields(tmp_path):
    class BrasiliaGeocoder:
        def geocode(self, _query):
            return {"latitude": -15.7939, "longitude": -47.8828}

    def handler(request: httpx.Request) -> httpx.Response:
        expected_path = DF_ARCGIS_LAYER.removeprefix("https://www.geoservicos.ide.df.gov.br")
        assert request.url.path == expected_path + "/query"
        params = dict(request.url.params)
        assert params["geometryType"] == "esriGeometryPoint"
        assert params["inSR"] == "4326"
        assert params["outSR"] == "4326"
        return httpx.Response(200, json={
            "features": [{
                "attributes": {
                    "objectid": 901,
                    "iptu_imovel": "12345678",
                    "iptu_ciu": "CIU-998877",
                    "iptu_endereco": "SQN 100 BLOCO A",
                    "lt_endereco": "SQN 100",
                    "lt_quadra": "SQN 100",
                    "lt_lote": "Lote 12",
                    "iptu_area_terr": 840.0,
                    "ac_area_ct": 220.5,
                },
                "geometry": {
                    "rings": [[
                        [-47.8830, -15.7940], [-47.8820, -15.7940],
                        [-47.8820, -15.7930], [-47.8830, -15.7940],
                    ]],
                },
            }],
        })

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(
        cache_dir=tmp_path / "cache", client=client, geocoder=BrasiliaGeocoder()
    )
    records = adapter.search(SearchRequest(
        address="SQN 100", number="12", city="Brasília", state="DF"
    ))
    client.close()

    assert len(records) == 1
    record = records[0]
    assert record.city == "Brasília"
    assert record.state == "DF"
    assert record.block == "SQN 100"
    assert record.lot == "Lote 12"
    assert record.area_m2 == 840.0
    assert record.attributes["sql"] == "12345678"
    assert record.attributes["iptu_registration_number"] == "12345678"
    assert record.attributes["iptu_ciu"] == "CIU-998877"
    assert record.attributes["built_area_m2"] == 220.5
    assert record.attributes["sql_status"] == "provided_by_layer"
    assert record.attributes["service_url"] == DF_ARCGIS_LAYER
    assert record.attributes["official_source"] == "IDE-DF — Lotes com Inscrição do IPTU"
    assert record.attributes["cadastre_match"] == "spatial_candidate_only"
    assert json.loads(record.attributes["geometry_geojson"])["type"] == "Polygon"


def test_praia_grande_prioritizes_individual_parcel_layers():
    capabilities = """<?xml version="1.0"?>
    <wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0">
      <wfs:FeatureTypeList>
        <wfs:FeatureType><wfs:Name>PraiaGrandePlantaCadastral:lotes_total</wfs:Name><wfs:Title>Lotes total</wfs:Title></wfs:FeatureType>
        <wfs:FeatureType><wfs:Name>PraiaGrandePlantaCadastral:Lotes_Fiscais</wfs:Name><wfs:Title>Lotes Fiscais</wfs:Title></wfs:FeatureType>
        <wfs:FeatureType><wfs:Name>PraiaGrandePlantaCadastral:lotes</wfs:Name><wfs:Title>Lotes</wfs:Title></wfs:FeatureType>
      </wfs:FeatureTypeList>
    </wfs:WFS_Capabilities>
    """
    layers = _cadastral_layers(capabilities)
    assert layers[0]["name"] == "PraiaGrandePlantaCadastral:Lotes_Fiscais"
    assert layers[1]["name"] == "PraiaGrandePlantaCadastral:lotes"


def test_rio_uses_geopal_as_secondary_parcel_source_when_territorial_layer_is_empty(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == RIO_ARCGIS_LAYER.removeprefix("https://pgeo3.rio.rj.gov.br") + "/query":
            return httpx.Response(200, json={"features": []})
        assert request.url.path == RIO_GEOPAL_LAYER.removeprefix("https://pgeo3.rio.rj.gov.br") + "/query"
        return httpx.Response(200, json={
            "features": [{
                "attributes": {
                    "objectid": 21, "chavegeo": "AB123456", "quadra": "Q-10", "lote": "L-7",
                },
                "geometry": {"x": -43.2, "y": -22.9},
            }],
        })

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(
        cache_dir=tmp_path / "cache", client=client, geocoder=FakeGeocoder()
    )
    records = adapter.search(SearchRequest(
        address="Avenida Rio Branco", number="1", city="Rio de Janeiro", state="RJ"
    ))
    client.close()

    assert len(records) == 1
    record = records[0]
    assert record.block == "Q-10"
    assert record.lot == "L-7"
    assert record.attributes["parcel_identifier"] == "AB123456"
    assert record.attributes["sql"] is None
    assert record.attributes["sql_status"] == "not_provided_by_layer"
    assert record.attributes["service_url"] == RIO_GEOPAL_LAYER



def test_santos_and_bertioga_public_wfs_sources_are_configured():
    assert MUNICIPAL_WFS[("santos", "sp")]["url"] == "https://egov.santos.sp.gov.br/geoserver/wfs"
    assert MUNICIPAL_WFS[("bertioga", "sp")]["url"] == "https://geoportal.bertioga.sp.gov.br/geoserver/ows"
    assert _official_url(MUNICIPAL_WFS[("santos", "sp")]["url"])
    assert _official_url(MUNICIPAL_WFS[("bertioga", "sp")]["url"])


def test_bertioga_wfs_returns_public_lot_registration_as_sql_candidate(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        if params.get("request") == "GetCapabilities":
            return httpx.Response(200, text=CAPABILITIES.replace(
                "cadastro:lotes", "CadastroLotes:Lotes"
            ).replace("Lotes e quadras cadastrais", "Cadastro de Lotes"))
        assert params.get("typeNames") == "CadastroLotes:Lotes"
        return httpx.Response(200, json={
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "id": "Lotes.123",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [-46.02, -23.85], [-46.019, -23.85],
                        [-46.019, -23.849], [-46.02, -23.85],
                    ]],
                },
                "properties": {
                    "geolot": "01.023.0042",
                    "quadra": "023",
                    "lote": "42",
                    "logradouro": "Rua Exemplo",
                    "numero": "100",
                    "area_terreno": 250,
                },
            }],
        })

    client = httpx.Client(transport=httpx.MockTransport(handler))
    class BertiogaGeocoder:
        def geocode(self, _query):
            return {"latitude": -23.8495, "longitude": -46.0195}

    adapter = OfficialMunicipalServicesAdapter(
        cache_dir=tmp_path / "cache", client=client, geocoder=BertiogaGeocoder()
    )
    records = adapter.search(SearchRequest(
        address="Rua Exemplo", number="100", city="Bertioga", state="SP"
    ))
    client.close()

    assert len(records) == 1
    record = records[0]
    assert record.city == "Bertioga"
    assert record.attributes["sql"] == "01.023.0042"
    assert record.attributes["sql_status"] == "provided_by_layer"
    assert record.block == "023"
    assert record.lot == "42"
    assert record.area_m2 == 250
    assert record.attributes["service_url"] == MUNICIPAL_WFS[("bertioga", "sp")]["url"]



def test_wfs_prefers_sql_layer_over_geometry_only_layer(tmp_path):
    capabilities = """<?xml version="1.0"?>
    <wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0">
      <wfs:FeatureTypeList>
        <wfs:FeatureType><wfs:Name>cadastro:lotes_geometria</wfs:Name><wfs:Title>Lotes geometria</wfs:Title></wfs:FeatureType>
        <wfs:FeatureType><wfs:Name>fiscal:lotes_sql</wfs:Name><wfs:Title>Cadastro fiscal SQL</wfs:Title></wfs:FeatureType>
      </wfs:FeatureTypeList>
    </wfs:WFS_Capabilities>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        if params.get("request") == "GetCapabilities":
            return httpx.Response(200, text=capabilities)
        assert params.get("typeNames") == "fiscal:lotes_sql"
        return httpx.Response(200, json={
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "id": "fiscal.9",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [-46.02, -23.85], [-46.019, -23.85],
                        [-46.019, -23.849], [-46.02, -23.85],
                    ]],
                },
                "properties": {"sq_l": "001.023.0042", "quadra": "023", "lote": "42"},
            }],
        })

    client = httpx.Client(transport=httpx.MockTransport(handler))
    class SantosGeocoder:
        def geocode(self, _query):
            return {"latitude": -23.8495, "longitude": -46.0195}

    adapter = OfficialMunicipalServicesAdapter(
        cache_dir=tmp_path / "cache", client=client, geocoder=SantosGeocoder()
    )
    records = adapter.search(SearchRequest(
        address="Praça Visconde de Mauá", city="Santos", state="SP"
    ))
    client.close()

    assert len(records) == 1
    assert records[0].attributes["sql"] == "001.023.0042"
    assert records[0].attributes["sql_status"] == "provided_by_layer"
    assert records[0].attributes["wfs_layer"] == "fiscal:lotes_sql"



def test_goiania_arcgis_maps_official_cadastral_fields_without_mislabeling_sql(tmp_path):
    class GoianiaGeocoder:
        def geocode(self, _query):
            return {"latitude": -16.6869, "longitude": -49.2648}

    def handler(request: httpx.Request) -> httpx.Response:
        expected_path = GOIANIA_ARCGIS_LAYER.removeprefix(
            "https://portalmapa.goiania.go.gov.br"
        )
        assert request.url.path == expected_path + "/query"
        params = dict(request.url.params)
        assert params["geometryType"] == "esriGeometryPoint"
        assert params["inSR"] == "4326"
        assert params["outSR"] == "4326"
        assert params["returnGeometry"] == "true"
        return httpx.Response(200, json={
            "features": [{
                "attributes": {
                    "OBJECTID": 812,
                    "nrinscr": "123.456.789",
                    "nmlogradou": "Rua Exemplo",
                    "nrimovel": "250",
                    "nrquadra": "Q-12",
                    "nrlote": "L-8",
                    "areaterr": 360.0,
                    "areaedif": 145.5,
                },
                "geometry": {
                    "rings": [[
                        [-49.2650, -16.6870], [-49.2640, -16.6870],
                        [-49.2640, -16.6860], [-49.2650, -16.6870],
                    ]],
                },
            }],
        })

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(
        cache_dir=tmp_path / "cache", client=client, geocoder=GoianiaGeocoder()
    )
    records = adapter.search(SearchRequest(
        address="Rua Exemplo", number="250", city="Goiânia", state="GO"
    ))
    client.close()

    assert len(records) == 1
    record = records[0]
    assert record.city == "Goiânia"
    assert record.state == "GO"
    assert record.address == "Rua Exemplo, 250"
    assert record.block == "Q-12"
    assert record.lot == "L-8"
    assert record.area_m2 == 360.0
    assert record.attributes["built_area_m2"] == 145.5
    assert record.attributes["municipal_registration_number"] == "123.456.789"
    assert record.attributes["sql"] is None
    assert record.attributes["sql_status"] == "not_provided_by_layer"
    assert record.attributes["service_url"] == GOIANIA_ARCGIS_LAYER
    assert record.attributes["official_source"] == "Prefeitura de Goiânia — Cadastro Imobiliário"
    assert json.loads(record.attributes["geometry_geojson"])["type"] == "Polygon"


def test_blumenau_arcgis_maps_lot_geometry_and_keeps_iq_distinct_from_sql(tmp_path):
    class BlumenauGeocoder:
        def geocode(self, _query):
            return {"latitude": -26.9194, "longitude": -49.0661}

    def handler(request: httpx.Request) -> httpx.Response:
        expected_path = BLUMENAU_ARCGIS_LAYER.removeprefix(
            "https://geo.blumenau.sc.gov.br"
        )
        assert request.url.path == expected_path + "/query"
        params = dict(request.url.params)
        assert params["geometryType"] == "esriGeometryPoint"
        assert params["inSR"] == "4326"
        assert params["outSR"] == "4326"
        return httpx.Response(200, json={
            "features": [{
                "attributes": {
                    "OBJECTID": 412,
                    "IQ": "BLU-001-0023",
                    "NUMLOTE": 23,
                    "NOBAIRRO": "CENTRO",
                    "AREA_CARTOGRAFICA": 410.0,
                },
                "geometry": {
                    "rings": [[
                        [-49.0662, -26.9195], [-49.0660, -26.9195],
                        [-49.0660, -26.9193], [-49.0662, -26.9195],
                    ]],
                },
            }],
        })

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(
        cache_dir=tmp_path / "cache", client=client, geocoder=BlumenauGeocoder()
    )
    records = adapter.search(SearchRequest(
        address="Rua XV de Novembro", number="100", city="Blumenau", state="SC"
    ))
    client.close()

    assert len(records) == 1
    record = records[0]
    assert record.city == "Blumenau"
    assert record.state == "SC"
    assert record.lot == "23"
    assert record.area_m2 == 410.0
    assert record.attributes["parcel_identifier"] == "BLU-001-0023"
    assert record.attributes["neighborhood"] == "CENTRO"
    assert record.attributes["sql"] is None
    assert record.attributes["sql_status"] == "not_provided_by_layer"
    assert record.attributes["service_url"] == BLUMENAU_ARCGIS_LAYER
    assert record.attributes["official_source"] == "Prefeitura de Blumenau — Cadastro de Lotes"
    assert json.loads(record.attributes["geometry_geojson"])["type"] == "Polygon"
