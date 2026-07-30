"""API FastAPI + service des fichiers statiques."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from . import config
from .downloader import fetch_info, friendly_error
from .jobs import manager
from .models import ALL_FORMATS, Job

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    manager.shutdown()


app = FastAPI(title="YouTube Downloader", version="1.0.0", lifespan=lifespan)


# --------------------------------------------------------------------------- #
# Schémas
# --------------------------------------------------------------------------- #

class InfoRequest(BaseModel):
    url: str


class DownloadRequest(BaseModel):
    url: str
    format: str = Field(default="mp4")
    quality: str = Field(default="best")
    audioBitrate: str = Field(default="192")
    playlist: bool = False
    embedThumbnail: bool = True
    embedSubs: bool = False


def _validate_url(url: str) -> str:
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="URL invalide : elle doit commencer par http(s)://")
    return url


# --------------------------------------------------------------------------- #
# Routes API
# --------------------------------------------------------------------------- #

@app.get("/api/health")
async def health() -> dict:
    return {
        "ok": True,
        "maxPlaylistItems": config.MAX_PLAYLIST_ITEMS,
        "shareJobs": config.SHARE_JOBS,
    }


@app.post("/api/info")
async def info(req: InfoRequest) -> dict:
    url = _validate_url(req.url)
    try:
        return await run_in_threadpool(fetch_info, url)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=friendly_error(exc)) from exc


@app.post("/api/download")
async def download(req: DownloadRequest) -> dict:
    url = _validate_url(req.url)
    fmt = req.format.lower()
    if fmt not in ALL_FORMATS:
        raise HTTPException(status_code=400, detail=f"Format non supporté : {req.format}")

    job = Job(
        url=url,
        fmt=fmt,
        quality=req.quality,
        audio_bitrate=req.audioBitrate,
        playlist=req.playlist,
        embed_thumbnail=req.embedThumbnail,
        embed_subs=req.embedSubs,
    )
    manager.submit(job)
    return job.to_dict()


@app.get("/api/jobs")
async def list_jobs() -> list[dict]:
    # Hors mode partagé, exposer la liste complète reviendrait à dévoiler les
    # téléchargements des autres appareils : chacun suit ses jobs par leur id.
    if not config.SHARE_JOBS:
        raise HTTPException(status_code=403, detail="La mise en commun des jobs est désactivée")
    return [j.to_dict() for j in manager.list()]


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    job = manager.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job introuvable")
    return job.to_dict()


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict:
    if not manager.cancel(job_id):
        raise HTTPException(status_code=409, detail="Ce job ne peut plus être annulé")
    return {"ok": True}


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str) -> dict:
    if not manager.delete(job_id):
        raise HTTPException(status_code=404, detail="Job introuvable")
    return {"ok": True}


@app.get("/api/jobs/{job_id}/file")
async def get_file(job_id: str):
    job = manager.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job introuvable")
    if job.status != "done" or not job.filepath:
        raise HTTPException(status_code=409, detail="Le fichier n'est pas encore prêt")
    if not job.filepath.exists():
        raise HTTPException(status_code=410, detail="Le fichier a expiré et a été supprimé")
    return FileResponse(
        path=job.filepath,
        filename=job.filename,
        media_type="application/octet-stream",
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(_, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


# Le front est servi à la racine ; à monter en dernier pour ne pas masquer /api.
app.mount("/", StaticFiles(directory=config.STATIC_DIR, html=True), name="static")
