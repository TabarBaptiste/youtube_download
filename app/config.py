"""Configuration de l'application, surchargeable par variables d'environnement."""
import base64
import logging
import os
from pathlib import Path
from typing import Optional


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# Répertoire de travail où les fichiers téléchargés sont stockés temporairement.
# Créé immédiatement : le fichier de cookies y est écrit plus bas.
DOWNLOAD_DIR = Path(os.environ.get("DOWNLOAD_DIR", BASE_DIR.parent / "downloads"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

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


def _materialize_cookies() -> Optional[str]:
    """Écrit sur disque les cookies fournis par variable d'environnement.

    Les PaaS (Railway, Render…) ne permettent pas de monter un fichier : on
    accepte donc le contenu directement, en clair (COOKIES_CONTENT) ou encodé
    en base64 (COOKIES_B64, à préférer car les retours à la ligne du format
    Netscape survivent mal à certains formulaires de configuration).

    yt-dlp réécrit le fichier de cookies après usage : on le place dans un
    répertoire inscriptible plutôt que de dépendre d'un montage en lecture seule.
    """
    raw = os.environ.get("COOKIES_CONTENT")
    encoded = os.environ.get("COOKIES_B64")

    if encoded and not raw:
        try:
            raw = base64.b64decode(encoded).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            logging.getLogger("ytdl.config").error(
                "COOKIES_B64 illisible, cookies ignorés : %s", exc
            )
            return None

    if not raw or not raw.strip():
        return None

    # Le format Netscape exige de vraies tabulations : un copier-coller qui les
    # a converties en espaces produit un fichier silencieusement inutilisable.
    if "\t" not in raw:
        logging.getLogger("ytdl.config").warning(
            "Les cookies ne contiennent aucune tabulation : le format Netscape "
            "est probablement corrompu (utilisez COOKIES_B64)."
        )

    target = DOWNLOAD_DIR / ".cookies.txt"
    target.write_text(raw if raw.endswith("\n") else raw + "\n", encoding="utf-8")
    target.chmod(0o600)
    return str(target)


COOKIES_FILE = COOKIES_FILE or _materialize_cookies()

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
