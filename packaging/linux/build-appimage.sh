#!/usr/bin/env bash
set -euo pipefail
python -m pip install --upgrade pyinstaller
pyinstaller --noconfirm --windowed --name ImobHunter-BR imobhunter/__main__.py
echo "Binário preparado em dist/ImobHunter-BR. Empacotamento AppImage deve ocorrer na pipeline Linux."
