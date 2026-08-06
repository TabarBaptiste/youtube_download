"""Moteur de téléchargement : encapsule yt-dlp et FFmpeg."""
from __future__ import annotations

import logging
import re
import shutil
import time
import zipfile
from pathlib import Path
from typing import Optional

import yt_dlp

from . import config
from .models import AUDIO_FORMATS, Job

log = logging.getLogger("ytdl")

# Résolutions proposées dans l'interface, de la meilleure à la plus légère.
QUALITY_LADDER = ["2160", "1440", "1080", "720", "480", "360", "240"]


class Cancelled(Exception):
    """Levée depuis un hook de progression pour interrompre un téléchargement."""


def _sanitize(name: str) -> str:
    """Nettoie un nom de fichier des caractères problématiques."""
    name = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", name).strip(" .")
    return (name or "video")[:120]


def base_opts() -> dict:
    """Options yt-dlp communes à toutes les opérations."""
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "ignoreerrors": False,
        "retries": 5,
        "fragment_retries": 5,
        "socket_timeout": 30,
        "noplaylist": True,
        "restrictfilenames": False,
        "windowsfilenames": True,
        # Seul Deno est activé par défaut ; on déclare Node, fourni par l'image.
        "js_runtimes": config.JS_RUNTIMES,
    }
    if config.COOKIES_FILE:
        opts["cookiefile"] = config.COOKIES_FILE

    extractor_args: dict[str, dict] = {}
    if config.PLAYER_CLIENTS:
        extractor_args["youtube"] = {"player_client": config.PLAYER_CLIENTS}
    if config.POT_PROVIDER_URL:
        # Le plugin bgutil interroge ce service pour obtenir les PO Tokens que
        # YouTube réclame aux IP de datacenter, sans compte ni cookies.
        extractor_args["youtubepot-bgutilhttp"] = {"base_url": [config.POT_PROVIDER_URL]}
    if extractor_args:
        opts["extractor_args"] = extractor_args

    return opts


# --------------------------------------------------------------------------- #
# Métadonnées
# --------------------------------------------------------------------------- #

def fetch_info(url: str) -> dict:
    """Récupère les métadonnées d'une URL sans rien télécharger."""
    opts = base_opts() | {"skip_download": True, "extract_flat": "in_playlist"}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if e]
        first = entries[0] if entries else {}
        return {
            "isPlaylist": True,
            "title": info.get("title") or "Playlist",
            "uploader": info.get("uploader") or info.get("channel"),
            "thumbnail": first.get("thumbnails", [{}])[-1].get("url") if first.get("thumbnails") else None,
            "duration": None,
            "itemCount": len(entries),
            "qualities": QUALITY_LADDER,
            "webpageUrl": info.get("webpage_url") or url,
        }

    heights = sorted(
        {
            f["height"]
            for f in (info.get("formats") or [])
            if f.get("height") and f.get("vcodec") not in (None, "none")
        },
        reverse=True,
    )
    qualities = [str(h) for h in heights] or QUALITY_LADDER

    return {
        "isPlaylist": False,
        "title": info.get("title"),
        "uploader": info.get("uploader") or info.get("channel"),
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "itemCount": 1,
        "qualities": qualities,
        "webpageUrl": info.get("webpage_url") or url,
    }


# --------------------------------------------------------------------------- #
# Construction des options de téléchargement
# --------------------------------------------------------------------------- #

def _format_selector(job: Job) -> str:
    if job.fmt in AUDIO_FORMATS:
        return "bestaudio/best"

    height = "" if job.quality == "best" else f"[height<={job.quality}]"
    if job.fmt == "mp4":
        # On privilégie H.264 + AAC : le combo lisible partout sans réencodage.
        return (
            f"bv*{height}[vcodec^=avc1]+ba[acodec^=mp4a]/"
            f"bv*{height}+ba/b{height}/bv*+ba/b"
        )
    return f"bv*{height}+ba/b{height}/bv*+ba/b"


def build_opts(job: Job, outdir: Path) -> dict:
    opts = base_opts()
    opts["format"] = _format_selector(job)
    opts["outtmpl"] = str(outdir / "%(title).100B [%(id)s].%(ext)s")
    opts["noplaylist"] = not job.playlist
    postprocessors: list[dict] = []

    if job.fmt in AUDIO_FORMATS:
        pp = {"key": "FFmpegExtractAudio", "preferredcodec": job.fmt}
        if job.fmt in {"mp3", "m4a", "opus"}:
            pp["preferredquality"] = job.audio_bitrate
        postprocessors.append(pp)
    else:
        opts["merge_output_format"] = job.fmt
        if job.embed_subs:
            opts["writesubtitles"] = True
            opts["writeautomaticsub"] = True
            opts["subtitleslangs"] = ["fr", "en", "-live_chat"]
            postprocessors.append({"key": "FFmpegEmbedSubtitle", "already_have_subtitle": False})

    if job.embed_thumbnail and job.fmt in {"mp3", "m4a", "opus", "mp4", "mkv"}:
        opts["writethumbnail"] = True
        postprocessors.append({"key": "FFmpegThumbnailsConvertor", "format": "jpg"})
        postprocessors.append({"key": "EmbedThumbnail", "already_have_thumbnail": False})

    postprocessors.append({"key": "FFmpegMetadata", "add_metadata": True})
    opts["postprocessors"] = postprocessors

    if job.playlist:
        opts["playlistend"] = config.MAX_PLAYLIST_ITEMS

    return opts


# --------------------------------------------------------------------------- #
# Exécution
# --------------------------------------------------------------------------- #

def _human_speed(bps: Optional[float]) -> Optional[str]:
    if not bps:
        return None
    units = ["o/s", "Ko/s", "Mo/s", "Go/s"]
    value = float(bps)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}"
        value /= 1024
    return None


def _human_eta(seconds: Optional[float]) -> Optional[str]:
    if seconds is None:
        return None
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m{seconds % 60:02d}s"


def _make_hooks(job: Job):
    def progress_hook(d: dict) -> None:
        if job.cancel_requested:
            raise Cancelled()

        info = d.get("info_dict") or {}
        # Sur une playlist, on garde le titre de la playlist (nom de l'archive ZIP).
        playlist_title = info.get("playlist_title") or info.get("playlist")
        if playlist_title:
            job.title = playlist_title
        elif not job.title and info.get("title"):
            job.title = info["title"]
        if not job.thumbnail and info.get("thumbnail"):
            job.thumbnail = info["thumbnail"]
        if job.duration is None and info.get("duration"):
            job.duration = info["duration"]
        if not job.uploader and (info.get("uploader") or info.get("channel")):
            job.uploader = info.get("uploader") or info.get("channel")
        if info.get("n_entries"):
            job.total_items = info["n_entries"]
            job.current_item = info.get("playlist_index") or job.current_item

        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes") or 0
            item_ratio = (done / total) if total else 0.0
            # Sur une playlist, la progression globale mixe l'index et l'élément courant.
            base = (job.current_item - 1) / max(job.total_items, 1)
            job.progress = min(99.0, 100 * (base + item_ratio / max(job.total_items, 1)))
            job.speed = _human_speed(d.get("speed"))
            job.eta = _human_eta(d.get("eta"))
            job.status = "downloading"
            job.stage = (
                f"Téléchargement {job.current_item}/{job.total_items}"
                if job.total_items > 1
                else "Téléchargement"
            )
        elif d["status"] == "finished":
            job.speed = None
            job.eta = None
            job.status = "processing"
            job.stage = "Conversion (FFmpeg)"

    def postprocessor_hook(d: dict) -> None:
        if job.cancel_requested:
            raise Cancelled()
        if d.get("status") == "started":
            job.status = "processing"
            job.stage = f"Traitement : {d.get('postprocessor', 'FFmpeg')}"

    return progress_hook, postprocessor_hook


def _collect_outputs(outdir: Path) -> list[Path]:
    """Liste les fichiers médias produits, en écartant les résidus de yt-dlp."""
    skip_suffixes = {".part", ".ytdl", ".temp", ".jpg", ".png", ".webp", ".vtt", ".srt"}
    files = [
        p
        for p in sorted(outdir.iterdir())
        if p.is_file() and p.suffix.lower() not in skip_suffixes
    ]
    return files


def run_job(job: Job) -> None:
    """Exécute un job de bout en bout. Met à jour l'objet Job au fil de l'eau."""
    outdir = config.DOWNLOAD_DIR / job.id
    outdir.mkdir(parents=True, exist_ok=True)

    try:
        job.status = "downloading"
        job.stage = "Analyse de l'URL"
        opts = build_opts(job, outdir)
        hook, pp_hook = _make_hooks(job)
        opts["progress_hooks"] = [hook]
        opts["postprocessor_hooks"] = [pp_hook]

        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([job.url])

        files = _collect_outputs(outdir)
        if not files:
            raise RuntimeError("Aucun fichier produit par le téléchargement.")

        if len(files) > 1:
            job.stage = "Création de l'archive ZIP"
            archive = outdir / f"{_sanitize(job.title or 'playlist')}.zip"
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as zf:
                for f in files:
                    zf.write(f, arcname=f.name)
            for f in files:
                f.unlink(missing_ok=True)
            result = archive
        else:
            result = files[0]

        job.filepath = result
        job.filename = result.name
        job.filesize = result.stat().st_size
        job.progress = 100.0
        job.status = "done"
        job.stage = "Terminé"
        job.finished_at = time.time()
        job.speed = None
        job.eta = None

    except Cancelled:
        job.status = "cancelled"
        job.stage = "Annulé"
        job.finished_at = time.time()
        shutil.rmtree(outdir, ignore_errors=True)
    except Exception as exc:  # noqa: BLE001 - on remonte l'erreur à l'utilisateur
        log.exception("Job %s en échec", job.id)
        job.status = "error"
        job.stage = "Échec"
        job.error = friendly_error(exc)
        job.finished_at = time.time()
        shutil.rmtree(outdir, ignore_errors=True)


def friendly_error(exc: Exception) -> str:
    """Traduit les erreurs yt-dlp en messages lisibles côté interface."""
    # On retire le préfixe d'extracteur ("ERROR: [generic] xyz: ") et la cause
    # technique entre parenthèses, illisibles pour l'utilisateur.
    msg = str(exc).replace("ERROR: ", "").strip()
    msg = re.sub(r"^\[[^\]]+\]\s*[^:]{0,60}:\s*", "", msg)
    msg = re.sub(r"\s*\(caused by .*$", "", msg, flags=re.S).strip()
    lowered = msg.lower()

    if "private video" in lowered:
        return "Cette vidéo est privée."
    if "sign in to confirm" in lowered or "not a bot" in lowered:
        return (
            "YouTube demande une vérification depuis ce serveur. "
            "Vérifiez PLAYER_CLIENTS et POT_PROVIDER_URL (voir README), ou à "
            "défaut renseignez des cookies via COOKIES_FILE/COOKIES_B64."
        )
    if "members-only" in lowered or "premium" in lowered:
        return "Cette vidéo est réservée aux membres ou abonnés."
    if "age" in lowered and "restrict" in lowered:
        return "Vidéo soumise à une restriction d'âge : un fichier de cookies est nécessaire."
    if "video unavailable" in lowered or "removed" in lowered:
        return "Vidéo indisponible ou supprimée."
    if "404" in lowered or "not found" in lowered:
        return "Introuvable (404) : vérifiez l'URL."
    if "unsupported url" in lowered:
        return "URL non prise en charge."
    if "requested format" in lowered:
        return "Aucun flux ne correspond à la qualité demandée. Essayez « Maximale »."
    if "timed out" in lowered or "timeout" in lowered:
        return "Délai dépassé : le serveur distant ne répond pas."
    if "ffmpeg" in lowered:
        return f"Erreur de conversion FFmpeg : {msg[:160]}"
    return msg[:220] or "Erreur inconnue."
