#!/usr/bin/env bash
# Démarrage local : crée le venv si besoin, installe les dépendances, lance le serveur.
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg est introuvable. Installez-le puis relancez (apt install ffmpeg / brew install ffmpeg)." >&2
  exit 1
fi

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

PORT="${PORT:-8000}"
echo "→ http://localhost:${PORT}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}"
