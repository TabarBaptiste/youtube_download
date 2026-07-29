FROM python:3.12-slim

# FFmpeg fusionne les flux et convertit en MP3/MP4.
# Node sert de runtime JavaScript à yt-dlp : sans lui, le « n challenge » de
# YouTube n'est pas résolu, ce qui provoque des 403 et limite la vidéo au 360p.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV DOWNLOAD_DIR=/data \
    PYTHONUNBUFFERED=1
RUN mkdir -p /data

EXPOSE 8000

# Railway (et la plupart des PaaS) assignent un port dynamique via $PORT et
# routent le trafic public vers celui-ci : écouter sur 8000 en dur laisse le
# conteneur sourd aux requêtes entrantes. La forme shell du CMD est nécessaire
# pour que ${PORT:-8000} soit interpolé au démarrage.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import os,urllib.request as u; p=os.environ.get('PORT','8000'); u.urlopen('http://127.0.0.1:'+p+'/api/health')"

CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
