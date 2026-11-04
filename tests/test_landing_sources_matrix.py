"""Institutional landing and detailed source matrix reflect existing integration contracts."""
from html.parser import HTMLParser
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
DETAILS = (WEB / "fontes.html").read_text(encoding="utf-8")
CSS = (WEB / "styles.css").read_text(encoding="utf-8")


class Markup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.links = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "a":
            self.links.append(a.get("href", ""))


def test_source_summary_has_link_and_respects_size_budget():
    assert 'href="fontes.html"' in INDEX
    assert (WEB / "fontes.html").is_file()
    assert "<strong>GeoSampa</strong>" in INDEX
    assert "<strong>OpenStreetMap</strong>" in INDEX
    assert "Conecta gov.br depende de credenciais oficiais" in INDEX
    assert (WEB / "index.html").stat().st_size < 22_000
    p = Markup()
    p.feed(DETAILS)
    assert {"fontes", "fontes-incluidas", "fontes-municipais", "fontes-restritas"} <= p.ids
    assert "index.html#downloads" in p.links


def test_detailed_sources_are_separated_by_access_mode():
    for name in ("GeoSampa", "IBGE / CNEFE / SIDRA", "OpenStreetMap",
                 "INDE e geosserviços", "ICMBio e IPHAN", "Receita Federal / CNPJ",
                 "Geocodificação nacional", "Cadastro rural", "Fontes municipais próprias",
                 "Conecta gov.br / CNPJ", "SINTER / CIB", "IPTU municipal restrito",
                 "Cartórios / RI Digital"):
        assert name in DETAILS
    assert "não são liberadas por uma licença do ImobHunter" in DETAILS
    assert "não basta cadastrar um link protegido" in DETAILS
    assert "não contornamos autenticação" in DETAILS.lower()
    for sensitive in ('type="password"', "client_secret=", "authorization: bearer"):
        assert sensitive not in DETAILS.lower()


def test_documented_municipal_coverage_has_limitations():
    for city in ("São Paulo capital", "Praia Grande", "Santos", "Bertioga",
                 "Mogi das Cruzes", "Campinas", "Santo André", "Jundiaí",
                 "Belo Horizonte", "Juiz de Fora", "Rio de Janeiro capital",
                 "Brasília", "Goiânia", "Blumenau", "Joinville",
                 "São Bento do Sul", "Caxias do Sul", "Porto Alegre", "Recife"):
        assert city in DETAILS
    assert "indisponibilidade de serviços em testes" in DETAILS
    assert "não com consulta fiscal automática homologada" in DETAILS
    assert "Arquivos brutos não vêm nos instaladores" in DETAILS


def test_styles_responsive_and_installer_links_intact():
    assert "#fontes .sources-localities" in CSS
    assert "#fontes .sourcegrid-restricted" in CSS
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert version == "2.1.1"
    assert f"ImobHunter-BR-Setup-Windows-{version}.exe" in INDEX
    assert INDEX.count(f"Baixar v{version} →") == 4
    assert 'id="demoSearch"' not in INDEX
