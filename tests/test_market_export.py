from __future__ import annotations

import csv
import json
from pathlib import Path

from openpyxl import load_workbook

from imobhunter.application.market_export import export_market_results


def sample_results() -> list[dict]:
    return [
        {
            "name": "Empresa & Filhos",
            "cnpj": "12345678000190",
            "cnae": "4711301",
            "address": "Rua A, 10",
            "city": "São Paulo",
            "state": "SP",
            "latitude": -23.55,
            "longitude": -46.63,
            "distance_km": 1.25,
            "revenue_reported": 125000.0,
            "revenue_period": "2025",
            "revenue_estimate": None,
            "estimate_method": "",
            "revenue_status": "Divulgado",
            "source": "Base de teste",
            "updated_at": "2026-10-15",
        }
    ]


def test_export_market_results_csv_keeps_headers_and_records(tmp_path: Path) -> None:
    target = tmp_path / "market.csv"
    export_market_results(sample_results(), target, {"radius_km": "5"})

    with target.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["name"] == "Empresa & Filhos"
    assert rows[0]["cnpj"] == "12345678000190"
    assert rows[0]["source"] == "Base de teste"


def test_export_market_results_json_keeps_query_and_missing_values(tmp_path: Path) -> None:
    target = tmp_path / "market.json"
    export_market_results(sample_results(), target, {"radius_km": "5", "segment": "comércio"})

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["count"] == 1
    assert payload["query"]["segment"] == "comércio"
    assert payload["records"][0]["revenue_reported"] == 125000.0
    assert payload["records"][0]["revenue_estimate"] is None


def test_export_market_results_html_escapes_untrusted_values(tmp_path: Path) -> None:
    target = tmp_path / "market.html"
    export_market_results(sample_results(), target, {"segment": "<script>alert(1)</script>"})

    report = target.read_text(encoding="utf-8")
    assert "Empresa &amp; Filhos" in report
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in report
    assert "<script>alert(1)</script>" not in report


def test_export_market_results_xlsx_creates_readable_workbook(tmp_path: Path) -> None:
    target = tmp_path / "market.xlsx"
    export_market_results(sample_results(), target)

    sheet = load_workbook(target, read_only=True, data_only=True).active
    assert sheet["A1"].value == "name"
    assert sheet["A2"].value == "Empresa & Filhos"
    assert sheet["J2"].value == 125000.0
    assert sheet.freeze_panes == "A2"


def test_export_market_results_rejects_unknown_extension(tmp_path: Path) -> None:
    try:
        export_market_results(sample_results(), tmp_path / "market.pdf")
    except ValueError as exc:
        assert "Formato inválido" in str(exc)
    else:
        raise AssertionError("Expected unsupported export format to be rejected")
