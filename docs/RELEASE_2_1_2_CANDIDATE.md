# ImobHunter-BR 2.1.2: Windows candidate, not yet released

The staged version includes PR #179 (market intelligence: company phone
and CNPJ-tag support) and PR #180 (SP IPTU Parquet import into indexed SQLite).

Version 2.1.2 is synchronized across project, Python package, Windows
version information and Inno Setup. The institutional site deliberately
still links to R2 version 2.1.1 until the new release is approved.

Build steps:
1. Green PR checks, merge, then green main CI.
2. Automatically build only Windows candidate. Store the EXE as a GitHub
   Actions artifact with SHA256 and an antivirus scan in a Windows runner.
3. Manually test Windows installation, license activation/restart, address
   searches, company ZIP imports with available phone/CNPJ, Parquet, and export.
4. Manually trigger remaining Linux/macOS installers after Windows QA.
5. Verify all four and authorize an explicit R2 publish separately; update
   the landing download links only after published binaries are verified.

Microsoft Defender previously detected Program:Win32/Contebrew.A!ml in
the older Windows installer. A clean scan on a single runner cannot guarantee
absence of risk in users' current antivirus definitions. Do not tell
users to suppress their antivirus. A verified publisher code signing
certificate is not yet available.

The macOS Apple Silicon cross-build is a known risk when PyArrow ships
native binary libraries; do not mark it supported for 2.1.2 without
architecture and smoke verification. No installer or database is uploaded
by this PR.
