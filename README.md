# YT Downloader

Web app simple pour télécharger une vidéo (ou une playlist) depuis une URL, la
convertir au format voulu et récupérer le fichier depuis un navigateur — PC ou
téléphone.

Le serveur fait tout le travail : extraction des flux via **yt-dlp**, fusion et
conversion via **FFmpeg**. Le client se contente d'afficher la progression et de
récupérer le fichier final.

## Fonctionnalités

- **Vidéo** : MP4, MKV, WebM — de 360p à 4K, ou la meilleure qualité disponible.
- **Audio** : MP3, M4A, Opus, WAV avec choix du débit (128 / 192 / 320 kbps).
- **Aperçu automatique** : titre, chaîne, durée et miniature dès que l'URL est collée.
- **Progression en direct** : pourcentage, débit, temps restant, annulation possible.
- **Playlists** : téléchargement en lot, livré sous forme d'archive ZIP.
- **Options** : intégration de la miniature dans le fichier, incrustation des sous-titres.
- **PWA** : installable sur mobile (« Ajouter à l'écran d'accueil »), interface responsive,
  liste des téléchargements conservée après un rechargement de page.
- **Nettoyage automatique** : les fichiers sont supprimés du serveur après expiration.

Les URLs ne sont pas limitées à YouTube : tout site géré par yt-dlp fonctionne.

## Démarrage rapide

### Docker (recommandé)

```bash
docker compose up -d --build
```

L'application est disponible sur <http://localhost:8000>.

### Local

FFmpeg doit être installé (`apt install ffmpeg` ou `brew install ffmpeg`).

```bash
./run.sh
```

Ou manuellement :

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Depuis un téléphone sur le même réseau, ouvrez `http://<ip-de-la-machine>:8000`.

## Configuration

Toutes les options passent par des variables d'environnement.

| Variable                   | Défaut        | Rôle                                               |
| -------------------------- | ------------- | -------------------------------------------------- |
| `DOWNLOAD_DIR`             | `./downloads` | Répertoire de travail des fichiers produits        |
| `MAX_WORKERS`              | `2`           | Téléchargements simultanés                         |
| `FILE_TTL_SECONDS`         | `3600`        | Durée de conservation d'un fichier terminé         |
| `CLEANUP_INTERVAL_SECONDS` | `300`         | Fréquence du passage de nettoyage                  |
| `MAX_PLAYLIST_ITEMS`       | `50`          | Nombre maximum de vidéos par playlist              |
| `COOKIES_FILE`             | –             | Fichier de cookies au format Netscape              |
| `PLAYER_CLIENTS`           | –             | Clients du player yt-dlp, séparés par des virgules |

### Cookies

Si le serveur reçoit un message du type « Sign in to confirm you're not a bot »,
exportez vos cookies au format Netscape depuis votre navigateur, puis :

```bash
COOKIES_FILE=/chemin/vers/cookies.txt uvicorn app.main:app
```

En Docker, montez le fichier et décommentez les deux lignes correspondantes dans
`docker-compose.yml`.

## API

| Méthode  | Route                   | Description                              |
| -------- | ----------------------- | ---------------------------------------- |
| `GET`    | `/api/health`           | État du service                          |
| `POST`   | `/api/info`             | Métadonnées d'une URL (`{"url": "..."}`) |
| `POST`   | `/api/download`         | Lance un téléchargement, renvoie un job  |
| `GET`    | `/api/jobs`             | Liste des jobs                           |
| `GET`    | `/api/jobs/{id}`        | État et progression d'un job             |
| `GET`    | `/api/jobs/{id}/file`   | Récupère le fichier produit              |
| `POST`   | `/api/jobs/{id}/cancel` | Annule un job en cours                   |
| `DELETE` | `/api/jobs/{id}`        | Supprime le job et son fichier           |

Corps accepté par `POST /api/download` :

```json
{
  "url": "https://www.youtube.com/watch?v=...",
  "format": "mp4",
  "quality": "1080",
  "audioBitrate": "192",
  "playlist": false,
  "embedThumbnail": true,
  "embedSubs": false
}
```

Exemple complet :

```bash
ID=$(curl -s -X POST localhost:8000/api/download \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://www.youtube.com/watch?v=...","format":"mp3"}' | jq -r .id)

curl -s localhost:8000/api/jobs/$ID          # suivi de la progression
curl -OJ localhost:8000/api/jobs/$ID/file    # récupération du fichier
```

## Architecture

```
app/
  main.py        API FastAPI + service des fichiers statiques
  jobs.py        Registre des jobs, pool de threads, nettoyage périodique
  downloader.py  Options yt-dlp, hooks de progression, conversion FFmpeg, ZIP
  models.py      Modèle Job et sérialisation JSON
  config.py      Configuration via variables d'environnement
  static/        Front-end (HTML/CSS/JS sans dépendance) + manifeste PWA
```

Les jobs sont conservés en mémoire : un redémarrage vide la liste, et les
répertoires orphelins sont supprimés au passage de nettoyage suivant.

## Notes

- Une seule instance est prévue : l'état des jobs n'est pas partagé entre
  plusieurs processus. Avec un reverse proxy, laissez `MAX_WORKERS` piloter la
  concurrence plutôt que de multiplier les workers uvicorn.
- Derrière nginx, désactivez la mise en tampon des réponses pour les gros
  fichiers (`proxy_buffering off;`) et relevez `client_max_body_size`.
- yt-dlp doit être maintenu à jour : `pip install -U yt-dlp` (ou reconstruire
  l'image) quand une extraction cesse de fonctionner.
