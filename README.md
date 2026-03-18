# MyYoutubeDownloader (beta)

Simple YouTube downloader web app:
- Search by query
- Select multiple videos
- Download selected items as MP3
- Get one ZIP with all files

## What engine is used
This build uses **Loader.to backend only** (working path) for downloads.
No multi-provider fallback chain in the app flow.

## Requirements
- Python 3.10+
- Packages:
  - `flask`
  - `yt-dlp` (used for search only)
  - `requests`
  - `gunicorn`
- HTTPS cert/key (for production HTTPS run)

## Local run
```bash
cd /root/.openclaw/workspace/japps/YoutubeDownloader
python3 app.py
```

## Production run (gunicorn)
```bash
cd /root/.openclaw/workspace/japps/YoutubeDownloader
source .env && gunicorn -b 0.0.0.0:${PORT} --timeout 180 --certfile=/etc/ssl/apps/server.crt --keyfile=/etc/ssl/apps/server.key --workers 2 app:app
```

## Systemd service example
```ini
[Unit]
Description=YouTube Downloader App
After=network.target

[Service]
Type=simple
User=appson
WorkingDirectory=/root/.openclaw/workspace/japps/YoutubeDownloader
Environment="PATH=/usr/local/bin:/usr/bin:/bin"
Environment="PYTHONUNBUFFERED=1"
EnvironmentFile=/root/.openclaw/workspace/japps/YoutubeDownloader/.env
ExecStart=/usr/local/bin/gunicorn -b 0.0.0.0:${PORT} --timeout 180 --certfile=/etc/ssl/apps/server.crt --keyfile=/etc/ssl/apps/server.key --workers 2 app:app
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

## UFW
```bash
source .env && sudo ufw allow ${PORT}/tcp
```

## IMPORTANT: cookies.txt from Chrome (local machine)
If you need an authenticated YouTube session in your own environment:

1. On your **local Chrome**, install extension: **Get cookies.txt LOCALLY**
2. Open `https://youtube.com` while logged in
3. Click extension icon
4. Click **"Export All Cookies"**
5. Save file as `cookies.txt`
6. Place it in app folder:
   - `/root/.openclaw/workspace/japps/YoutubeDownloader/cookies.txt`

> Never commit cookies to git.

## Git safety
This repo ignores sensitive/runtime files:
- `cookies.txt`
- `search.log`
- `downloads/`
- `downloads.zip`
- `gunicorn.ctl`

## Notes
- Search results come from yt-dlp search.
- Download conversion is handled by Loader.to backend.
- Multi-file download reliability improved with per-item retries and longer timeout.
