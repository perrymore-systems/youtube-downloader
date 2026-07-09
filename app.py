import os
import sys
import platform
import urllib.request
import json
import subprocess
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import stat
import shutil

PORT = int(os.environ.get('PORT', 8000))
def get_base_path():
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_path()
PUBLIC_DIR = os.path.join(BASE_DIR, 'public')

# Use user's home directory for binaries so they persist across runs when bundled
BIN_DIR = os.path.join(os.path.expanduser('~'), '.infinity-dl', 'bin')
if not os.path.exists(BIN_DIR):
    os.makedirs(BIN_DIR)

def get_platform_info():
    system = platform.system().lower()
    machine = platform.machine().lower()
    
    is_arm = 'arm' in machine or 'aarch64' in machine
    
    if system == 'windows':
        return 'win32', 'x64' # Usually x64 on Windows for these binaries
    elif system == 'darwin':
        return 'darwin', 'arm64' if is_arm else 'x64'
    elif system == 'linux':
        return 'linux', 'arm64' if is_arm else 'x64'
    
    return system, machine

def download_file(url, dest_path):
    if os.path.exists(dest_path):
        return dest_path
    
    print(f"Downloading {url} to {dest_path}...")
    try:
        urllib.request.urlretrieve(url, dest_path)
        # Make executable
        st = os.stat(dest_path)
        os.chmod(dest_path, st.st_mode | stat.S_IEXEC)
        print(f"Downloaded and made executable: {dest_path}")
    except Exception as e:
        print(f"Failed to download {url}: {e}")
        sys.exit(1)
    
    return dest_path

def setup_binaries():
    # If the environment has them natively (like in our Docker container), use those
    yt_dlp_sys = shutil.which('yt-dlp')
    ffmpeg_sys = shutil.which('ffmpeg')
    
    if yt_dlp_sys and ffmpeg_sys:
        print("Using system provided yt-dlp and ffmpeg.")
        return yt_dlp_sys, ffmpeg_sys
        
    system, arch = get_platform_info()
    
    # 1. Setup yt-dlp
    yt_dlp_url = ""
    yt_dlp_filename = "yt-dlp"
    if system == 'win32':
        yt_dlp_url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
        yt_dlp_filename = "yt-dlp.exe"
    elif system == 'darwin':
        yt_dlp_url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos"
    else:
        yt_dlp_url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp"
        
    yt_dlp_path = os.path.join(BIN_DIR, yt_dlp_filename)
    download_file(yt_dlp_url, yt_dlp_path)
    
    # 2. Setup ffmpeg (using ffmpeg-static releases)
    ffmpeg_filename = "ffmpeg.exe" if system == 'win32' else "ffmpeg"
    
    # Map to ffmpeg-static names
    os_name = system
    if system == 'darwin': os_name = 'darwin'
    elif system == 'win32': os_name = 'win32'
    else: os_name = 'linux'
    
    ffmpeg_url = f"https://github.com/eugeneware/ffmpeg-static/releases/download/b5.0.1/{os_name}-{arch}"
    if system == 'win32':
        ffmpeg_url += ".exe"
        
    ffmpeg_path = os.path.join(BIN_DIR, ffmpeg_filename)
    download_file(ffmpeg_url, ffmpeg_path)
    
    return yt_dlp_path, ffmpeg_path

yt_dlp_exe, ffmpeg_exe = setup_binaries()

class RequestHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        super().end_headers()
        
    def do_GET(self):
        parsed_url = urlparse(self.path)
        
        if parsed_url.path == '/api/process':
            query = parse_qs(parsed_url.query)
            url = query.get('url', [''])[0]
            
            if not url:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'Missing url parameter')
                return
                
            # Use yt-dlp to get formats. Use --no-playlist to ensure we only get the single video.
            cmd = [yt_dlp_exe, '--no-playlist', '--extractor-args', 'youtube:player_client=android', '-J', url]
            try:
                # Capture stderr as well to display useful errors
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                data = json.loads(result.stdout)
                
                formats = []
                for f in data.get('formats', []):
                    # Filter for decent video qualities, or combined formats
                    if f.get('vcodec') != 'none':
                        format_id = f.get('format_id')
                        ext = f.get('ext')
                        resolution = f.get('resolution') or f"{f.get('width')}x{f.get('height')}"
                        note = f.get('format_note', '')
                        fps = f.get('fps', '')
                        formats.append({
                            'id': format_id,
                            'ext': ext,
                            'resolution': resolution,
                            'note': note,
                            'fps': fps,
                            'has_audio': f.get('acodec') != 'none'
                        })
                
                # Sort formats
                formats = sorted(formats, key=lambda k: k.get('resolution') or '', reverse=True)
                
                # Deduplicate based on resolution
                seen_res = set()
                unique_formats = []
                for f in formats:
                    if f['resolution'] and f['resolution'] not in seen_res:
                        seen_res.add(f['resolution'])
                        unique_formats.append(f)
                
                response_data = {
                    'title': data.get('title'),
                    'thumbnail': data.get('thumbnail'),
                    'formats': unique_formats
                }
                
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response_data).encode('utf-8'))
            except subprocess.CalledProcessError as e:
                print(f"yt-dlp error (exit code {e.returncode}):\n{e.stderr}")
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Failed to extract video. It might be private or blocked.'}).encode('utf-8'))
            except Exception as e:
                print(f"Python error:\n{str(e)}")
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                
        elif parsed_url.path == '/api/download':
            query = parse_qs(parsed_url.query)
            url = query.get('url', [''])[0]
            format_id = query.get('format_id', ['best'])[0]
            
            if not url:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'Missing url parameter')
                return
                
            # Request format + best audio, and merge
            # If the selected format_id doesn't have audio, yt-dlp will merge it with bestaudio
            download_format = f"{format_id}+bestaudio/best" if format_id != 'best' else 'bestvideo+bestaudio/best'
            
            # Fetch video info to get the safe title for the filename
            try:
                info_cmd = [yt_dlp_exe, '--no-playlist', '--extractor-args', 'youtube:player_client=android', '-J', url]
                info_result = subprocess.run(info_cmd, capture_output=True, text=True, check=True)
                info_data = json.loads(info_result.stdout)
                safe_title = "".join([c for c in info_data.get('title', 'video') if c.isalpha() or c.isdigit() or c==' ']).rstrip()
            except:
                safe_title = "downloaded_video"

            # Create a temporary directory for the download
            import tempfile
            temp_dir = tempfile.mkdtemp()
            out_template = os.path.join(temp_dir, f"{safe_title}.%(ext)s")
            
            cmd = [
                yt_dlp_exe,
                '-f', download_format,
                '--merge-output-format', 'mp4',
                '--extractor-args', 'youtube:player_client=android',
                '--ffmpeg-location', ffmpeg_exe,
                '-o', out_template,
                url
            ]
            
            try:
                # We need to stream the file to the client, but yt-dlp merging requires the file to be fully downloaded and merged on disk first.
                # So we run it synchronously, then serve the file.
                print(f"Downloading and merging: {' '.join(cmd)}")
                subprocess.run(cmd, check=True)
                
                # Find the downloaded file
                downloaded_file = None
                for f in os.listdir(temp_dir):
                    if f.startswith(safe_title):
                        downloaded_file = os.path.join(temp_dir, f)
                        break
                        
                if downloaded_file:
                    self.send_response(200)
                    self.send_header('Content-Type', 'video/mp4')
                    self.send_header('Content-Disposition', f'attachment; filename="{safe_title}.mp4"')
                    self.end_headers()
                    
                    with open(downloaded_file, 'rb') as vf:
                        self.wfile.write(vf.read())
                        
                    # Clean up
                    os.remove(downloaded_file)
                    os.rmdir(temp_dir)
                else:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b"Failed to find downloaded file")
            except Exception as e:
                print(f"Error downloading video: {e}")
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode())
        else:
            # Serve static files
            if self.path == '/':
                target_path = os.path.join(PUBLIC_DIR, 'index.html')
            else:
                target_path = os.path.join(PUBLIC_DIR, self.path.lstrip('/'))
            
            if os.path.exists(target_path):
                self.send_response(200)
                if target_path.endswith('.css'):
                    self.send_header('Content-type', 'text/css')
                elif target_path.endswith('.js'):
                    self.send_header('Content-type', 'application/javascript')
                elif target_path.endswith('.html'):
                    self.send_header('Content-type', 'text/html')
                self.end_headers()
                with open(target_path, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()
            return

if __name__ == '__main__':
    import webbrowser
    server_address = ('', PORT)
    httpd = HTTPServer(server_address, RequestHandler)
    print(f"Server running on port {PORT}")
    
    # Only open browser if not in a cloud environment
    if not os.environ.get('PORT'):
        def open_browser():
            webbrowser.open(f'http://localhost:{PORT}')
        threading.Timer(1.0, open_browser).start()
    
    httpd.serve_forever()
