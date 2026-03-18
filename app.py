#!/usr/bin/env python3
"""
YouTube Downloader App
- Text area for multiple search queries (one per line)
- Search YouTube for each query, show checkbox list
- Download selected items, zip, and serve
"""

import os
import json
import zipfile
import subprocess
import tempfile
import sys

# Fix Flask dotenv compatibility issue - patch it before importing Flask
import flask.cli
original_load_dotenv = flask.cli.load_dotenv
def patched_load_dotenv(*args, **kwargs):
    # Skip dotenv loading entirely
    return None
flask.cli.load_dotenv = patched_load_dotenv

from flask import Flask, request, render_template_string, send_file, after_this_request
from yt_dlp import YoutubeDL
from third_party_downloader import ThirdPartyDownloader

app = Flask(__name__)
APP_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIES_FILE = os.path.join(APP_DIR, 'cookies.txt')
DOWNLOADS_DIR = os.path.join(APP_DIR, 'downloads')
ZIP_OUTPUT = os.path.join(APP_DIR, 'downloads.zip')

# Ensure downloads directory exists
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>YouTube Downloader</title>
    <style>
        * { box-sizing: border-box; }
        body { 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
            background: #0f0f0f; 
            color: #f1f1f1; 
            margin: 0; 
            padding: 20px;
            min-height: 100vh;
        }
        h1 { color: #ff0000; font-size: 2.5em; margin-bottom: 30px; }
        .container { max-width: 900px; margin: 0 auto; }
        textarea { 
            width: 100%; height: 120px; 
            background: #1a1a1a; color: #fff; 
            border: 1px solid #333; border-radius: 8px;
            padding: 15px; font-size: 16px;
            resize: vertical;
        }
        button { 
            background: #ff0000; color: white; 
            border: none; padding: 15px 30px; 
            font-size: 18px; border-radius: 8px; 
            cursor: pointer; margin-top: 15px;
            font-weight: bold;
        }
        button:hover { background: #cc0000; }
        .results { margin-top: 30px; }
        .video-item { 
            background: #1a1a1a; padding: 15px; 
            margin: 10px 0; border-radius: 8px;
            display: flex; align-items: center; gap: 15px;
        }
        .video-item input[type="checkbox"] { 
            width: 24px; height: 24px; cursor: pointer; 
        }
        .video-item label { 
            flex: 1; cursor: pointer; font-size: 16px;
            display: flex; align-items: center; gap: 10px;
        }
        .video-item img { 
            width: 120px; height: 68px; 
            object-fit: cover; border-radius: 4px; 
        }
        .video-info { display: flex; flex-direction: column; }
        .video-title { font-weight: bold; color: #fff; }
        .video-duration { color: #888; font-size: 14px; }
        .download-section { margin-top: 30px; }
        .download-btn { background: #00aa00; }
        .download-btn:hover { background: #008800; }
        .status { 
            padding: 15px; margin: 15px 0; 
            border-radius: 8px; font-size: 16px;
        }
        .status.info { background: #0066cc; }
        .status.error { background: #cc0000; }
        .status.success { background: #00aa00; }
        .query-section { margin-bottom: 30px; }
        .query-title { color: #888; margin-bottom: 10px; font-size: 14px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎬 YouTube Downloader</h1>
        
        {% if status %}
        <div class="status {{ status_type }}">{{ status }}</div>
        {% endif %}
        
        <div class="query-section">
            <div class="query-title">Enter search queries (one per line):</div>
            <form method="POST" action="/">
                <textarea name="queries" placeholder="song name 1&#10;song name 2&#10;artist name">{{ queries }}</textarea>
                <button type="submit" name="action" value="search">🔍 Search YouTube</button>
            </form>
        </div>
        
        {% if results %}
        <div class="results">
            <h2>Select videos to download (<span id="selected-count">{{ selected_count }}</span> selected):</h2>
            <form method="POST" action="/" id="download-form">
                <input type="hidden" name="queries" value="{{ queries }}">
                {% for video in results %}
                <div class="video-item">
                    <input type="checkbox" id="v{{ loop.index0 }}" name="video" value="{{ video.id }}" onchange="updateCount()">
                    <label for="v{{ loop.index0 }}">
                        <img src="{{ video.thumbnail }}" alt="thumb">
                        <div class="video-info">
                            <span class="video-title">{{ video.title }}</span>
                            <span class="video-duration">{{ video.duration }} • {{ video.channel }}</span>
                        </div>
                    </label>
                </div>
                {% endfor %}
                <div class="download-section">
                    <button type="button" onclick="submitDownload()" class="download-btn">⬇️ Download Selected (<span id="btn-count">{{ selected_count }}</span>)</button>
                </div>
            </form>
        </div>
        
        <script>
        function updateCount() {
            const checkboxes = document.querySelectorAll('input[name="video"]:checked');
            const count = checkboxes.length;
            document.getElementById('selected-count').textContent = count;
            document.getElementById('btn-count').textContent = count;
        }
        function submitDownload() {
            const form = document.getElementById('download-form');
            let actionInput = form.querySelector('input[name="action"]');
            if (!actionInput) {
                actionInput = document.createElement('input');
                actionInput.type = 'hidden';
                actionInput.name = 'action';
                form.appendChild(actionInput);
            }
            actionInput.value = 'download';
            form.submit();
        }
        </script>
        {% endif %}
        
        {% if zip_ready %}
        <div class="download-section">
            <a href="/download.zip">
                <button class="download-btn">📦 Download ZIP ({{ zip_size }})</button>
            </a>
        </div>
        {% endif %}
    </div>
</body>
</html>
'''

LOG_FILE = 'search.log'

def log(msg):
    """Log to file."""
    with open(LOG_FILE, 'a') as f:
        from datetime import datetime
        f.write(f"[{datetime.now().isoformat()}] {msg}\n")


def safe_filename(name: str, max_len: int = 140) -> str:
    """Create a filesystem-safe filename."""
    if not name:
        return "audio"
    bad = '<>:"/\\|?*\n\r\t'
    cleaned = ''.join('_' if c in bad else c for c in name).strip().rstrip('.')
    return (cleaned[:max_len] or "audio")

def search_youtube(query, max_results=10):
    """Search YouTube using yt-dlp with flat extraction."""
    log(f"SEARCH START: query='{query}', max_results={max_results}")
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,  # Only get metadata, not full info
        'skip_download': True,
    }
    
    videos = []
    try:
        with YoutubeDL(ydl_opts) as ydl:
            search_query = f"ytsearch{2*max_results}:{query}"  # Get extra in case some fail
            log(f"  Executing: {search_query}")
            results = ydl.extract_info(search_query, download=False)
            log(f"  Results type: {type(results)}, keys: {results.keys() if results else None}")
            
            if results and 'entries' in results:
                for entry in results['entries'][:max_results]:
                    try:
                        if entry:
                            duration = entry.get('duration')
                            if duration:
                                duration = int(duration)
                                mins = duration // 60
                                secs = duration % 60
                                duration_str = f"{mins}:{secs:02d}"
                            else:
                                duration_str = "N/A"
                            
                            videos.append({
                                'id': entry.get('id', ''),
                                'title': entry.get('title', 'Unknown'),
                                'thumbnail': entry.get('thumbnail', ''),
                                'duration': duration_str,
                                'channel': entry.get('channel', 'Unknown'),
                                'url': f"https://www.youtube.com/watch?v={entry.get('id', '')}"
                            })
                            log(f"    Added: {entry.get('title', 'Unknown')[:50]}")
                    except Exception as entry_err:
                        log(f"    Entry error: {entry_err}")
                        continue
            
            log(f"  Found {len(videos)} videos")
            return videos
    except Exception as e:
        log(f"  ERROR: {type(e).__name__}: {e}")
        import traceback
        log(f"  Trace: {traceback.format_exc()}")
    
    return videos

@app.route('/', methods=['GET', 'POST'])
def index():
    status = None
    status_type = 'info'
    results = []
    queries = ''
    total_videos = 0
    selected_count = 0
    zip_ready = False
    zip_size = ''
    
    if request.method == 'POST':
        queries = request.form.get('queries', '').strip()
        action = request.form.get('action', 'search')
        
        if action == 'search':
            # Parse queries (one per line)
            query_lines = [q.strip() for q in queries.split('\n') if q.strip()]
            
            all_results = []
            for query in query_lines:
                videos = search_youtube(query)
                all_results.extend(videos)
            
            results = all_results
            total_videos = len(results)
            
            if total_videos == 0:
                status = "No results found. Try different keywords."
                status_type = 'error'
        
        elif action == 'download':
            selected = request.form.getlist('video')
            selected_count = len(selected)
            log(f"DOWNLOAD action: selected={selected}, count={selected_count}, queries={queries}")
            
            if selected_count == 0:
                status = "No videos selected!"
                status_type = 'error'
            else:
                status = f"Downloading {selected_count} video(s)... please wait"
                status_type = 'info'
                
                # Clear previous downloads
                for f in os.listdir(DOWNLOADS_DIR):
                    os.remove(os.path.join(DOWNLOADS_DIR, f))
                if os.path.exists(ZIP_OUTPUT):
                    os.remove(ZIP_OUTPUT)
                
                # Build id -> original title map from current queries
                id_to_title = {}
                query_lines = [q.strip() for q in queries.split('\n') if q.strip()]
                for query in query_lines:
                    for v in search_youtube(query):
                        vid = v.get('id')
                        if vid and vid not in id_to_title:
                            id_to_title[vid] = v.get('title') or vid

                # Download selected videos using the working provider only (Loader.to)
                downloaded = []
                downloaded_by_id = {}
                tpd = ThirdPartyDownloader()
                for video_id in selected:
                    video_url = f"https://www.youtube.com/watch?v={video_id}"

                    # Retry per-item to reduce one-off provider timeouts
                    success = False
                    last_error = None
                    for attempt in range(1, 4):
                        try:
                            res = tpd.resolve(video_url, audio_only=True)
                            if res.ok and res.media_url:
                                temp_name = (res.filename or f"{video_id}.mp3").replace('/', '_')
                                out_path = os.path.join(DOWNLOADS_DIR, temp_name)
                                tpd.download_to_file(res.media_url, out_path)
                                downloaded.append(temp_name)
                                downloaded_by_id[video_id] = temp_name
                                log(f"LOADER OK: {video_id} attempt={attempt}")
                                success = True
                                break
                            last_error = res.error
                            log(f"LOADER FAIL: {video_id} attempt={attempt} err={res.error}")
                        except Exception as e:
                            last_error = str(e)
                            log(f"LOADER ERROR: {video_id} attempt={attempt} {type(e).__name__}: {e}")

                    if not success:
                        log(f"LOADER FINAL FAIL: {video_id} err={last_error}")

                # Rename downloaded GUID files to original search titles (just before zipping)
                for video_id, temp_name in downloaded_by_id.items():
                    src = os.path.join(DOWNLOADS_DIR, temp_name)
                    if not os.path.exists(src):
                        continue
                    base_title = safe_filename(id_to_title.get(video_id, video_id))
                    dst_name = f"{base_title}.mp3"
                    dst = os.path.join(DOWNLOADS_DIR, dst_name)
                    i = 2
                    while os.path.exists(dst) and os.path.abspath(dst) != os.path.abspath(src):
                        dst_name = f"{base_title} ({i}).mp3"
                        dst = os.path.join(DOWNLOADS_DIR, dst_name)
                        i += 1
                    if os.path.abspath(src) != os.path.abspath(dst):
                        os.replace(src, dst)
                        log(f"RENAMED: {temp_name} -> {dst_name}")
                
                # Create ZIP
                if os.listdir(DOWNLOADS_DIR):
                    with zipfile.ZipFile(ZIP_OUTPUT, 'w', zipfile.ZIP_DEFLATED) as zipf:
                        for f in os.listdir(DOWNLOADS_DIR):
                            fpath = os.path.join(DOWNLOADS_DIR, f)
                            if os.path.isfile(fpath):
                                zipf.write(fpath, f)
                    
                    zip_size = f"{os.path.getsize(ZIP_OUTPUT) / (1024*1024):.1f} MB"
                    zip_ready = True
                    status = f"✅ Downloaded {len(downloaded)} video(s) and created ZIP!"
                    status_type = 'success'
                else:
                    status = "No files were downloaded"
                    status_type = 'error'
    
    return render_template_string(HTML_TEMPLATE,
        status=status,
        status_type=status_type,
        results=results,
        queries=queries,
        total_videos=total_videos,
        selected_count=selected_count,
        zip_ready=zip_ready,
        zip_size=zip_size
    )

@app.route('/download.zip')
def download_zip():
    if os.path.exists(ZIP_OUTPUT):
        return send_file(ZIP_OUTPUT, as_attachment=True, download_name='youtube_downloads.zip')
    return "No ZIP file available", 404

if __name__ == '__main__':
    # Disable dotenv loading to avoid version conflict
    os.environ['FLASK_APP'] = ''
    os.environ['FLASK_ENV'] = ''
    
    # SSL context for HTTPS
    ssl_context = (
        '/etc/ssl/apps/server.crt',
        '/etc/ssl/apps/server.key'
    )
    
    # Run on port 18484, HTTPS only
    app.run(host='0.0.0.0', port=18484, debug=False, ssl_context=ssl_context)