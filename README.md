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
| `POT_PROVIDER_URL`         | –             | URL du fournisseur de PO Token (voir ci-dessous)   |
| `PLAYER_CLIENTS`           | –             | Clients du player yt-dlp, séparés par des virgules |
| `JS_RUNTIMES`              | `deno,node`   | Runtimes JS activés pour résoudre le n challenge   |
| `COOKIES_FILE`             | –             | Chemin d'un fichier de cookies au format Netscape  |
| `COOKIES_B64`              | –             | Contenu du fichier de cookies encodé en base64     |
| `COOKIES_CONTENT`          | –             | Contenu du fichier de cookies en clair             |

### Vérification anti-bot (« Sign in to confirm you're not a bot »)

Depuis un serveur hébergé (Railway, Render, VPS…), YouTube répond très souvent
« Sign in to confirm you're not a bot » : les plages d'IP des datacenters sont
filtrées, alors que la même requête passe sans problème depuis une connexion
résidentielle.

**Solution recommandée : un fournisseur de PO Token**, sans compte Google ni
cookie. Un service annexe génère les jetons que YouTube réclame :

```yaml
# docker-compose.yml — service déjà présent, image officielle sans état
bgutil:
  image: brainicism/bgutil-ytdlp-pot-provider
```

Puis, sur le service principal :

```bash
POT_PROVIDER_URL=http://bgutil:4416   # ou l'URL interne de votre PaaS
PLAYER_CLIENTS=tv_simply
```

`PLAYER_CLIENTS` est indispensable : le client par défaut de yt-dlp
(`android_vr`) n'utilise pas de PO Token, donc `POT_PROVIDER_URL` ne serait
jamais sollicité. `tv_simply` est le seul client testé qui tient un
téléchargement complet avec un jeton — `mweb`, souvent cité en référence,
obtient bien un jeton mais coupe le flux vidéo en 403 après quelques pour
cent.

Le runtime JavaScript compte aussi : yt-dlp exige Node ≥ 22 pour résoudre le
« n challenge », alors que le paquet Debian `nodejs` s'arrête à la version 20
et est silencieusement ignoré. L'image embarque donc Deno (`JS_RUNTIMES`
par défaut), seul runtime activé nativement par yt-dlp.

### Cookies (solution de repli)

Si le fournisseur de PO Token ne suffit plus face à un blocage plus strict,
les cookies restent disponibles en dernier recours. Fournir des cookies de
session lève également ce blocage.

Exportez les cookies de `youtube.com` au format Netscape depuis votre navigateur
(extension « Get cookies.txt LOCALLY » ou équivalent).

**En local ou en Docker** — montez le fichier et pointez `COOKIES_FILE` dessus
(les deux lignes concernées sont déjà présentes, commentées, dans
`docker-compose.yml`) :

```bash
COOKIES_FILE=/chemin/vers/cookies.txt uvicorn app.main:app
```

**Sur un PaaS** — impossible d'y monter un fichier : passez le contenu par
variable d'environnement. Préférez `COOKIES_B64`, car le format Netscape repose
sur de vraies tabulations que les formulaires de configuration convertissent
souvent en espaces, ce qui rend le fichier silencieusement inutilisable :

```bash
base64 -w0 < cookies.txt    # macOS : base64 -i cookies.txt
```

Collez le résultat dans une variable `COOKIES_B64`. Au démarrage, l'application
le décode vers un fichier privé (`chmod 600`) dans `DOWNLOAD_DIR` et le
transmet à yt-dlp.

Deux points à connaître avant d'utiliser vos propres cookies : ils donnent accès
à votre compte Google, donc traitez-les comme un mot de passe (jamais dans le
dépôt — `.gitignore` les couvre déjà) ; et YouTube invalide régulièrement les
sessions utilisées depuis une IP de datacenter, ce qui peut déconnecter le
compte. Un compte secondaire dédié évite les deux problèmes.

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
