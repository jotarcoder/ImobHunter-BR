"""Single read-only municipal endpoint catalogue for the desktop settings UI.

URLs are taken directly from the actual search adapters. The catalogue does
not create new integrations or promise SQL/IPTU/geometry for every address.
"""
from __future__ import annotations

from dataclasses import dataclass

from imobhunter.sources.geosampa import DEFAULT_WFS_URL
from imobhunter.sources.rs_caxias_cadastre import CAXIAS_LOTS, CAXIAS_BLOCKS, CAXIAS_MAP_LOTS, CAXIAS_MAP_BLOCKS
from imobhunter.sources.pe_recife_cadastre import RECIFE_LOTS, RECIFE_LOTS_FEATURE
from imobhunter.sources.mg_juiz_cadastre import JUIZ_INSCRIPTIONS, JUIZ_PARCELS, JUIZ_PARCELS_LEGACY
from imobhunter.sources.sc_municipal_cadastre import (
    JOINVILLE_LAYER, JOINVILLE_POLYGON_LAYER, SAO_BENTO_SERVICE,
)
from imobhunter.sources.official_municipal_services import (
    BLUMENAU_ARCGIS_LAYER,
    DF_ARCGIS_LAYER,
    GOIANIA_ARCGIS_LAYER,
    MUNICIPAL_WFS,
    PORTO_ALEGRE_ARCGIS_LAYER,
    RECIFE_CKAN_API,
    RECIFE_IPTU_DATASET_ID,
    RIO_ARCGIS_LAYER,
    RIO_GEOPAL_LAYER,
)


@dataclass(frozen=True)
class MunicipalEndpoint:
    id: str
    city: str
    state: str
    label: str
    url: str
    kind: str
    layer: str
    limits: str
    role: str = "primary"

    def as_settings_item(self) -> dict[str, str]:
        return {
            "id": self.id, "city": self.city, "state": self.state,
            "label": self.label, "url": self.url, "kind": self.kind,
            "layer": self.layer, "limits": self.limits, "role": self.role,
        }


def municipal_endpoints() -> tuple[MunicipalEndpoint, ...]:
    """Describe ONLY endpoints reached by the current official adapters."""
    wfs = (
        ("praia_grande", "Praia Grande", "SP", "Cadastro de lotes: atributos dependem da camada"),
        ("santos", "Santos", "SP", "Cadastro municipal: SQL não garantido"),
        ("bertioga", "Bertioga", "SP", "Serviço indisponível em teste manual; não desativar TLS"),
        ("belo_horizonte", "Belo Horizonte", "MG", "Atributos fiscais dependem da camada"),
    )
    result: list[MunicipalEndpoint] = [
        MunicipalEndpoint(
            id="sao_paulo", city="São Paulo", state="SP", label="São Paulo capital — SP (GeoSampa)",
            url=DEFAULT_WFS_URL, kind="wfs", layer="geoportal:lote_cidadao",
            limits="Exclusivo do município de São Paulo. O número predial nem sempre coincide com o lote.",
        )
    ]
    for id_, city, state, limits in wfs:
        source = MUNICIPAL_WFS[(city.casefold(), state.casefold())]
        result.append(MunicipalEndpoint(
            id_, city, state, f"{city} — {state}", source["url"], "wfs",
            "Descoberta por GetCapabilities", limits,
        ))
    result.extend((
        MunicipalEndpoint(
            "rio_territorial", "Rio de Janeiro", "RJ",
            "Rio de Janeiro — RJ (imóveis territoriais)", RIO_ARCGIS_LAYER,
            "arcgis", "FeatureServer/0", "SQL/IPTU depende dos atributos oficiais.",
        ),
        MunicipalEndpoint(
            "rio_geopal", "Rio de Janeiro", "RJ",
            "Rio de Janeiro — RJ (GeoPAL)", RIO_GEOPAL_LAYER,
            "arcgis", "FeatureServer/0", "Fonte alternativa quando a territorial não retorna registros.",
            "fallback",
        ),
        MunicipalEndpoint(
            "df", "Brasília", "DF", "Brasília — DF (IDE-DF)",
            DF_ARCGIS_LAYER, "arcgis", "FeatureServer/0",
            "Apenas campos devolvidos pela camada são exibidos.",
        ),
        MunicipalEndpoint(
            "goiania", "Goiânia", "GO", "Goiânia — GO",
            GOIANIA_ARCGIS_LAYER, "arcgis", "MapServer/3",
            "Inscrição municipal não é automaticamente um SQL/IPTU.",
        ),
        MunicipalEndpoint(
            "blumenau", "Blumenau", "SC", "Blumenau — SC",
            BLUMENAU_ARCGIS_LAYER, "arcgis", "FeatureServer/0",
            "IQ é identificador cadastral, não SQL/IPTU.",
        ),
        MunicipalEndpoint(
            "recife", "Recife", "PE", "Recife — PE (IPTU dados abertos)",
            f"{RECIFE_CKAN_API}/package_show?id={RECIFE_IPTU_DATASET_ID}",
            "ckan", "Conjunto público CKAN",
            "O dataset não garante API de pesquisa por endereço nem geometria.",
        ),
        MunicipalEndpoint(
            "joinville", "Joinville", "SC", "Joinville — SC (inscrição por endereço)",
            JOINVILLE_LAYER, "arcgis", "SEFAZ MapServer/0",
            "Confere logradouro e número exatos; IQ é inscrição imobiliária, não SQL de SP.",
        ),
        MunicipalEndpoint(
            "joinville_polygons", "Joinville", "SC", "Joinville — SC (polígonos de lotes)",
            JOINVILLE_POLYGON_LAYER, "arcgis", "Hosted FeatureServer/0",
            "Somente geometria ligada à inscrição IQ; não consultar valores fiscais.",
            "fallback",
        ),
        MunicipalEndpoint(
            "sao_bento_enderecos", "São Bento do Sul", "SC",
            "São Bento do Sul — SC (endereços cadastrais)",
            SAO_BENTO_SERVICE + "/11", "arcgis", "MapServer/11",
            "Exige número e logradouro exatos; indisponibilidade não significa lote inexistente.",
        ),
        MunicipalEndpoint(
            "sao_bento_lotes", "São Bento do Sul", "SC",
            "São Bento do Sul — SC (lotes e geometrias)",
            SAO_BENTO_SERVICE + "/0", "arcgis", "MapServer/0",
            "Vinculado à tabela de endereços pelo código geolot.", "related",
        ),
        MunicipalEndpoint(
            "sao_bento_inscricao", "São Bento do Sul", "SC",
            "São Bento do Sul — SC (inscrição imobiliária)",
            SAO_BENTO_SERVICE + "/14", "arcgis", "MapServer/14",
            "Só cadastro de terreno vinculado por geolot; inscrições ambíguas não são assumidas.",
            "related",
        ),
        MunicipalEndpoint(
            "recife_esig_lotes", "Recife", "PE",
            "Recife — PE (ESIG lotes por endereço)",
            RECIFE_LOTS, "arcgis", "MapServer/3",
            "Quadra, lote e sequencial do imóvel somente com rua/número oficiais.",
        ),
        MunicipalEndpoint(
            "recife_esig_lotes_alternative", "Recife", "PE",
            "Recife — PE (ESIG lotes alternativo)",
            RECIFE_LOTS_FEATURE, "arcgis", "FeatureServer/3",
            "Fonte alternativa oficial se ESIG MapServer estiver indisponível.",
            "fallback",
        ),
        MunicipalEndpoint(
            "caxias_lotes", "Caxias do Sul", "RS",
            "Caxias do Sul — RS (lotes por endereço)",
            CAXIAS_LOTS, "arcgis", "FeatureServer/3",
            "Confere rua/número. Inscrição do lote não equivale a SQL/IPTU.",
        ),
        MunicipalEndpoint(
            "caxias_quadras", "Caxias do Sul", "RS",
            "Caxias do Sul — RS (quadras oficiais)",
            CAXIAS_BLOCKS, "arcgis", "FeatureServer/4",
            "Quadra vinculada ao lote por interseção espacial não ambígua.",
            "related",
        ),
        MunicipalEndpoint(
            "caxias_lotes_map", "Caxias do Sul", "RS",
            "Caxias do Sul — RS (lotes MapServer)",
            CAXIAS_MAP_LOTS, "arcgis", "MapServer/3",
            "Tentativa alternativa com a mesma base municipal; SQL/IPTU não homologado.",
            "fallback",
        ),
        MunicipalEndpoint(
            "caxias_quadras_map", "Caxias do Sul", "RS",
            "Caxias do Sul — RS (quadras MapServer)",
            CAXIAS_MAP_BLOCKS, "arcgis", "MapServer/4",
            "Camada alternativa de quadras oficiais, por interseção de polígonos.",
            "fallback",
        ),
        MunicipalEndpoint(
            "juiz_inscricao", "Juiz de Fora", "MG",
            "Juiz de Fora — MG (inscrição por endereço)",
            JUIZ_INSCRIPTIONS, "arcgis", "MapServer/27",
            "Confirma rua/número em cadastro municipal; usa INSCID, não SQL/SP.",
        ),
        MunicipalEndpoint(
            "juiz_lotes", "Juiz de Fora", "MG",
            "Juiz de Fora — MG (quadra, lote e geometria)",
            JUIZ_PARCELS, "arcgis", "MapServer/0",
            "Relacionamento por loteid; quadra/lote apenas se polígono inequívoco.",
            "related",
        ),
        MunicipalEndpoint(
            "juiz_lotes_legado", "Juiz de Fora", "MG",
            "Juiz de Fora — MG (quadra/lote complementar)",
            JUIZ_PARCELS_LEGACY, "arcgis", "FeatureServer/0",
            "Complementa quadra/lote por loteid exato; origem cadastral histórica.",
            "fallback",
        ),
        MunicipalEndpoint(
            "porto_alegre", "Porto Alegre", "RS",
            "Porto Alegre — RS (lotes fiscais)",
            PORTO_ALEGRE_ARCGIS_LAYER, "arcgis", "MapServer/0",
            "Lotes fiscais não garantem SQL/IPTU individual.",
        ),
    ))
    return tuple(result)


def settings_endpoint_rows() -> tuple[dict[str, str], ...]:
    """Make the GUI entries from constants used by the actual adapters."""
    return tuple(item.as_settings_item() for item in municipal_endpoints())
