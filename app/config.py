"""Configuration de l'application, surchargeable par variables d'environnement."""
import os
from pathlib import Path


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# Répertoire de travail où les fichiers téléchargés sont stockés temporairement.
DOWNLOAD_DIR = Path(os.environ.get("DOWNLOAD_DIR", BASE_DIR.parent / "downloads"))

# Nombre de téléchargements traités en parallèle.
MAX_WORKERS = _int("MAX_WORKERS", 2)

# Durée de vie d'un fichier terminé (secondes) avant suppression automatique.
FILE_TTL_SECONDS = _int("FILE_TTL_SECONDS", 60 * 60)

# Fréquence du passage de nettoyage (secondes).
CLEANUP_INTERVAL_SECONDS = _int("CLEANUP_INTERVAL_SECONDS", 5 * 60)

# Nombre maximum de vidéos téléchargées quand l'URL est une playlist.
MAX_PLAYLIST_ITEMS = _int("MAX_PLAYLIST_ITEMS", 50)

# Fichier de cookies au format Netscape (facultatif) pour les vidéos qui
# exigent une session, ou quand YouTube demande une vérification.
COOKIES_FILE = os.environ.get("COOKIES_FILE") or None

# Clients du player YouTube utilisés par yt-dlp, séparés par des virgules.
# À laisser vide : les valeurs par défaut de yt-dlp sont les mieux tenues à jour,
# et forcer une liste (android, ios, web…) fait retomber la vidéo en 360p.
PLAYER_CLIENTS = [
    c.strip() for c in os.environ.get("PLAYER_CLIENTS", "").split(",") if c.strip()
]

# Runtimes JavaScript autorisés pour résoudre le « n challenge » de YouTube.
# Sans runtime, yt-dlp ne déchiffre pas les URLs des flux HD.
# yt-dlp attend un dict {runtime: {config}} ; la config par défaut suffit ici.
JS_RUNTIMES = {
    r.strip(): {}
    for r in os.environ.get("JS_RUNTIMES", "deno,node").split(",")
    if r.strip()
}

DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
