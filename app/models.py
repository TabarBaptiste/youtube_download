"""Modèles de données partagés entre l'API et le moteur de téléchargement."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

Status = Literal["queued", "downloading", "processing", "done", "error", "cancelled"]

# Formats de sortie proposés par l'interface.
AUDIO_FORMATS = {"mp3", "m4a", "opus", "wav"}
VIDEO_FORMATS = {"mp4", "mkv", "webm"}
ALL_FORMATS = AUDIO_FORMATS | VIDEO_FORMATS


@dataclass
class Job:
    """Un téléchargement (une vidéo ou une playlist entière)."""

    url: str
    fmt: str = "mp4"
    quality: str = "best"  # "best" ou une hauteur en pixels ("1080")
    audio_bitrate: str = "192"
    playlist: bool = False
    embed_thumbnail: bool = True
    embed_subs: bool = False

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: Status = "queued"
    progress: float = 0.0
    speed: Optional[str] = None
    eta: Optional[str] = None
    stage: str = "En attente"
    title: Optional[str] = None
    thumbnail: Optional[str] = None
    duration: Optional[int] = None
    uploader: Optional[str] = None
    error: Optional[str] = None

    filepath: Optional[Path] = None
    filename: Optional[str] = None
    filesize: Optional[int] = None

    total_items: int = 1
    current_item: int = 1

    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    cancel_requested: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "format": self.fmt,
            "quality": self.quality,
            "status": self.status,
            "progress": round(self.progress, 1),
            "speed": self.speed,
            "eta": self.eta,
            "stage": self.stage,
            "title": self.title,
            "thumbnail": self.thumbnail,
            "duration": self.duration,
            "uploader": self.uploader,
            "error": self.error,
            "filename": self.filename,
            "filesize": self.filesize,
            "totalItems": self.total_items,
            "currentItem": self.current_item,
            "createdAt": self.created_at,
            "downloadUrl": f"/api/jobs/{self.id}/file" if self.status == "done" else None,
        }
