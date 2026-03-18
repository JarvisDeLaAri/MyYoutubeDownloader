#!/usr/bin/env python3
"""
Third-party YouTube downloader resolver (free providers only).

Goal:
- Accept a YouTube URL
- Resolve it to a downloadable media URL through third-party free APIs
- Optionally download the file

Providers (in order):
1) Cobalt-compatible API (self-hosted preferred)
2) Piped API (public instance, direct audio/video stream URLs)
"""

from __future__ import annotations

import os
import re
import json
import requests
from dataclasses import dataclass
from typing import Dict, Optional, List
from urllib.parse import urlparse, parse_qs


@dataclass
class DownloadResult:
    ok: bool
    provider: str
    source_url: str
    media_url: Optional[str] = None
    filename: Optional[str] = None
    error: Optional[str] = None
    meta: Optional[Dict] = None


class ProviderBase:
    name = "base"

    def resolve(self, youtube_url: str, audio_only: bool = True) -> DownloadResult:
        raise NotImplementedError


class CobaltProvider(ProviderBase):
    """
    Cobalt API provider.

    Supports:
    - modern instances: POST /
    - legacy instances (v7 style): POST /api/json
    """

    name = "cobalt"

    def __init__(self, api_base: Optional[str] = None, api_key: Optional[str] = None):
        self.api_base = (api_base or os.getenv("COBALT_API_BASE") or "").strip()
        self.api_key = api_key or os.getenv("COBALT_API_KEY")

    @staticmethod
    def _discover_free_instances(limit: int = 3) -> List[str]:
        """Best-effort discovery from instances.cobalt.best (prefers auth=false + youtube=true)."""
        try:
            r = requests.get(
                "https://instances.cobalt.best/instances.json",
                timeout=15,
                headers={"User-Agent": "Gobling-Downloader/1.0"},
            )
            arr = r.json() if r.ok else []
            candidates = []
            for row in arr:
                if not row.get("online"):
                    continue
                info = row.get("info") or {}
                if info.get("auth") is False:
                    proto = row.get("protocol", "https")
                    api = row.get("api")
                    if api:
                        candidates.append(f"{proto}://{api}")
            return candidates[:limit]
        except Exception:
            return []

    @staticmethod
    def _parse_response(data: Dict, provider_name: str, source_url: str) -> DownloadResult:
        status = data.get("status")
        if status in {"tunnel", "redirect"} and data.get("url"):
            return DownloadResult(
                True,
                provider_name,
                source_url,
                media_url=data.get("url"),
                filename=data.get("filename"),
                meta=data,
            )

        if status == "picker":
            picker = data.get("picker") or []
            if picker and isinstance(picker, list):
                first = picker[0]
                return DownloadResult(
                    True,
                    provider_name,
                    source_url,
                    media_url=first.get("url"),
                    filename=first.get("filename") or data.get("filename"),
                    meta=data,
                )

        # legacy cobalt may return {status:'error', text:'...'}
        return DownloadResult(False, provider_name, source_url, error=f"status={status} data={json.dumps(data)[:400]}")

    def resolve(self, youtube_url: str, audio_only: bool = True) -> DownloadResult:
        bases = []
        if self.api_base:
            bases.append(self.api_base)
        else:
            bases.extend(self._discover_free_instances(limit=4))

        if not bases:
            return DownloadResult(False, self.name, youtube_url, error="no cobalt instance available")

        errors = []
        for base in bases:
            base = base.rstrip("/")

            # modern endpoint
            modern_headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "Gobling-Downloader/1.0",
            }
            if self.api_key:
                modern_headers["Authorization"] = f"Api-Key {self.api_key}"

            modern_payload = {
                "url": youtube_url,
                "downloadMode": "audio" if audio_only else "auto",
                "audioFormat": "mp3" if audio_only else "best",
                "audioBitrate": "128",
                "filenameStyle": "basic",
            }

            try:
                r = requests.post(base + "/", headers=modern_headers, json=modern_payload, timeout=25)
                if "application/json" in (r.headers.get("content-type") or ""):
                    parsed = self._parse_response(r.json(), self.name, youtube_url)
                    if parsed.ok:
                        return parsed
                    errors.append(f"{base}/ -> {parsed.error}")
                else:
                    errors.append(f"{base}/ -> non-json response")
            except Exception as e:
                errors.append(f"{base}/ -> {e}")

            # legacy endpoint
            legacy_headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "Gobling-Downloader/1.0",
            }
            legacy_payload = {
                "url": youtube_url,
                "isAudioOnly": bool(audio_only),
                "aFormat": "mp3",
                "vCodec": "h264",
                "filenamePattern": "basic",
            }
            try:
                r = requests.post(base + "/api/json", headers=legacy_headers, json=legacy_payload, timeout=25)
                if "application/json" in (r.headers.get("content-type") or ""):
                    parsed = self._parse_response(r.json(), self.name, youtube_url)
                    if parsed.ok:
                        return parsed
                    errors.append(f"{base}/api/json -> {parsed.error}")
                else:
                    errors.append(f"{base}/api/json -> non-json response")
            except Exception as e:
                errors.append(f"{base}/api/json -> {e}")

        return DownloadResult(False, self.name, youtube_url, error=" || ".join(errors[:8]))


class LoaderToProvider(ProviderBase):
    """
    Loader.to backend (free web service).

    Flow:
    1) GET /ajax/download.php?format=mp3&url=<youtube_url>
    2) poll returned progress_url (or /api/progress?id=<id>)
    3) take download_url when ready
    """

    name = "loader_to"

    def __init__(self, api_base: Optional[str] = None):
        self.api_base = (api_base or os.getenv("LOADER_API_BASE") or "https://p.savenow.to").rstrip("/")

    def resolve(self, youtube_url: str, audio_only: bool = True) -> DownloadResult:
        fmt = "mp3" if audio_only else "mp4"
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://en.loader.to/4/",
            "Accept": "application/json,text/plain,*/*",
        }
        try:
            start = requests.get(
                self.api_base + "/ajax/download.php",
                params={"format": fmt, "url": youtube_url},
                headers=headers,
                timeout=30,
            )
            data = start.json()
        except Exception as e:
            return DownloadResult(False, self.name, youtube_url, error=f"start failed: {e}")

        if not data.get("success"):
            return DownloadResult(False, self.name, youtube_url, error=f"start error: {json.dumps(data)[:400]}")

        job_id = data.get("id")
        progress_url = data.get("progress_url") or f"{self.api_base}/api/progress?id={job_id}"

        for _ in range(90):  # ~180s max (provider queues can be slow)
            try:
                pr = requests.get(progress_url, headers=headers, timeout=20)
                pd = pr.json()
            except Exception:
                pd = {}

            done_url = pd.get("download_url") or pd.get("url")
            if done_url:
                file_ext = "mp3" if audio_only else "mp4"
                filename = f"{job_id}.{file_ext}"
                return DownloadResult(
                    True,
                    self.name,
                    youtube_url,
                    media_url=done_url,
                    filename=filename,
                    meta={"job_id": job_id, "progress": pd.get("progress"), "provider": pd},
                )

            # finished but no URL => fail early
            if pd.get("progress") == 1000 and not done_url:
                return DownloadResult(False, self.name, youtube_url, error=f"finished without url: {json.dumps(pd)[:400]}")

            import time
            time.sleep(2)

        return DownloadResult(False, self.name, youtube_url, error="timeout waiting for provider")


class PipedProvider(ProviderBase):
    """
    Piped API provider (free public API).
    Uses /api/v1/streams/<videoId> to get stream URLs.
    """

    name = "piped"

    def __init__(self, api_base: Optional[str] = None):
        self.api_base = (api_base or os.getenv("PIPED_API_BASE") or "https://piped.video").rstrip("/")

    @staticmethod
    def _extract_video_id(url: str) -> Optional[str]:
        try:
            p = urlparse(url)
            if p.hostname in {"youtu.be"}:
                return p.path.strip("/")
            if p.hostname and "youtube" in p.hostname:
                qs = parse_qs(p.query)
                if "v" in qs:
                    return qs["v"][0]
                m = re.search(r"/shorts/([A-Za-z0-9_-]{6,})", p.path)
                if m:
                    return m.group(1)
        except Exception:
            return None
        return None

    def resolve(self, youtube_url: str, audio_only: bool = True) -> DownloadResult:
        vid = self._extract_video_id(youtube_url)
        if not vid:
            return DownloadResult(False, self.name, youtube_url, error="cannot extract video id")

        endpoint = f"{self.api_base}/api/v1/streams/{vid}"
        try:
            r = requests.get(endpoint, timeout=30, headers={"User-Agent": "Gobling-Downloader/1.0"})
            if r.status_code != 200:
                return DownloadResult(False, self.name, youtube_url, error=f"http {r.status_code}")
            data = r.json()
        except Exception as e:
            return DownloadResult(False, self.name, youtube_url, error=f"request failed: {e}")

        if audio_only:
            audio = data.get("audioStreams") or []
            if not audio:
                return DownloadResult(False, self.name, youtube_url, error="no audio streams")
            # Pick highest bitrate available
            audio_sorted = sorted(audio, key=lambda x: x.get("bitrate") or 0, reverse=True)
            pick = audio_sorted[0]
            return DownloadResult(
                True,
                self.name,
                youtube_url,
                media_url=pick.get("url"),
                filename=f"{vid}.m4a",
                meta={"bitrate": pick.get("bitrate"), "mimeType": pick.get("mimeType")},
            )

        video = data.get("videoStreams") or []
        if not video:
            return DownloadResult(False, self.name, youtube_url, error="no video streams")
        pick = sorted(video, key=lambda x: x.get("quality") or 0, reverse=True)[0]
        return DownloadResult(
            True,
            self.name,
            youtube_url,
            media_url=pick.get("url"),
            filename=f"{vid}.mp4",
            meta={"quality": pick.get("quality"), "mimeType": pick.get("mimeType")},
        )


class ThirdPartyDownloader:
    def __init__(self):
        # Working path only: Loader.to backend
        self.providers: List[ProviderBase] = [
            LoaderToProvider(),
        ]

    def resolve(self, youtube_url: str, audio_only: bool = True) -> DownloadResult:
        errors = []
        for provider in self.providers:
            res = provider.resolve(youtube_url, audio_only=audio_only)
            if res.ok and res.media_url:
                return res
            errors.append(f"{provider.name}: {res.error}")
        return DownloadResult(False, "chain", youtube_url, error=" | ".join(errors))

    @staticmethod
    def download_to_file(media_url: str, out_path: str, timeout: int = 180) -> str:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with requests.get(media_url, stream=True, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"}) as r:
            r.raise_for_status()
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)
        return out_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Resolve/download YouTube links using free third-party providers")
    parser.add_argument("url", help="YouTube URL")
    parser.add_argument("--video", action="store_true", help="Prefer video instead of audio")
    parser.add_argument("--download", action="store_true", help="Actually download the resolved media")
    parser.add_argument("--out", default="downloads", help="Output directory")
    args = parser.parse_args()

    d = ThirdPartyDownloader()
    result = d.resolve(args.url, audio_only=not args.video)

    print(json.dumps({
        "ok": result.ok,
        "provider": result.provider,
        "media_url": result.media_url,
        "filename": result.filename,
        "error": result.error,
        "meta": result.meta,
    }, ensure_ascii=False, indent=2))

    if args.download and result.ok and result.media_url:
        filename = result.filename or "download.bin"
        out_path = os.path.join(args.out, filename)
        ThirdPartyDownloader.download_to_file(result.media_url, out_path)
        print(f"saved: {out_path}")
