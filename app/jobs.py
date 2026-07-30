"""Registre des jobs en mémoire, pool d'exécution et nettoyage périodique."""
from __future__ import annotations

import logging
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from . import config
from .downloader import run_job
from .models import Job

log = logging.getLogger("ytdl.jobs")


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=config.MAX_WORKERS, thread_name_prefix="dl")
        self._stop = threading.Event()
        self._cleaner = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleaner.start()

    # -- API publique ------------------------------------------------------ #

    def submit(self, job: Job) -> Job:
        with self._lock:
            self._jobs[job.id] = job
        self._pool.submit(run_job, job)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job or job.status in {"done", "error", "cancelled"}:
            return False
        job.cancel_requested = True
        return True

    def delete(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.pop(job_id, None)
        if not job:
            return False
        job.cancel_requested = True
        shutil.rmtree(config.DOWNLOAD_DIR / job.id, ignore_errors=True)
        return True

    def shutdown(self) -> None:
        self._stop.set()
        for job in self.list():
            job.cancel_requested = True
        self._pool.shutdown(wait=False, cancel_futures=True)

    # -- Nettoyage --------------------------------------------------------- #

    def _cleanup_loop(self) -> None:
        # Un premier passage immédiat purge les dossiers orphelins laissés par un
        # arrêt précédent, sans attendre le premier intervalle.
        try:
            self._cleanup_once()
        except Exception:  # noqa: BLE001
            log.exception("Échec du nettoyage initial")

        while not self._stop.wait(config.CLEANUP_INTERVAL_SECONDS):
            try:
                self._cleanup_once()
            except Exception:  # noqa: BLE001
                log.exception("Échec du nettoyage")

    def _cleanup_once(self) -> None:
        now = time.time()
        expired: list[str] = []
        with self._lock:
            for job_id, job in self._jobs.items():
                ref = job.finished_at or job.created_at
                if job.status in {"done", "error", "cancelled"} and now - ref > config.FILE_TTL_SECONDS:
                    expired.append(job_id)

        for job_id in expired:
            log.info("Nettoyage du job expiré %s", job_id)
            self.delete(job_id)

        # Répertoires orphelins (redémarrage du serveur, crash…).
        for path in config.DOWNLOAD_DIR.iterdir():
            if not path.is_dir():
                continue
            if self.get(path.name) is None and now - path.stat().st_mtime > config.FILE_TTL_SECONDS:
                shutil.rmtree(path, ignore_errors=True)


manager = JobManager()
