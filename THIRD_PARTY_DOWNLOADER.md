# Third-Party YouTube Downloader Module (Free-only)

File: `third_party_downloader.py`

## What it does
- Takes a YouTube URL
- Tries free third-party backends to resolve a direct media link
- Optionally downloads the file

## Provider chain
1. **Cobalt-compatible API**
   - Modern: `POST /`
   - Legacy: `POST /api/json`
   - Auto-discovers public unauthenticated instances via `https://instances.cobalt.best/instances.json`
2. **Piped API**
   - `GET /api/v1/streams/<video_id>`

## Usage
```bash
python3 third_party_downloader.py 'https://www.youtube.com/watch?v=VIDEO_ID'
python3 third_party_downloader.py 'https://www.youtube.com/watch?v=VIDEO_ID' --download --out downloads
```

## Optional env vars
- `COBALT_API_BASE` – force a specific cobalt instance
- `COBALT_API_KEY` – if your cobalt instance requires Api-Key auth
- `PIPED_API_BASE` – set a Piped base URL

## Integration idea for app.py
- On `/download` failures with yt-dlp, call `ThirdPartyDownloader.resolve(url)`
- If resolved, stream-download to `downloads/` and continue ZIP flow

## Reality check
Public free endpoints are unstable and frequently rate-limited/blocked by anti-bot controls.
For consistent results, run your own Cobalt instance (still free/open-source) and point `COBALT_API_BASE` to it.
