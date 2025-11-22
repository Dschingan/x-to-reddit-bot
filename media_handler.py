"""
Gelişmiş Medya İndirme ve İşleme Modülü
Video, resim ve GIF desteği ile kapsamlı hata yönetimi
"""

import os
import re
import time
import json
import hashlib
import requests
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import List, Optional, Dict, Tuple, Any
from urllib.parse import urlparse, parse_qs
import m3u8
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class MediaDownloader:
    """Gelişmiş medya indirme sınıfı"""
    
    # Desteklenen medya formatları
    IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp'}
    VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.webm', '.mkv'}
    
    # Kullanıcı ajanları
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    ]
    
    def __init__(self, 
                 connect_timeout: float = 10.0,
                 read_timeout: float = 120.0,
                 max_retries: int = 5,
                 chunk_size: int = 65536):
        """
        Args:
            connect_timeout: Bağlantı timeout (saniye)
            read_timeout: Okuma timeout (saniye)
            max_retries: Maksimum deneme sayısı
            chunk_size: İndirme chunk boyutu (byte)
        """
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.max_retries = max_retries
        self.chunk_size = chunk_size
        self.session = self._create_session()
        
    def _create_session(self) -> requests.Session:
        """Retry mekanizmalı session oluştur"""
        session = requests.Session()
        
        retry_strategy = Retry(
            total=self.max_retries,
            connect=3,
            read=3,
            backoff_factor=1.0,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET", "HEAD"]),
            raise_on_status=False
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy, pool_maxsize=10)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        return session
    
    def _get_random_user_agent(self) -> str:
        """Rastgele user agent döndür"""
        import random
        return random.choice(self.USER_AGENTS)
    
    def _get_headers(self) -> Dict[str, str]:
        """İndirme için HTTP headers"""
        return {
            "User-Agent": self._get_random_user_agent(),
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "DNT": "1",
            "Upgrade-Insecure-Requests": "1"
        }
    
    def _detect_media_type(self, url: str) -> str:
        """URL'den medya tipini tespit et"""
        url_lower = url.lower()
        
        # Video kontrolü
        if any(ext in url_lower for ext in ['.mp4', '.mov', '.avi', '.webm', '.mkv']):
            return 'video'
        
        if '.m3u8' in url_lower or 'playlist.m3u8' in url_lower:
            return 'hls_video'
        
        # Resim kontrolü
        if any(ext in url_lower for ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp']):
            return 'image'
        
        # Twitter/X özel URL'leri
        if 'pbs.twimg.com/media' in url_lower:
            return 'image'
        
        if 'video.twimg.com' in url_lower:
            return 'video'
        
        # Format parametresi kontrolü
        if 'format=jpg' in url_lower or 'format=png' in url_lower or 'format=webp' in url_lower:
            return 'image'
        
        return 'unknown'
    
    def _get_file_extension(self, url: str, media_type: str = None) -> str:
        """URL ve medya tipinden dosya uzantısı belirle"""
        # URL'den uzantı çıkar
        parsed = urlparse(url)
        path = parsed.path
        ext = os.path.splitext(path)[1].split('?')[0].lower()
        
        if ext in self.IMAGE_EXTENSIONS or ext in self.VIDEO_EXTENSIONS:
            return ext
        
        # Medya tipine göre varsayılan uzantı
        if media_type == 'video' or media_type == 'hls_video':
            return '.mp4'
        elif media_type == 'image':
            # Twitter için genelde jpg
            if 'twimg.com' in url:
                return '.jpg'
            return '.jpg'
        
        return '.jpg'  # Varsayılan
    
    def download_media(self, 
                      url: str, 
                      output_path: Optional[str] = None,
                      media_type: Optional[str] = None) -> Optional[str]:
        """
        Medya dosyasını indir
        
        Args:
            url: Medya URL'si
            output_path: Çıktı dosya yolu (None ise otomatik oluştur)
            media_type: Medya tipi ('image', 'video', 'hls_video')
        
        Returns:
            İndirilen dosya yolu veya None
        """
        try:
            # Medya tipini tespit et
            if media_type is None:
                media_type = self._detect_media_type(url)
            
            print(f"[+] Medya indiriliyor: {url[:80]}...")
            print(f"[+] Medya tipi: {media_type}")
            
            # Çıktı yolu oluştur
            if output_path is None:
                ext = self._get_file_extension(url, media_type)
                output_path = f"temp_media_{int(time.time())}_{os.getpid()}{ext}"
            
            # HLS video için özel işlem
            if media_type == 'hls_video':
                return self._download_hls_video(url, output_path)
            
            # Normal indirme (resim veya direkt video)
            return self._download_file(url, output_path)
            
        except Exception as e:
            print(f"[HATA] Medya indirme hatası: {e}")
            return None
    
    def _download_file(self, url: str, output_path: str) -> Optional[str]:
        """Dosyayı stream ederek indir"""
        headers = self._get_headers()
        
        # Önce HEAD request ile dosya boyutunu kontrol et
        try:
            head_response = self.session.head(url, headers=headers, timeout=5, allow_redirects=True)
            if head_response.status_code == 200:
                content_length = head_response.headers.get('Content-Length')
                if content_length:
                    size_mb = int(content_length) / (1024 * 1024)
                    print(f"[+] Dosya boyutu: {size_mb:.2f} MB")
        except Exception:
            pass
        
        # Stream download
        for attempt in range(1, self.max_retries + 1):
            try:
                with self.session.get(
                    url,
                    headers=headers,
                    stream=True,
                    timeout=(self.connect_timeout, self.read_timeout),
                    allow_redirects=True
                ) as response:
                    
                    if response.status_code != 200:
                        print(f"[UYARI] HTTP {response.status_code}: {url}")
                        if attempt < self.max_retries:
                            time.sleep(attempt * 2)
                            continue
                        return None
                    
                    # Dosyayı yaz
                    downloaded = 0
                    with open(output_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=self.chunk_size):
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                    
                    # Dosya boyutu kontrolü
                    if os.path.exists(output_path):
                        file_size = os.path.getsize(output_path)
                        if file_size > 0:
                            print(f"[+] İndirildi: {output_path} ({file_size / 1024:.1f} KB)")
                            return output_path
                        else:
                            print(f"[HATA] Boş dosya indirildi")
                            os.remove(output_path)
                            return None
                    
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.ChunkedEncodingError,
                    requests.exceptions.ReadTimeout,
                    requests.exceptions.Timeout) as e:
                print(f"[UYARI] İndirme hatası (deneme {attempt}/{self.max_retries}): {e}")
                if attempt < self.max_retries:
                    time.sleep(attempt * 2)
                    continue
            except Exception as e:
                print(f"[HATA] Beklenmeyen indirme hatası: {e}")
                break
        
        return None
    
    def _download_hls_video(self, hls_url: str, output_path: str) -> Optional[str]:
        """HLS video stream'ini indir"""
        print(f"[+] HLS video indiriliyor: {hls_url}")
        
        # Önce ffmpeg ile dene
        if shutil.which('ffmpeg'):
            try:
                print("[+] FFmpeg ile HLS indiriliyor...")
                cmd = [
                    'ffmpeg',
                    '-y',  # Üzerine yaz
                    '-i', hls_url,
                    '-c', 'copy',  # Codec kopyala (hızlı)
                    '-bsf:a', 'aac_adtstoasc',  # AAC fix
                    '-movflags', '+faststart',
                    output_path
                ]
                
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=300  # 5 dakika timeout
                )
                
                if result.returncode == 0 and os.path.exists(output_path):
                    file_size = os.path.getsize(output_path)
                    if file_size > 0:
                        print(f"[+] HLS video indirildi: {file_size / (1024*1024):.2f} MB")
                        return output_path
                else:
                    print(f"[UYARI] FFmpeg başarısız: {result.stderr[:200]}")
            except subprocess.TimeoutExpired:
                print("[UYARI] FFmpeg timeout")
            except Exception as e:
                print(f"[UYARI] FFmpeg hatası: {e}")
        
        # Python ile HLS indirme (fallback)
        try:
            print("[+] Python ile HLS indiriliyor...")
            return self._download_hls_python(hls_url, output_path)
        except Exception as e:
            print(f"[HATA] Python HLS indirme hatası: {e}")
            return None
    
    def _download_hls_python(self, hls_url: str, output_path: str) -> Optional[str]:
        """Python ile HLS segment'lerini indir ve birleştir"""
        try:
            # M3U8 playlist'i yükle
            playlist = m3u8.load(hls_url)
            
            if not playlist or not playlist.segments:
                print("[HATA] HLS playlist boş veya geçersiz")
                return None
            
            # Base URL
            base_url = hls_url.rsplit('/', 1)[0]
            
            print(f"[+] {len(playlist.segments)} segment indiriliyor...")
            
            # Segment'leri indir ve birleştir
            with open(output_path, 'wb') as output_file:
                for idx, segment in enumerate(playlist.segments):
                    segment_url = segment.uri
                    
                    # Relative URL'i absolute yap
                    if not segment_url.startswith('http'):
                        segment_url = f"{base_url}/{segment_url}"
                    
                    # Segment'i indir
                    try:
                        response = self.session.get(
                            segment_url,
                            headers=self._get_headers(),
                            timeout=(self.connect_timeout, 30),
                            stream=True
                        )
                        
                        if response.status_code == 200:
                            for chunk in response.iter_content(chunk_size=self.chunk_size):
                                if chunk:
                                    output_file.write(chunk)
                            
                            if (idx + 1) % 10 == 0:
                                print(f"[+] {idx + 1}/{len(playlist.segments)} segment indirildi")
                        else:
                            print(f"[UYARI] Segment {idx} indirilemedi: HTTP {response.status_code}")
                            return None
                            
                    except Exception as seg_error:
                        print(f"[HATA] Segment {idx} hatası: {seg_error}")
                        return None
            
            # Dosya kontrolü
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                print(f"[+] HLS video başarıyla indirildi: {output_path}")
                return output_path
            
            return None
            
        except Exception as e:
            print(f"[HATA] Python HLS indirme hatası: {e}")
            return None
    
    def download_multiple_images(self, 
                                 urls: List[str], 
                                 output_dir: Optional[str] = None) -> List[str]:
        """
        Birden fazla resmi indir ve duplicate'leri filtrele
        
        Args:
            urls: Resim URL listesi
            output_dir: Çıktı dizini (None ise geçici dizin)
        
        Returns:
            İndirilen benzersiz resim yolları listesi
        """
        if not urls:
            return []
        
        # Çıktı dizini
        if output_dir is None:
            output_dir = tempfile.gettempdir()
        
        downloaded_images = []
        image_hashes = set()
        
        print(f"[+] {len(urls)} resim indiriliyor...")
        
        for idx, url in enumerate(urls):
            try:
                # Medya tipini kontrol et
                media_type = self._detect_media_type(url)
                if media_type != 'image':
                    print(f"[!] Resim değil, atlanıyor: {url[:50]}")
                    continue
                
                # Dosya adı oluştur
                ext = self._get_file_extension(url, 'image')
                filename = os.path.join(output_dir, f"image_{int(time.time())}_{idx}{ext}")
                
                # İndir
                downloaded_path = self.download_media(url, filename, 'image')
                
                if downloaded_path and os.path.exists(downloaded_path):
                    # Duplicate kontrolü
                    file_hash = self._calculate_file_hash(downloaded_path)
                    
                    if file_hash and file_hash not in image_hashes:
                        image_hashes.add(file_hash)
                        downloaded_images.append(downloaded_path)
                        print(f"[+] Benzersiz resim: {downloaded_path}")
                    else:
                        print(f"[!] Duplicate resim, siliniyor: {downloaded_path}")
                        try:
                            os.remove(downloaded_path)
                        except Exception:
                            pass
                
            except Exception as e:
                print(f"[HATA] Resim {idx} indirme hatası: {e}")
        
        print(f"[+] Toplam {len(downloaded_images)} benzersiz resim indirildi")
        return downloaded_images
    
    def _calculate_file_hash(self, file_path: str) -> Optional[str]:
        """Dosya hash'ini hesapla (MD5)"""
        try:
            hasher = hashlib.md5()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b''):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception as e:
            print(f"[HATA] Hash hesaplama hatası: {e}")
            return None
    
    def get_video_info(self, video_path: str) -> Optional[Dict]:
        """Video bilgilerini al (ffprobe)"""
        if not shutil.which('ffprobe'):
            print("[UYARI] ffprobe bulunamadı")
            return None
        
        try:
            cmd = [
                'ffprobe',
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                '-show_streams',
                video_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                info = json.loads(result.stdout)
                
                # Format bilgileri
                format_info = info.get('format', {})
                duration = float(format_info.get('duration', 0))
                size = int(format_info.get('size', 0))
                
                # Video stream bilgileri
                video_stream = None
                for stream in info.get('streams', []):
                    if stream.get('codec_type') == 'video':
                        video_stream = stream
                        break
                
                return {
                    'duration': duration,
                    'size': size,
                    'width': video_stream.get('width', 0) if video_stream else 0,
                    'height': video_stream.get('height', 0) if video_stream else 0,
                    'codec': video_stream.get('codec_name', 'unknown') if video_stream else 'unknown',
                    'bitrate': int(format_info.get('bit_rate', 0))
                }
            
        except Exception as e:
            print(f"[HATA] Video bilgisi alma hatası: {e}")
        
        return None
    
    def cleanup(self):
        """Session'ı temizle"""
        try:
            self.session.close()
        except Exception:
            pass


# Global downloader instance
_downloader = None


def get_media_downloader() -> MediaDownloader:
    """Global media downloader instance'ını al"""
    global _downloader
    if _downloader is None:
        _downloader = MediaDownloader()
    return _downloader


def download_media(url: str, output_path: Optional[str] = None) -> Optional[str]:
    """Kolay kullanım için wrapper fonksiyon"""
    downloader = get_media_downloader()
    return downloader.download_media(url, output_path)


def download_multiple_images(urls: List[str]) -> List[str]:
    """Kolay kullanım için wrapper fonksiyon"""
    downloader = get_media_downloader()
    return downloader.download_multiple_images(urls)


if __name__ == "__main__":
    # Test
    print("=== Media Downloader Test ===\n")
    
    downloader = MediaDownloader()
    
    # Test URL (örnek)
    test_url = "https://pbs.twimg.com/media/example.jpg"
    print(f"Test URL: {test_url}")
    print(f"Medya tipi: {downloader._detect_media_type(test_url)}")
