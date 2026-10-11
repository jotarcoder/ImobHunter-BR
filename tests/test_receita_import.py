from pathlib import Path
import zipfile

from imobhunter.application.receita_import import import_receita_archives


def test_import_official_receita_zip_to_local_sqlite(tmp_path: Path):
    db = tmp_path / "local.sqlite3"
    archive_path = tmp_path / "dados.zip"
    company_row = "12345678;EMPRESA TESTE LTDA;2062;49;100000,00;03;\n"
    # Official establishment layout: 30 fields, no header, semicolon separated.
    fields = ["12345678", "0001", "95", "1", "NOME FANTASIA", "02", "20260101", "00", ""] 
    fields += ["", "20200101", "6201501", "6201501", "R", "RUA TESTE", "10", "SALA 2", "CENTRO", "01001000", "SP", "3550308"]
    fields += ["11", "12345678", "", "", "", "", "contato@example.com", "", ""]
    fields = fields[:30]
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("F.K03200$Z.D10112.EMPRESAS.CSV", company_row.encode("latin-1"))
        archive.writestr("F.K03200$Z.D10112.ESTABELECIMENTOS.CSV", (";".join(fields) + "\n").encode("latin-1"))
    counts = import_receita_archives(db, [archive_path])
    assert counts["companies"] == 1
    assert counts["establishments"] == 1
