#!/usr/bin/env bash
set -euo pipefail
python -m pip install --upgrade pyinstaller
pyinstaller --noconfirm --windowed --name ImobHunter-BR imobhunter/__main__.py
echo "Aplicativo preparado em dist/ImobHunter-BR.app."
