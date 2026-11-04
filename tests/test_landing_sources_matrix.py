"""The institutional site must accurately describe built-in and conditional sources."""
from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web/index.html").read_text(encoding="utf-8")
CSS = (ROOT / "web/styles.css").read_text(encoding="utf-8")


def test_sources_grouped_and_credentials_not_promised_as_unrestricted():
    for section in ('id="fontes-incluidas"', 'id="fontes-municipais"', 'id="fontes-restritas"'):
        assert section in HTML
    for name in ("GeoSampa", "IBGE / CNEFE / SIDRA", "OpenStreetMap",
                 "INDE e geosserviços", "ICMBio e IPHAN",
                 "Receita Federal / CNPJ", "Geocodificação nacional",
                 "Cadastro rural", "Fontes municipais próprias",
                 "Conecta gov.br / CNPJ", "SINTER / CIB",
                 "IPTU municipal restrito", "Cartórios / RI Digital"):
        assert name in HTML
    assert "não são liberadas por uma licença do ImobHunter" in HTML
    assert "não basta cadastrar um link protegido" in HTML
    assert "não contornamos autenticação" in HTML.lower()
    assert "credenciais oficiais" in HTML
    assert 'type="password"' not in HTML
    assert "client_secret=" not in HTML
    assert "authorization: bearer" not in HTML.lower()
    assert 'id="demoSearch"' not in HTML


def test_city_scope_and_offline_caveats():
    for city in ("São Paulo capital", "Praia Grande", "Santos", "Bertioga",
                 "Mogi das Cruzes", "Campinas", "Santo André", "Jundiaí",
                 "Belo Horizonte", "Juiz de Fora", "Rio de Janeiro capital",
                 "Brasília", "Goiânia", "Blumenau", "Joinville",
                 "São Bento do Sul", "Caxias do Sul", "Porto Alegre", "Recife"):
        assert city in HTML
    assert "indisponibilidade de serviços em testes" in HTML
    assert "não com consulta fiscal automática homologada" in HTML
    assert "Arquivos brutos não vêm nos instaladores" in HTML
    assert "GeoSampa</strong>" in HTML
    assert "OpenStreetMap</strong>" in HTML


def test_sources_remain_responsive_and_downloads_are_unchanged():
    assert "#fontes .sources-localities" in CSS
    assert "#fontes .sourcegrid-restricted" in CSS
    assert "@media(max-width:700px)" in CSS
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert version == "2.1.1"
    assert f"ImobHunter-BR-Setup-Windows-{version}.exe" in HTML
    assert HTML.count(f"Baixar v{version} →") == 4
    assert re.search(r'<section id="fontes"[^>]*>[\s\S]*?id="fontes-restritas"', HTML)
