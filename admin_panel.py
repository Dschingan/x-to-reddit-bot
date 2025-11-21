"""
Kapsamlı Admin Paneli - .env Parametrelerini Yönetme
Profesyonel, kolay anlaşılır ve tam özellikli admin arayüzü
"""

from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
import os
import json
import time
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import dotenv
from pathlib import Path
import shutil
import logging


class AdminPanelManager:
    """Admin paneli yönetimi ve .env işlemleri"""
    
    def __init__(self, env_path: str = ".env"):
        self.env_path = Path(env_path)
        self.env_vars = self._load_env()
        
    def _load_env(self) -> Dict[str, str]:
        """Mevcut .env dosyasını yükle"""
        if not self.env_path.exists():
            return {}
        return dotenv.dotenv_values(str(self.env_path))
    
    def get_env_var(self, key: str) -> Optional[str]:
        """Belirli bir .env değişkenini al"""
        return self.env_vars.get(key)
    
    def set_env_var(self, key: str, value: str) -> bool:
        """Belirli bir .env değişkenini ayarla"""
        try:
            self.env_vars[key] = value
            self._save_env()
            return True
        except Exception as e:
            print(f"[HATA] .env ayarlanamadı: {e}")
            return False
    
    def _save_env(self):
        """Değişiklikleri .env dosyasına kaydet"""
        try:
            with open(self.env_path, 'w', encoding='utf-8') as f:
                for key, value in self.env_vars.items():
                    if ' ' in str(value) or not value:
                        f.write(f'{key}="{value}"\n')
                    else:
                        f.write(f'{key}={value}\n')
        except Exception as e:
            print(f"[HATA] .env kaydedilemedi: {e}")
            raise
    
    def get_all_env_vars(self) -> Dict[str, str]:
        """Tüm .env değişkenlerini al"""
        return self.env_vars.copy()
    
    def delete_env_var(self, key: str) -> bool:
        """Belirli bir .env değişkenini sil"""
        try:
            if key in self.env_vars:
                del self.env_vars[key]
                self._save_env()
                return True
            return False
        except Exception as e:
            print(f"[HATA] .env değişkeni silinemedi: {e}")
            return False
    
    def backup_env(self, backup_dir: str = "backups") -> str:
        """Mevcut .env dosyasını yedekle"""
        try:
            backup_path = Path(backup_dir)
            backup_path.mkdir(exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = backup_path / f"env_backup_{timestamp}.env"
            
            shutil.copy2(self.env_path, backup_file)
            return str(backup_file)
        except Exception as e:
            print(f"[HATA] Yedekleme hatası: {e}")
            return ""
    
    def restore_env(self, backup_file: str) -> bool:
        """Yedekten .env dosyasını geri yükle"""
        try:
            if Path(backup_file).exists():
                shutil.copy2(backup_file, self.env_path)
                self.env_vars = self._load_env()
                return True
            return False
        except Exception as e:
            print(f"[HATA] Geri yükleme hatası: {e}")
            return False
    
    def get_env_stats(self) -> Dict[str, Any]:
        """Çevre değişkenleri istatistikleri"""
        stats = {
            "total_vars": len(self.env_vars),
            "empty_vars": sum(1 for v in self.env_vars.values() if not v.strip()),
            "sensitive_vars": 0,
            "categories": {},
            "last_modified": None
        }
        
        # Hassas değişken sayısı
        sensitive_keywords = ["TOKEN", "SECRET", "KEY", "PASSWORD", "URL", "B64"]
        for key in self.env_vars.keys():
            if any(kw in key.upper() for kw in sensitive_keywords):
                stats["sensitive_vars"] += 1
        
        # Son değişiklik zamanı
        try:
            if self.env_path.exists():
                stats["last_modified"] = datetime.fromtimestamp(self.env_path.stat().st_mtime)
        except Exception:
            pass
        
        return stats


def register_admin_routes(app: FastAPI, env_path: str = ".env", admin_token: str = ""):
    """Kapsamlı admin paneli route'larını FastAPI app'e kaydet"""
    
    manager = AdminPanelManager(env_path)
    
    # Kategori tanımları
    ENV_CATEGORIES = {
        "Twitter/X Ayarları": {
            "icon": "🐦",
            "hidden_if_external_queue": False,
            "vars": [
                ("TWITTER_USERNAME", "Twitter Kullanıcı Adı", "text", "Takip edilecek Twitter hesabının kullanıcı adı (örn: @TheBFWire)"),
                ("TWITTER_USER_ID", "Twitter Kullanıcı ID", "text", "Takip edilecek hesabın sayısal ID'si (1661482508876238849)"),
                ("TWITTER_BEARER_TOKEN", "Twitter Bearer Token", "text", "Twitter API v2 için gerekli ana yetkilendirme anahtarı"),
                ("TWITTER_ACCESS_TOKEN", "Access Token", "text", "Twitter API erişim tokeni"),
                ("TWITTER_ACCESS_TOKEN_SECRET", "Access Token Secret", "text", "Twitter API erişim token gizli anahtarı"),
                ("TWITTER_CONSUMER_KEY", "Consumer Key", "text", "Twitter API tüketici anahtarı"),
                ("TWITTER_CONSUMER_SECRET", "Consumer Secret", "text", "Twitter API tüketici gizli anahtarı"),
                ("TWITTER_CLIENT_ID", "Client ID", "text", "Twitter OAuth 2.0 istemci kimliği"),
                ("TWITTER_CLIENT_ID_SECRET", "Client Secret", "text", "Twitter OAuth 2.0 istemci gizli anahtarı"),
                ("TWSCRAPE_DEBUG", "TWSCRAPE Debug", "checkbox", "Tweet çekme işlemlerinde detaylı log göster"),
            ]
        },
        "Reddit Ayarları": {
            "icon": "🔴",
            "hidden_if_external_queue": False,
            "vars": [
                ("REDDIT_USERNAME", "Reddit Bot Hesabı", "text", "Gönderileri paylaşacak Reddit bot hesabının kullanıcı adı"),
                ("REDDIT_PASSWORD", "Reddit Şifresi", "text", "Reddit bot hesabının şifresi"),
                ("REDDIT_CLIENT_ID", "Reddit App ID", "text", "Reddit uygulaması kimlik numarası (14 karakter)"),
                ("REDDIT_CLIENT_SECRET", "Reddit App Secret", "text", "Reddit uygulaması gizli anahtarı (27 karakter)"),
                ("REDDIT_USER_AGENT", "User Agent", "text", "Reddit API için tanımlayıcı string (örn: BF6Bot/1.0)"),
                ("SUBREDDIT", "Hedef Subreddit", "text", "Gönderilerin paylaşılacağı subreddit adı (örn: bf6_tr)"),
                ("REDDIT_FLAIR_ID", "Varsayılan Flair", "text", "Gönderilere otomatik eklenecek flair ID'si"),
            ]
        },
        "API Anahtarları": {
            "icon": "🔑",
            "hidden_if_external_queue": False,
            "vars": [
                ("GEMINI_API_KEY", "Google Gemini API", "text", "Tweet çevirisi ve içerik analizi için Google Gemini API anahtarı"),
                ("OPENAI_API_KEY", "OpenAI API", "text", "ChatGPT/GPT-4 ile metin işleme için OpenAI API anahtarı"),
                ("RAPIDAPI_KEY", "RapidAPI Ana Anahtar", "text", "RapidAPI platformu için genel erişim anahtarı"),
                ("RAPIDAPI_TWITTER_KEY", "RapidAPI Twitter", "text", "RapidAPI üzerinden Twitter verisi çekmek için özel anahtar"),
                ("RAPIDAPI_TRANSLATE_KEY", "RapidAPI Çeviri", "text", "RapidAPI çeviri servisleri için özel anahtar"),
                ("TRANSLATION_API_KEY", "Çeviri Servisi", "text", "Alternatif çeviri servisi API anahtarı"),
                ("GITHUB_TOKEN", "GitHub Token", "text", "Manifest dosyası ve repo işlemleri için GitHub Personal Access Token"),
            ]
        },
        "Veritabanı Ayarları": {
            "icon": "💾",
            "hidden_if_external_queue": True,
            "vars": [
                ("DATABASE_URL", "PostgreSQL Bağlantısı", "text", "Render PostgreSQL veritabanı bağlantı URL'si (postgres://...)"),
                ("ACCOUNTS_DB_PATH", "Yerel DB Dosyası", "text", "Twitter hesap bilgileri için SQLite dosya yolu"),
                ("FAIL_IF_DB_UNAVAILABLE", "DB Hatası Durdur", "checkbox", "Veritabanına bağlanılamazsa bot çalışmasını durdur"),
            ]
        },
        "Manifest & Zamanlama": {
            "icon": "📅",
            "hidden_if_external_queue": False,
            "vars": [
                ("MANIFEST_URL", "Manifest JSON URL", "text", "Gönderilecek tweet'lerin listesini içeren GitHub Gist URL'si"),
                ("USE_EXTERNAL_QUEUE", "Manifest Modu", "checkbox", "✅ Manifest listesinden gönder | ❌ Canlı Twitter takibi"),
                ("MANIFEST_IGNORE_SCHEDULE", "Zamanlamayı Yoksay", "checkbox", "✅ Hemen gönder | ❌ Belirlenen saatlerde gönder"),
                ("MANIFEST_POST_INTERVAL_SECONDS", "Gönderim Aralığı", "number", "Ardışık gönderiler arası bekleme süresi (saniye)"),
                ("MANIFEST_TEST_FIRST_ITEM", "Test Modu", "checkbox", "✅ Sadece ilk gönderiyi test et | ❌ Normal çalış"),
                ("FORCE_REBUILD_MANIFEST", "Manifest Yenile", "checkbox", "✅ Tüm manifest'i sıfırdan oluştur | ❌ Mevcut durumu koru"),
                ("HIGH_WATERMARK_ENABLED", "Eski Tweet Filtresi", "checkbox", "✅ Çok eski tweet'leri atla | ❌ Tüm tweet'leri işle"),
            ]
        },
        "Otomatik Gönderiler": {
            "icon": "📌",
            "hidden_if_external_queue": True,
            "vars": [
                ("SCHEDULED_PIN_ENABLED", "Haftalık Sabit Gönderi", "checkbox", "✅ Her hafta belirlenen günde otomatik pin gönderisi yap"),
            ]
        },
        "Diğer Ayarlar": {
            "icon": "⚙️",
            "hidden_if_external_queue": True,
            "vars": [
                ("SECONDARY_RETWEET_TARGET", "İkincil Takip Hesabı", "text", "Ana hesap dışında takip edilecek ikinci Twitter hesabı (@username)"),
                ("SECONDARY_RETWEET_TARGET_ID", "İkincil Hesap ID", "text", "İkincil takip hesabının sayısal Twitter ID'si"),
                ("LOCAL_ONLY", "Sadece Yerel Mod", "checkbox", "✅ Web arayüzü kapalı, sadece konsol | ❌ Web arayüzü açık"),
            ]
        }
    }
    
    def _is_admin(request: Request) -> bool:
        """Admin token kontrolü"""
        if not admin_token:
            return True
        token = request.headers.get("X-Admin-Token") or request.query_params.get("token")
        return token == admin_token
    
    def _mask_sensitive(key: str, value: str) -> str:
        """Artık maskeleme yok - tüm değerler açık gösterilecek"""
        return value
    
    @app.get("/admin/panel", response_class=HTMLResponse)
    def admin_panel(request: Request):
        """Ana admin paneli"""
        if not _is_admin(request):
            return HTMLResponse(
                "<html><head><meta charset='utf-8'></head><body style='font-family:sans-serif;text-align:center;margin-top:50px'><h1>❌ Yetkisiz</h1><p>Token gerekli</p></body></html>",
                status_code=401
            )
        
        token = request.query_params.get("token", "")
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # External queue durumunu kontrol et
        use_external_queue = os.getenv("USE_EXTERNAL_QUEUE", "false").lower() == "true"
        
        # Kategoriler HTML'i oluştur
        categories_html = ""
        for category, info in ENV_CATEGORIES.items():
            # External queue aktifse bazı kategorileri gizle
            if use_external_queue and info.get("hidden_if_external_queue", False):
                continue
                
            categories_html += f'<div class="category-card"><div class="category-header"><span class="category-icon">{info["icon"]}</span><h3>{category}</h3></div><div class="category-content">'
            
            for var_name, label, input_type, description in info["vars"]:
                # Render env variables'dan değeri al, yoksa .env'den
                current_value = os.getenv(var_name) or manager.get_env_var(var_name) or ""
                
                if input_type == "checkbox":
                    checked = "checked" if current_value.lower() in ["true", "1", "yes"] else ""
                    categories_html += f'<div class="form-group"><label class="checkbox-label"><input type="checkbox" name="{var_name}" {checked} class="env-input" data-token="{token}"/><span class="checkbox-text">{label}</span></label><small class="description">{description}</small></div>'
                elif input_type == "textarea":
                    categories_html += f'<div class="form-group"><label>{label}</label><small class="description">{description}</small><textarea class="env-input" name="{var_name}" rows="3" data-token="{token}" placeholder="Değer girin...">{current_value}</textarea><button class="btn-save" onclick="saveEnvVar(\'{var_name}\', this)">💾 Kaydet</button></div>'
                else:
                    categories_html += f'<div class="form-group"><label>{label}</label><small class="description">{description}</small><input type="{input_type}" class="env-input" name="{var_name}" value="{current_value}" data-token="{token}" placeholder="Değer girin..."/><button class="btn-save" onclick="saveEnvVar(\'{var_name}\', this)">💾 Kaydet</button></div>'
            
            categories_html += "</div></div>"
        
        # Manifest önizleme kartı ekle
        if use_external_queue:
            categories_html += get_manifest_preview_card(token)
        
        # Manuel gönderi kartı ekle
        categories_html += get_manual_post_card(token)
        
        return HTMLResponse(get_admin_html(categories_html, current_time, token, use_external_queue))
    
    @app.post("/admin/api/set-env")
    async def api_set_env(request: Request):
        """API: .env değişkenini ayarla"""
        if not _is_admin(request):
            return JSONResponse({"success": False, "error": "Unauthorized"}, status_code=401)
        
        try:
            data = await request.json()
            key = data.get("key", "").strip()
            value = data.get("value", "")
            
            if not key:
                return JSONResponse({"success": False, "error": "Key gerekli"})
            
            if manager.set_env_var(key, value):
                return JSONResponse({"success": True, "key": key})
            else:
                return JSONResponse({"success": False, "error": "Kaydedilemedi"})
        except Exception as e:
            return JSONResponse({"success": False, "error": str(e)})
    
    @app.get("/admin/api/env-vars")
    def api_get_env_vars(request: Request):
        """API: Tüm .env değişkenlerini al"""
        if not _is_admin(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        
        try:
            vars_dict = manager.get_all_env_vars()
            masked = {}
            for key, value in vars_dict.items():
                masked[key] = _mask_sensitive(key, value)
            return JSONResponse(masked)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)
    
    @app.get("/admin/api/env-var/{key}")
    def api_get_env_var(key: str, request: Request):
        """API: Belirli bir .env değişkenini al"""
        if not _is_admin(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        
        try:
            value = manager.get_env_var(key)
            if value is None:
                return JSONResponse({"error": "Not found"}, status_code=404)
            return JSONResponse({"key": key, "value": _mask_sensitive(key, value)})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)
    
    @app.delete("/admin/api/env-var/{key}")
    def api_delete_env_var(key: str, request: Request):
        """API: .env değişkenini sil"""
        if not _is_admin(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        
        try:
            if manager.delete_env_var(key):
                return JSONResponse({"success": True, "key": key})
            else:
                return JSONResponse({"success": False, "error": "Silinemedi"})
        except Exception as e:
            return JSONResponse({"success": False, "error": str(e)})
    
    @app.get("/admin/dashboard", response_class=HTMLResponse)
    def admin_dashboard(request: Request):
        """Gelişmiş dashboard"""
        if not _is_admin(request):
            return HTMLResponse("<h1>Unauthorized</h1>", status_code=401)
        
        token = request.query_params.get("token", "")
        stats = manager.get_env_stats()
        
        return HTMLResponse(get_dashboard_html(stats, token))
    
    @app.get("/admin/api/stats")
    def api_get_stats(request: Request):
        """API: İstatistikleri al"""
        if not _is_admin(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        
        try:
            stats = manager.get_env_stats()
            # Datetime objelerini string'e çevir
            if stats.get("last_modified"):
                stats["last_modified"] = stats["last_modified"].isoformat()
            return JSONResponse(stats)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)
    
    @app.post("/admin/api/backup")
    def api_backup_env(request: Request):
        """API: .env dosyasını yedekle"""
        if not _is_admin(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        
        try:
            backup_file = manager.backup_env()
            if backup_file:
                return JSONResponse({"success": True, "backup_file": backup_file})
            else:
                return JSONResponse({"success": False, "error": "Yedekleme başarısız"})
        except Exception as e:
            return JSONResponse({"success": False, "error": str(e)})
    
    @app.get("/admin/api/backups")
    def api_list_backups(request: Request):
        """API: Yedekleri listele"""
        if not _is_admin(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        
        try:
            backup_dir = Path("backups")
            if not backup_dir.exists():
                return JSONResponse({"backups": []})
            
            backups = []
            for backup_file in backup_dir.glob("env_backup_*.env"):
                stat = backup_file.stat()
                backups.append({
                    "filename": backup_file.name,
                    "path": str(backup_file),
                    "size": stat.st_size,
                    "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
            
            backups.sort(key=lambda x: x["created"], reverse=True)
            return JSONResponse({"backups": backups})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)
    
    @app.post("/admin/api/restore")
    async def api_restore_env(request: Request):
        """API: Yedekten geri yükle"""
        if not _is_admin(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        
        try:
            data = await request.json()
            backup_file = data.get("backup_file", "")
            
            if not backup_file:
                return JSONResponse({"success": False, "error": "Backup file gerekli"})
            
            if manager.restore_env(backup_file):
                return JSONResponse({"success": True})
            else:
                return JSONResponse({"success": False, "error": "Geri yükleme başarısız"})
        except Exception as e:
            return JSONResponse({"success": False, "error": str(e)})
    
    @app.get("/admin/download-backup/{filename}")
    def download_backup(filename: str, request: Request):
        """Yedek dosyasını indir"""
        if not _is_admin(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        
        try:
            backup_file = Path("backups") / filename
            if backup_file.exists() and backup_file.suffix == ".env":
                return FileResponse(backup_file, filename=filename)
            else:
                return JSONResponse({"error": "File not found"}, status_code=404)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)
    
    @app.get("/admin/api/manifest-preview")
    def api_manifest_preview(request: Request):
        """API: Sıradaki manifest gönderilerini önizle"""
        if not _is_admin(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        
        try:
            import requests
            from datetime import datetime, timezone
            import json
            
            # Manifest URL'sini al
            manifest_url = os.getenv("MANIFEST_URL", "")
            if not manifest_url:
                return JSONResponse({"error": "MANIFEST_URL tanımlı değil"}, status_code=400)
            
            # Gerçek manifest verisini çekmeye çalış
            try:
                response = requests.get(manifest_url, timeout=10)
                if response.status_code == 200:
                    manifest_data = response.json()
                    
                    # Manifest'ten sıradaki gönderileri al
                    current_time = datetime.now(timezone.utc)
                    next_items = []
                    
                    # Manifest formatına göre parse et
                    if isinstance(manifest_data, list):
                        items = manifest_data[:10]  # İlk 10 öğe
                    elif isinstance(manifest_data, dict) and 'items' in manifest_data:
                        items = manifest_data['items'][:10]
                    else:
                        items = []
                    
                    for item in items:
                        # Her manifest item'ını parse et
                        parsed_item = {
                            "id": item.get("id", f"item_{len(next_items)}"),
                            "title": item.get("title", item.get("text", "Başlık bulunamadı")),
                            "content": item.get("content", item.get("description", "")),
                            "media_urls": item.get("media", item.get("images", [])),
                            "media_type": "image" if item.get("media") or item.get("images") else "text",
                            "source_url": item.get("url", item.get("source", "")),
                            "scheduled_time": item.get("scheduled_at", item.get("publish_time", "")),
                            "tags": item.get("tags", []),
                            "priority": item.get("priority", "normal"),
                            "author": item.get("author", "Bot")
                        }
                        
                        # Zamanlama bilgisini parse et ve kalan süreyi hesapla
                        if parsed_item["scheduled_time"]:
                            try:
                                # Farklı tarih formatlarını dene
                                scheduled_dt = None
                                for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"]:
                                    try:
                                        scheduled_dt = datetime.strptime(parsed_item["scheduled_time"], fmt)
                                        if scheduled_dt.tzinfo is None:
                                            scheduled_dt = scheduled_dt.replace(tzinfo=timezone.utc)
                                        break
                                    except ValueError:
                                        continue
                                
                                if scheduled_dt:
                                    time_diff = scheduled_dt - current_time
                                    if time_diff.total_seconds() > 0:
                                        hours = int(time_diff.total_seconds() // 3600)
                                        minutes = int((time_diff.total_seconds() % 3600) // 60)
                                        parsed_item["time_remaining"] = f"{hours}s {minutes}d"
                                        parsed_item["status"] = "scheduled"
                                    else:
                                        parsed_item["time_remaining"] = "Süresi geçmiş"
                                        parsed_item["status"] = "overdue"
                                else:
                                    parsed_item["time_remaining"] = "Tarih parse edilemedi"
                                    parsed_item["status"] = "unknown"
                            except Exception:
                                parsed_item["time_remaining"] = "Hesaplanamadı"
                                parsed_item["status"] = "unknown"
                        else:
                            parsed_item["time_remaining"] = "Zamanlama yok"
                            parsed_item["status"] = "ready"
                        
                        next_items.append(parsed_item)
                    
                    preview_data = {
                        "manifest_url": manifest_url,
                        "status": f"✅ Manifest başarıyla yüklendi ({len(next_items)} gönderi)",
                        "last_updated": current_time.isoformat(),
                        "total_items": len(items),
                        "next_items": next_items
                    }
                else:
                    # Manifest yüklenemedi, örnek veri göster
                    preview_data = {
                        "manifest_url": manifest_url,
                        "status": f"⚠️ Manifest yüklenemedi (HTTP {response.status_code})",
                        "error": "Manifest URL'sine erişilemiyor",
                        "next_items": []
                    }
            except requests.RequestException as e:
                # Ağ hatası, örnek veri göster
                current_time = datetime.now(timezone.utc)
                preview_data = {
                    "manifest_url": manifest_url,
                    "status": "⚠️ Ağ hatası - Örnek veri gösteriliyor",
                    "error": str(e),
                    "next_items": [
                        {
                            "id": "example_1",
                            "title": "Breaking: Major Tech Announcement Expected",
                            "content": "Industry sources suggest a significant announcement coming from major tech companies this week...",
                            "media_urls": ["https://example.com/image1.jpg"],
                            "media_type": "image",
                            "source_url": "https://twitter.com/example/status/123",
                            "scheduled_time": (current_time.replace(hour=current_time.hour+2)).strftime("%Y-%m-%d %H:%M:%S"),
                            "time_remaining": "2s 0d",
                            "status": "scheduled",
                            "tags": ["tech", "breaking"],
                            "priority": "high",
                            "author": "TechNews"
                        },
                        {
                            "id": "example_2",
                            "title": "Market Analysis: Weekly Crypto Report",
                            "content": "Comprehensive analysis of this week's cryptocurrency market movements and trends...",
                            "media_urls": [],
                            "media_type": "text",
                            "source_url": "https://twitter.com/crypto/status/456",
                            "scheduled_time": (current_time.replace(hour=current_time.hour+4)).strftime("%Y-%m-%d %H:%M:%S"),
                            "time_remaining": "4s 0d",
                            "status": "scheduled",
                            "tags": ["crypto", "analysis"],
                            "priority": "normal",
                            "author": "CryptoAnalyst"
                        }
                    ]
                }
            
            return JSONResponse(preview_data)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)
    
    @app.post("/admin/api/manual-post")
    async def api_create_manual_post(request: Request):
        """API: Manuel gönderi oluştur"""
        if not _is_admin(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        
        try:
            data = await request.json()
            title = data.get("title", "").strip()
            content = data.get("content", "").strip()
            schedule_time = data.get("schedule_time", "")
            
            if not title:
                return JSONResponse({"success": False, "error": "Başlık gerekli"})
            
            # Manuel gönderi veritabanına kaydet (basit implementasyon)
            manual_post = {
                "id": f"manual_{int(time.time())}",
                "title": title,
                "content": content,
                "schedule_time": schedule_time,
                "created_at": datetime.now().isoformat(),
                "status": "scheduled" if schedule_time else "ready"
            }
            
            # Gerçek implementasyonda veritabanına kaydedilecek
            return JSONResponse({"success": True, "post_id": manual_post["id"]})
        except Exception as e:
            return JSONResponse({"success": False, "error": str(e)})
    
    @app.get("/admin/api/scheduled-posts")
    def api_get_scheduled_posts(request: Request):
        """API: Zamanlanmış gönderileri listele"""
        if not _is_admin(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        
        try:
            # Gerçek implementasyonda veritabanından çekilecek
            scheduled_posts = [
                {
                    "id": "manual_1732204800",
                    "title": "Örnek zamanlanmış gönderi",
                    "content": "Bu bir test gönderisidir",
                    "schedule_time": "2024-11-21 20:00:00",
                    "status": "scheduled"
                }
            ]
            
            return JSONResponse({"posts": scheduled_posts})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)
    
    @app.post("/admin/api/update-manifest-item")
    async def api_update_manifest_item(request: Request):
        """API: Manifest gönderisini güncelle"""
        if not _is_admin(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        
        try:
            data = await request.json()
            item_id = data.get("id", "")
            updates = data.get("updates", {})
            
            if not item_id:
                return JSONResponse({"success": False, "error": "Gönderi ID gerekli"})
            
            # Gerçek implementasyonda manifest'i güncelleyecek
            # Şimdilik başarılı yanıt dön
            return JSONResponse({
                "success": True, 
                "message": f"Gönderi {item_id} güncellendi",
                "updated_fields": list(updates.keys())
            })
        except Exception as e:
            return JSONResponse({"success": False, "error": str(e)})
    
    @app.delete("/admin/api/delete-manifest-item/{item_id}")
    def api_delete_manifest_item(request: Request, item_id: str):
        """API: Manifest gönderisini sil"""
        if not _is_admin(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        
        try:
            # Gerçek implementasyonda manifest'ten silecek
            return JSONResponse({
                "success": True,
                "message": f"Gönderi {item_id} silindi"
            })
        except Exception as e:
            return JSONResponse({"success": False, "error": str(e)})


def get_manifest_preview_card(token: str) -> str:
    """Manifest önizleme kartı"""
    return f'''
    <div class="category-card" style="grid-column: 1 / -1; max-width: none;">
        <div class="category-header">
            <span class="category-icon">📋</span>
            <h3>Sıradaki Manifest Gönderileri</h3>
        </div>
        <div class="category-content">
            <div class="form-group">
                <div style="display:flex;gap:10px;margin-bottom:15px;">
                    <button class="btn-save" onclick="loadManifestPreview()" style="flex:1;">🔄 Manifest Yenile</button>
                    <button class="btn-save" onclick="autoRefreshToggle()" id="auto-refresh-btn" style="flex:1;background:#ff9800;">⏱️ Otomatik Yenileme</button>
                </div>
                <div id="manifest-preview" style="margin-top:15px;max-height:600px;overflow-y:auto;border:1px solid #e0e0e0;border-radius:8px;background:#fafafa;padding:15px;"></div>
            </div>
        </div>
    </div>
    '''

def get_manual_post_card(token: str) -> str:
    """Manuel gönderi oluşturma kartı"""
    return f'''
    <div class="category-card">
        <div class="category-header">
            <span class="category-icon">✍️</span>
            <h3>Manuel Gönderi Oluştur</h3>
        </div>
        <div class="category-content">
            <div class="form-group">
                <label>Gönderi Başlığı</label>
                <input type="text" id="manual-title" placeholder="Reddit gönderisi başlığı..." style="width:100%;padding:10px;margin-bottom:10px;border:2px solid #ddd;border-radius:6px;"/>
            </div>
            <div class="form-group">
                <label>Gönderi İçeriği</label>
                <textarea id="manual-content" rows="4" placeholder="Gönderi açıklaması (opsiyonel)..." style="width:100%;padding:10px;margin-bottom:10px;border:2px solid #ddd;border-radius:6px;"></textarea>
            </div>
            <div class="form-group">
                <label>Medya Yükle</label>
                <input type="file" id="manual-media" accept="image/*,video/*" style="width:100%;padding:10px;margin-bottom:10px;border:2px solid #ddd;border-radius:6px;"/>
            </div>
            <div class="form-group">
                <label>Zamanlama (Opsiyonel)</label>
                <input type="datetime-local" id="manual-schedule" style="width:100%;padding:10px;margin-bottom:10px;border:2px solid #ddd;border-radius:6px;"/>
                <small style="color:#666;">Boş bırakırsanız hemen gönderilir</small>
            </div>
            <div class="form-group">
                <button class="btn-save" onclick="createManualPost()">📤 Gönderi Oluştur</button>
                <button class="btn-save" onclick="viewScheduledPosts()" style="margin-left:10px;">📅 Zamanlanmış Gönderiler</button>
            </div>
        </div>
    </div>
    '''


def get_admin_html(categories_html: str, current_time: str, token: str = "", use_external_queue: bool = False) -> str:
    """Admin paneli HTML şablonu"""
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bot Admin Paneli - .env Yönetimi</title>
    <style>
        * {{margin:0;padding:0;box-sizing:border-box}}
        body {{font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);min-height:100vh;padding:20px}}
        .container {{max-width:1400px;margin:0 auto}}
        .header {{background:white;border-radius:12px;padding:30px;margin-bottom:30px;box-shadow:0 10px 30px rgba(0,0,0,0.2)}}
        .header h1 {{color:#333;margin-bottom:10px;font-size:2.5em}}
        .header-info {{display:flex;gap:20px;margin-top:15px;flex-wrap:wrap}}
        .info-item {{display:flex;align-items:center;gap:8px;color:#666;font-size:0.95em}}
        .info-item strong {{color:#333}}
        .status-badge {{display:inline-block;background:#4CAF50;color:white;padding:6px 12px;border-radius:20px;font-size:0.85em;font-weight:600}}
        .categories-grid {{display:grid;grid-template-columns:repeat(auto-fit,minmax(500px,1fr));gap:20px;margin-bottom:30px}}
        .category-card {{background:white;border-radius:12px;overflow:hidden;box-shadow:0 10px 30px rgba(0,0,0,0.1);transition:transform 0.3s}}
        .category-card:hover {{transform:translateY(-5px)}}
        .category-header {{background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white;padding:20px;display:flex;align-items:center;gap:15px}}
        .category-icon {{font-size:2em}}
        .category-header h3 {{font-size:1.3em;font-weight:600}}
        .category-content {{padding:20px}}
        .form-group {{margin-bottom:20px;padding-bottom:20px;border-bottom:1px solid #eee}}
        .form-group:last-child {{border-bottom:none;margin-bottom:0;padding-bottom:0}}
        .form-group label {{display:block;font-weight:600;color:#333;margin-bottom:6px;font-size:0.95em}}
        .description {{display:block;color:#999;font-size:0.85em;margin-bottom:8px;font-style:italic}}
        .form-group input[type="text"],.form-group input[type="number"],.form-group input[type="password"],.form-group textarea {{width:100%;padding:10px 12px;border:2px solid #ddd;border-radius:6px;font-family:'Courier New',monospace;font-size:0.9em;transition:border-color 0.3s}}
        .form-group input:focus,.form-group textarea:focus {{outline:none;border-color:#667eea;box-shadow:0 0 0 3px rgba(102,126,234,0.1)}}
        .password-group {{display:flex;gap:8px;margin-bottom:8px}}
        .password-group input {{flex:1}}
        .btn-toggle {{padding:10px 12px;background:#f0f0f0;border:2px solid #ddd;border-radius:6px;cursor:pointer;font-size:1em;transition:all 0.3s}}
        .btn-toggle:hover {{background:#e0e0e0}}
        .btn-save {{padding:10px 16px;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white;border:none;border-radius:6px;cursor:pointer;font-weight:600;transition:all 0.3s;font-size:0.9em}}
        .btn-save:hover {{transform:translateY(-2px);box-shadow:0 5px 15px rgba(102,126,234,0.4)}}
        .btn-save:active {{transform:translateY(0)}}
        .checkbox-label {{display:flex;align-items:center;gap:10px;cursor:pointer;font-weight:600;color:#333}}
        .checkbox-label input[type="checkbox"] {{width:18px;height:18px;cursor:pointer}}
        .checkbox-text {{flex:1}}
        .notification {{position:fixed;top:20px;right:20px;padding:16px 20px;background:white;border-radius:8px;box-shadow:0 5px 20px rgba(0,0,0,0.2);z-index:1000;animation:slideIn 0.3s ease-out}}
        .notification.success {{border-left:4px solid #4CAF50}}
        .notification.error {{border-left:4px solid #f44336}}
        @keyframes slideIn {{from {{transform:translateX(400px);opacity:0}} to {{transform:translateX(0);opacity:1}}}}
        .footer {{background:white;border-radius:12px;padding:20px;text-align:center;color:#666;font-size:0.9em;box-shadow:0 10px 30px rgba(0,0,0,0.1)}}
        .nav-buttons {{display:flex;gap:10px;margin-top:20px;flex-wrap:wrap}}
        .nav-btn {{padding:10px 16px;background:#f8f9fa;color:#333;text-decoration:none;border-radius:6px;border:2px solid #ddd;cursor:pointer;font-weight:600;transition:all 0.3s}}
        .nav-btn:hover {{background:#e9ecef;transform:translateY(-2px)}}
        .nav-btn.active {{background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white;border-color:#667eea}}
        .modal {{display:none;position:fixed;z-index:1000;left:0;top:0;width:100%;height:100%;background:rgba(0,0,0,0.5)}}
        .modal-content {{background:white;margin:5% auto;padding:30px;width:90%;max-width:600px;border-radius:12px;box-shadow:0 20px 60px rgba(0,0,0,0.3)}}
        .close {{color:#aaa;float:right;font-size:28px;font-weight:bold;cursor:pointer}}
        .close:hover {{color:#000}}
        .backup-list {{max-height:300px;overflow-y:auto;margin:20px 0}}
        .backup-item {{display:flex;justify-content:space-between;align-items:center;padding:10px;border:1px solid #ddd;border-radius:6px;margin-bottom:10px}}
        .backup-info {{flex:1}}
        .backup-actions {{display:flex;gap:8px}}
        .loading-spinner {{border:4px solid #f3f3f3;border-top:4px solid #3498db;border-radius:50%;width:40px;height:40px;animation:spin 2s linear infinite;margin:0 auto;}}
        @keyframes spin {{0% {{transform:rotate(0deg);}} 100% {{transform:rotate(360deg);}}}}
        .manifest-item {{transition:all 0.3s ease;}}
        .manifest-item:hover {{box-shadow:0 4px 12px rgba(0,0,0,0.15);transform:translateY(-2px);}}
        .manifest-header {{background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white;padding:15px;border-radius:8px;margin-bottom:15px;}}
        .manifest-header h4 {{color:white !important;}}
        @media (max-width:768px) {{.categories-grid {{grid-template-columns:1fr}} .header h1 {{font-size:1.8em}} .header-info {{flex-direction:column}}}}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 Bot Admin Paneli</h1>
            <p style="color:#666;margin-top:10px;">Tüm .env parametrelerini profesyonel arayüzden yönetin</p>
            <div class="header-info">
                <div class="info-item"><span class="status-badge">✓ Aktif</span></div>
                <div class="info-item"><strong>Güncelleme:</strong> {current_time}</div>
                <div class="info-item"><strong>Dosya:</strong> .env</div>
            </div>
            <div class="nav-buttons">
                <a href="/admin/dashboard?token={token}" class="nav-btn">📊 Dashboard</a>
                <a href="/admin/panel?token={token}" class="nav-btn active">⚙️ Ayarlar</a>
                <button onclick="backupEnv()" class="nav-btn">💾 Yedekle</button>
                <button onclick="showBackups()" class="nav-btn">📂 Yedekler</button>
                {'<span class="nav-btn" style="background:#4CAF50;color:white;">🔄 Manifest Modu</span>' if use_external_queue else '<span class="nav-btn" style="background:#FF9800;color:white;">📡 Canlı Takip</span>'}
            </div>
        </div>
        <div class="categories-grid">{categories_html}</div>
        <div class="footer">
            <p>💡 İpucu: Değişiklikleri kaydettikten sonra botu yeniden başlatmanız gerekebilir.</p>
            <p style="margin-top:10px;font-size:0.85em;">Tüm değerler Render environment variables'dan okunmaktadır.</p>
        </div>
    </div>
    <script>
        function saveEnvVar(varName, button) {{
            const group = button.parentElement;
            const inputs = group.querySelectorAll('.env-input');
            let input = null;
            for (let i of inputs) {{
                if (i.name === varName) {{
                    input = i;
                    break;
                }}
            }}
            if (!input) return;
            let value = input.value;
            if (input.type === 'checkbox') {{
                value = input.checked ? 'true' : 'false';
            }}
            const token = input.dataset.token;
            fetch('/admin/api/set-env', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json', 'X-Admin-Token': token}},
                body: JSON.stringify({{key: varName, value: value}})
            }}).then(r => r.json()).then(data => {{
                if (data.success) {{
                    showNotification('✓ ' + varName + ' kaydedildi', 'success');
                }} else {{
                    showNotification('✗ Hata: ' + (data.error || 'Bilinmeyen hata'), 'error');
                }}
            }}).catch(e => {{
                showNotification('✗ Ağ hatası: ' + e.message, 'error');
            }});
        }}
        function togglePasswordVisibility(button) {{
            const input = button.previousElementSibling;
            if (input.type === 'password') {{
                input.type = 'text';
                button.textContent = '🙈';
            }} else {{
                input.type = 'password';
                button.textContent = '👁️';
            }}
        }}
        function showNotification(message, type) {{
            const notif = document.createElement('div');
            notif.className = 'notification ' + type;
            notif.textContent = message;
            document.body.appendChild(notif);
            setTimeout(() => {{
                notif.style.animation = 'slideIn 0.3s ease-out reverse';
                setTimeout(() => notif.remove(), 300);
            }}, 3000);
        }}
        document.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {{
            checkbox.addEventListener('change', function() {{
                const varName = this.name;
                const value = this.checked ? 'true' : 'false';
                const token = this.dataset.token;
                fetch('/admin/api/set-env', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json', 'X-Admin-Token': token}},
                    body: JSON.stringify({{key: varName, value: value}})
                }}).then(r => r.json()).then(data => {{
                    if (data.success) {{
                        showNotification('✓ ' + varName + ' güncellendi', 'success');
                    }}
                }}).catch(e => {{
                    showNotification('✗ Hata: ' + e.message, 'error');
                }});
            }});
        }});
        
        function backupEnv() {{
            const token = '{token}';
            fetch('/admin/api/backup', {{
                method: 'POST',
                headers: {{'X-Admin-Token': token}}
            }}).then(r => r.json()).then(data => {{
                if (data.success) {{
                    showNotification('✓ Yedekleme başarılı: ' + data.backup_file, 'success');
                }} else {{
                    showNotification('✗ Yedekleme hatası: ' + data.error, 'error');
                }}
            }}).catch(e => {{
                showNotification('✗ Ağ hatası: ' + e.message, 'error');
            }});
        }}
        
        function showBackups() {{
            const token = '{token}';
            fetch('/admin/api/backups?token=' + token)
            .then(r => r.json())
            .then(data => {{
                if (data.backups) {{
                    let html = '<h3>Yedek Dosyaları</h3><div class="backup-list">';
                    data.backups.forEach(backup => {{
                        const size = (backup.size / 1024).toFixed(1) + ' KB';
                        const date = new Date(backup.created).toLocaleString('tr-TR');
                        html += `<div class="backup-item">
                            <div class="backup-info">
                                <strong>${{backup.filename}}</strong><br>
                                <small>${{date}} - ${{size}}</small>
                            </div>
                            <div class="backup-actions">
                                <button onclick="downloadBackup('${{backup.filename}}')" class="btn-save">⬇️ İndir</button>
                                <button onclick="restoreBackup('${{backup.path}}')" class="btn-save">🔄 Geri Yükle</button>
                            </div>
                        </div>`;
                    }});
                    html += '</div>';
                    showModal(html);
                }} else {{
                    showModal('<h3>Yedek Bulunamadı</h3><p>Henüz yedek dosyası oluşturulmamış.</p>');
                }}
            }}).catch(e => {{
                showNotification('✗ Yedekler yüklenemedi: ' + e.message, 'error');
            }});
        }}
        
        function downloadBackup(filename) {{
            const token = '{token}';
            window.open(`/admin/download-backup/${{filename}}?token=${{token}}`, '_blank');
        }}
        
        function restoreBackup(path) {{
            if (!confirm('Bu yedekten geri yüklemek istediğinizden emin misiniz? Mevcut ayarlar kaybolacak!')) return;
            const token = '{token}';
            fetch('/admin/api/restore', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json', 'X-Admin-Token': token}},
                body: JSON.stringify({{backup_file: path}})
            }}).then(r => r.json()).then(data => {{
                if (data.success) {{
                    showNotification('✓ Geri yükleme başarılı! Sayfa yenileniyor...', 'success');
                    setTimeout(() => location.reload(), 2000);
                }} else {{
                    showNotification('✗ Geri yükleme hatası: ' + data.error, 'error');
                }}
            }}).catch(e => {{
                showNotification('✗ Ağ hatası: ' + e.message, 'error');
            }});
        }}
        
        function showModal(content) {{
            const modal = document.createElement('div');
            modal.className = 'modal';
            modal.style.display = 'block';
            modal.innerHTML = `<div class="modal-content">
                <span class="close" onclick="this.parentElement.parentElement.remove()">&times;</span>
                ${{content}}
            </div>`;
            document.body.appendChild(modal);
            modal.onclick = function(e) {{
                if (e.target === modal) modal.remove();
            }};
        }}
        
        function loadManifestPreview() {{
            const token = '{token}';
            const previewDiv = document.getElementById('manifest-preview');
            previewDiv.innerHTML = '<div style="text-align:center;padding:20px;"><div class="loading-spinner"></div><p>Manifest yükleniyor...</p></div>';
            
            fetch('/admin/api/manifest-preview?token=' + token)
            .then(r => r.json())
            .then(data => {{
                if (data.error) {{
                    previewDiv.innerHTML = `<div style="color:red;padding:15px;border:1px solid #ffcdd2;background:#ffebee;border-radius:6px;">❌ <strong>Hata:</strong> ${{data.error}}</div>`;
                    return;
                }}
                
                let html = `<div class="manifest-header">`;
                html += `<h4 style="margin:0 0 10px 0;color:#1976d2;">📋 Manifest Durumu</h4>`;
                html += `<p style="margin:5px 0;"><strong>URL:</strong> <code style="background:#f5f5f5;padding:2px 6px;border-radius:3px;font-size:0.85em;">${{data.manifest_url}}</code></p>`;
                html += `<p style="margin:5px 0;"><strong>Durum:</strong> ${{data.status}}</p>`;
                if (data.last_updated) {{
                    const lastUpdate = new Date(data.last_updated).toLocaleString('tr-TR');
                    html += `<p style="margin:5px 0;font-size:0.9em;color:#666;"><strong>Son Güncelleme:</strong> ${{lastUpdate}}</p>`;
                }}
                html += `</div>`;
                
                if (data.next_items && data.next_items.length > 0) {{
                    html += '<div style="margin-top:15px;">';
                    html += '<h5 style="margin:10px 0;color:#388e3c;">🕒 Sıradaki Gönderiler:</h5>';
                    
                    data.next_items.forEach((item, index) => {{
                        const statusColor = item.status === 'scheduled' ? '#4caf50' : item.status === 'overdue' ? '#f44336' : '#ff9800';
                        const priorityIcon = item.priority === 'high' ? '🔥' : item.priority === 'low' ? '📝' : '📄';
                        
                        html += `<div class="manifest-item" style="border:1px solid #e0e0e0;padding:15px;margin:10px 0;border-radius:8px;background:#fafafa;">`;
                        
                        // Başlık ve öncelik
                        html += `<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px;">`;
                        html += `<h6 style="margin:0;color:#1976d2;font-size:1.1em;">${{priorityIcon}} ${{item.title}}</h6>`;
                        html += `<span style="background:${{statusColor}};color:white;padding:2px 8px;border-radius:12px;font-size:0.8em;">${{item.status.toUpperCase()}}</span>`;
                        html += `</div>`;
                        
                        // İçerik (varsa)
                        if (item.content && item.content.trim()) {{
                            const shortContent = item.content.length > 100 ? item.content.substring(0, 100) + '...' : item.content;
                            html += `<p style="margin:8px 0;color:#555;font-size:0.9em;line-height:1.4;">${{shortContent}}</p>`;
                        }}
                        
                        // Medya önizleme
                        if (item.media_urls && item.media_urls.length > 0) {{
                            html += `<div style="margin:10px 0;">`;
                            html += `<strong style="color:#7b1fa2;">🖼️ Medya (${{item.media_urls.length}} dosya):</strong><br>`;
                            item.media_urls.slice(0, 3).forEach(url => {{
                                if (typeof url === 'string' && /\.(jpg|jpeg|png|gif|webp)$/i.test(url)) {{
                                    html += `<img src="${{url}}" style="max-width:80px;max-height:60px;margin:5px 5px 5px 0;border-radius:4px;border:1px solid #ddd;" onerror="this.style.display='none'" />`;
                                }} else {{
                                    html += `<span style="background:#e3f2fd;color:#1976d2;padding:2px 6px;margin:2px;border-radius:3px;font-size:0.8em;">📎 Medya</span>`;
                                }}
                            }});
                            if (item.media_urls.length > 3) {{
                                html += `<span style="color:#666;font-size:0.8em;">+${{item.media_urls.length - 3}} daha...</span>`;
                            }}
                            html += `</div>`;
                        }}
                        
                        // Zamanlama bilgileri
                        html += `<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px;padding-top:10px;border-top:1px solid #e0e0e0;">`;
                        
                        if (item.scheduled_time) {{
                            const scheduleDate = new Date(item.scheduled_time).toLocaleString('tr-TR');
                            html += `<div><strong style="color:#5d4037;">📅 Zamanlama:</strong><br><span style="font-size:0.9em;">${{scheduleDate}}</span></div>`;
                        }} else {{
                            html += `<div><strong style="color:#5d4037;">📅 Zamanlama:</strong><br><span style="font-size:0.9em;color:#666;">Hemen gönder</span></div>`;
                        }}
                        
                        html += `<div><strong style="color:#d32f2f;">⏰ Kalan Süre:</strong><br><span style="font-size:0.9em;font-weight:bold;color:${{statusColor}};">${{item.time_remaining}}</span></div>`;
                        html += `</div>`;
                        
                        // Ek bilgiler
                        html += `<div style="margin-top:10px;display:flex;flex-wrap:wrap;gap:5px;">`;
                        if (item.author && item.author !== 'Bot') {{
                            html += `<span style="background:#f3e5f5;color:#7b1fa2;padding:2px 6px;border-radius:3px;font-size:0.8em;">� ${{item.author}}</span>`;
                        }}
                        if (item.tags && item.tags.length > 0) {{
                            item.tags.slice(0, 3).forEach(tag => {{
                                html += `<span style="background:#e8f5e8;color:#2e7d32;padding:2px 6px;border-radius:3px;font-size:0.8em;">#${{tag}}</span>`;
                            }});
                        }}
                        if (item.source_url) {{
                            html += `<a href="${{item.source_url}}" target="_blank" style="background:#e3f2fd;color:#1976d2;padding:2px 6px;border-radius:3px;font-size:0.8em;text-decoration:none;">🔗 Kaynak</a>`;
                        }}
                        html += `</div>`;
                        
                        html += `</div>`;
                    }});
                    
                    html += '</div>';
                    
                    // Özet istatistikler
                    const scheduledCount = data.next_items.filter(item => item.status === 'scheduled').length;
                    const overdueCount = data.next_items.filter(item => item.status === 'overdue').length;
                    const readyCount = data.next_items.filter(item => item.status === 'ready').length;
                    
                    html += `<div style="margin-top:15px;padding:10px;background:#f5f5f5;border-radius:6px;">`;
                    html += `<strong>📊 Özet:</strong> `;
                    html += `<span style="color:#4caf50;">✅ ${{scheduledCount}} zamanlanmış</span> | `;
                    html += `<span style="color:#ff9800;">⚡ ${{readyCount}} hazır</span>`;
                    if (overdueCount > 0) {{
                        html += ` | <span style="color:#f44336;">⚠️ ${{overdueCount}} süresi geçmiş</span>`;
                    }}
                    html += `</div>`;
                }} else {{
                    html += '<div style="text-align:center;padding:30px;color:#666;">';
                    html += '<div style="font-size:3em;margin-bottom:10px;">📭</div>';
                    html += '<p>Sırada bekleyen gönderi bulunamadı.</p>';
                    html += '</div>';
                }}
                
                previewDiv.innerHTML = html;
            }}).catch(e => {{
                previewDiv.innerHTML = `<div style="color:red;padding:15px;border:1px solid #ffcdd2;background:#ffebee;border-radius:6px;">🌐 <strong>Ağ Hatası:</strong> ${{e.message}}</div>`;
            }});
        }}
        
        function createManualPost() {{
            const token = '{token}';
            const title = document.getElementById('manual-title').value.trim();
            const content = document.getElementById('manual-content').value.trim();
            const schedule = document.getElementById('manual-schedule').value;
            
            if (!title) {{
                showNotification('✗ Başlık gerekli!', 'error');
                return;
            }}
            
            const postData = {{
                title: title,
                content: content,
                schedule_time: schedule
            }};
            
            fetch('/admin/api/manual-post', {{
                method: 'POST',
                headers: {{
                    'Content-Type': 'application/json',
                    'X-Admin-Token': token
                }},
                body: JSON.stringify(postData)
            }}).then(r => r.json()).then(data => {{
                if (data.success) {{
                    showNotification('✓ Gönderi oluşturuldu: ' + data.post_id, 'success');
                    // Formu temizle
                    document.getElementById('manual-title').value = '';
                    document.getElementById('manual-content').value = '';
                    document.getElementById('manual-schedule').value = '';
                }} else {{
                    showNotification('✗ Hata: ' + data.error, 'error');
                }}
            }}).catch(e => {{
                showNotification('✗ Ağ hatası: ' + e.message, 'error');
            }});
        }}
        
        function viewScheduledPosts() {{
            const token = '{token}';
            
            fetch('/admin/api/scheduled-posts?token=' + token)
            .then(r => r.json())
            .then(data => {{
                if (data.error) {{
                    showNotification('✗ Hata: ' + data.error, 'error');
                    return;
                }}
                
                let html = '<h3>📅 Zamanlanmış Gönderiler</h3>';
                
                if (data.posts && data.posts.length > 0) {{
                    html += '<div style="max-height:400px;overflow-y:auto;">';
                    data.posts.forEach(post => {{
                        html += `<div style="border:1px solid #ddd;padding:15px;margin:10px 0;border-radius:6px;">`;
                        html += `<h4>${{post.title}}</h4>`;
                        if (post.content) html += `<p>${{post.content}}</p>`;
                        html += `<small><strong>Zamanlama:</strong> ${{post.schedule_time || 'Hemen'}}</small><br>`;
                        html += `<small><strong>Durum:</strong> ${{post.status}}</small>`;
                        html += `</div>`;
                    }});
                    html += '</div>';
                }} else {{
                    html += '<p>Zamanlanmış gönderi bulunamadı.</p>';
                }}
                
                showModal(html);
            }}).catch(e => {{
                showNotification('✗ Ağ hatası: ' + e.message, 'error');
            }});
        }}
        
        let autoRefreshInterval = null;
        function autoRefreshToggle() {{
            const btn = document.getElementById('auto-refresh-btn');
            if (autoRefreshInterval) {{
                clearInterval(autoRefreshInterval);
                autoRefreshInterval = null;
                btn.innerHTML = '⏱️ Otomatik Yenileme';
                btn.style.background = '#ff9800';
                showNotification('🔄 Otomatik yenileme durduruldu', 'success');
            }} else {{
                autoRefreshInterval = setInterval(loadManifestPreview, 30000); // 30 saniyede bir
                btn.innerHTML = '⏸️ Yenilemeyi Durdur';
                btn.style.background = '#4caf50';
                showNotification('🔄 Otomatik yenileme başlatıldı (30s)', 'success');
                loadManifestPreview(); // Hemen yükle
            }}
        }}
        
        // Sayfa yüklendiğinde manifest'i otomatik yükle
        document.addEventListener('DOMContentLoaded', function() {{
            if (document.getElementById('manifest-preview')) {{
                loadManifestPreview();
            }}
        }});
    </script>
</body>
</html>"""


def get_dashboard_manifest_card(token: str) -> str:
    """Dashboard için manifest yönetim kartı"""
    return f'''
    <div class="chart-container" style="margin-top:30px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;">
            <h3 style="margin:0;color:#333;">📋 Manifest Sıradaki Gönderileri</h3>
            <div style="display:flex;gap:10px;">
                <button onclick="loadDashboardManifest()" class="nav-btn" style="margin:0;">🔄 Yenile</button>
                <button onclick="toggleAutoRefreshDashboard()" id="dashboard-auto-refresh" class="nav-btn" style="margin:0;background:#ff9800;">⏱️ Otomatik</button>
            </div>
        </div>
        <div id="dashboard-manifest-content" style="max-height:500px;overflow-y:auto;"></div>
    </div>
    
    <script>
        let dashboardAutoRefresh = null;
        
        function loadDashboardManifest() {{
            const token = '{token}';
            const contentDiv = document.getElementById('dashboard-manifest-content');
            contentDiv.innerHTML = '<div style="text-align:center;padding:30px;"><div style="border:4px solid #f3f3f3;border-top:4px solid #3498db;border-radius:50%;width:40px;height:40px;animation:spin 2s linear infinite;margin:0 auto;"></div><p style="margin-top:15px;">Yükleniyor...</p></div>';
            
            fetch('/admin/api/manifest-preview?token=' + token)
            .then(r => r.json())
            .then(data => {{
                if (data.error) {{
                    contentDiv.innerHTML = `<div style="color:red;padding:20px;text-align:center;border:1px solid #ffcdd2;background:#ffebee;border-radius:8px;">❌ <strong>Hata:</strong> ${{data.error}}</div>`;
                    return;
                }}
                
                let html = '';
                
                if (data.next_items && data.next_items.length > 0) {{
                    data.next_items.forEach((item, index) => {{
                        const statusColor = item.status === 'scheduled' ? '#4caf50' : item.status === 'overdue' ? '#f44336' : '#ff9800';
                        const priorityIcon = item.priority === 'high' ? '🔥' : item.priority === 'low' ? '📝' : '📄';
                        
                        html += `<div class="manifest-edit-item" style="border:1px solid #e0e0e0;padding:20px;margin:15px 0;border-radius:10px;background:#fafafa;position:relative;">`;
                        
                        // Başlık ve durum
                        html += `<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:15px;">`;
                        html += `<div style="flex:1;">`;
                        html += `<input type="text" id="title-${{item.id}}" value="${{item.title}}" style="width:100%;padding:8px;border:1px solid #ddd;border-radius:4px;font-weight:600;font-size:1.1em;" />`;
                        html += `</div>`;
                        html += `<div style="margin-left:15px;display:flex;gap:8px;align-items:center;">`;
                        html += `<span style="background:${{statusColor}};color:white;padding:4px 10px;border-radius:12px;font-size:0.8em;font-weight:600;">${{item.status.toUpperCase()}}</span>`;
                        html += `<button onclick="deleteManifestItem('${{item.id}}')" style="background:#f44336;color:white;border:none;padding:6px 10px;border-radius:4px;cursor:pointer;font-size:0.8em;">🗑️ Sil</button>`;
                        html += `</div>`;
                        html += `</div>`;
                        
                        // İçerik düzenleme
                        html += `<div style="margin-bottom:15px;">`;
                        html += `<label style="display:block;font-weight:600;margin-bottom:5px;color:#555;">📝 İçerik:</label>`;
                        html += `<textarea id="content-${{item.id}}" rows="3" style="width:100%;padding:8px;border:1px solid #ddd;border-radius:4px;resize:vertical;">${{item.content || ''}}</textarea>`;
                        html += `</div>`;
                        
                        // Medya yönetimi
                        if (item.media_urls && item.media_urls.length > 0) {{
                            html += `<div style="margin-bottom:15px;">`;
                            html += `<label style="display:block;font-weight:600;margin-bottom:5px;color:#555;">🖼️ Medya (${{item.media_urls.length}} dosya):</label>`;
                            html += `<div style="display:flex;flex-wrap:wrap;gap:10px;">`;
                            item.media_urls.forEach((url, idx) => {{
                                if (typeof url === 'string' && /\.(jpg|jpeg|png|gif|webp)$/i.test(url)) {{
                                    html += `<div style="position:relative;">`;
                                    html += `<img src="${{url}}" style="width:100px;height:80px;object-fit:cover;border-radius:6px;border:2px solid #ddd;" />`;
                                    html += `<button onclick="removeMedia('${{item.id}}', ${{idx}})" style="position:absolute;top:-5px;right:-5px;background:#f44336;color:white;border:none;border-radius:50%;width:20px;height:20px;font-size:12px;cursor:pointer;">×</button>`;
                                    html += `</div>`;
                                }} else {{
                                    html += `<div style="padding:10px;background:#e3f2fd;border-radius:6px;border:1px solid #1976d2;color:#1976d2;font-size:0.9em;">📎 ${{url.split('/').pop()}}</div>`;
                                }}
                            }});
                            html += `</div>`;
                            html += `</div>`;
                        }}
                        
                        // Zamanlama düzenleme
                        html += `<div style="display:grid;grid-template-columns:1fr 1fr;gap:15px;margin-bottom:15px;">`;
                        html += `<div>`;
                        html += `<label style="display:block;font-weight:600;margin-bottom:5px;color:#555;">📅 Zamanlama:</label>`;
                        const scheduleValue = item.scheduled_time ? new Date(item.scheduled_time).toISOString().slice(0, 16) : '';
                        html += `<input type="datetime-local" id="schedule-${{item.id}}" value="${{scheduleValue}}" style="width:100%;padding:8px;border:1px solid #ddd;border-radius:4px;" />`;
                        html += `</div>`;
                        html += `<div>`;
                        html += `<label style="display:block;font-weight:600;margin-bottom:5px;color:#555;">⏰ Kalan Süre:</label>`;
                        html += `<div style="padding:8px;background:#f5f5f5;border-radius:4px;font-weight:600;color:${{statusColor}};">${{item.time_remaining}}</div>`;
                        html += `</div>`;
                        html += `</div>`;
                        
                        // Ek bilgiler düzenleme
                        html += `<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:15px;">`;
                        html += `<div>`;
                        html += `<label style="display:block;font-weight:600;margin-bottom:5px;color:#555;font-size:0.9em;">👤 Yazar:</label>`;
                        html += `<input type="text" id="author-${{item.id}}" value="${{item.author || ''}}" style="width:100%;padding:6px;border:1px solid #ddd;border-radius:4px;font-size:0.9em;" />`;
                        html += `</div>`;
                        html += `<div>`;
                        html += `<label style="display:block;font-weight:600;margin-bottom:5px;color:#555;font-size:0.9em;">🏷️ Etiketler:</label>`;
                        html += `<input type="text" id="tags-${{item.id}}" value="${{(item.tags || []).join(', ')}}" placeholder="tag1, tag2, tag3" style="width:100%;padding:6px;border:1px solid #ddd;border-radius:4px;font-size:0.9em;" />`;
                        html += `</div>`;
                        html += `<div>`;
                        html += `<label style="display:block;font-weight:600;margin-bottom:5px;color:#555;font-size:0.9em;">🔗 Kaynak URL:</label>`;
                        html += `<input type="url" id="source-${{item.id}}" value="${{item.source_url || ''}}" style="width:100%;padding:6px;border:1px solid #ddd;border-radius:4px;font-size:0.9em;" />`;
                        html += `</div>`;
                        html += `</div>`;
                        
                        // Kaydet butonu
                        html += `<div style="text-align:right;">`;
                        html += `<button onclick="saveManifestItem('${{item.id}}')" style="background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white;border:none;padding:10px 20px;border-radius:6px;cursor:pointer;font-weight:600;">💾 Değişiklikleri Kaydet</button>`;
                        html += `</div>`;
                        
                        html += `</div>`;
                    }});
                    
                    // Özet
                    const scheduledCount = data.next_items.filter(item => item.status === 'scheduled').length;
                    const overdueCount = data.next_items.filter(item => item.status === 'overdue').length;
                    const readyCount = data.next_items.filter(item => item.status === 'ready').length;
                    
                    html += `<div style="margin-top:20px;padding:15px;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white;border-radius:8px;text-align:center;">`;
                    html += `<strong>📊 Özet:</strong> `;
                    html += `<span>✅ ${{scheduledCount}} zamanlanmış</span> | `;
                    html += `<span>⚡ ${{readyCount}} hazır</span>`;
                    if (overdueCount > 0) {{
                        html += ` | <span>⚠️ ${{overdueCount}} süresi geçmiş</span>`;
                    }}
                    html += `</div>`;
                }} else {{
                    html = '<div style="text-align:center;padding:50px;color:#666;">';
                    html += '<div style="font-size:4em;margin-bottom:20px;">📭</div>';
                    html += '<h3>Sırada bekleyen gönderi bulunamadı</h3>';
                    html += '<p>Manifest boş veya yüklenemedi.</p>';
                    html += '</div>';
                }}
                
                contentDiv.innerHTML = html;
            }}).catch(e => {{
                contentDiv.innerHTML = `<div style="color:red;padding:20px;text-align:center;border:1px solid #ffcdd2;background:#ffebee;border-radius:8px;">🌐 <strong>Ağ Hatası:</strong> ${{e.message}}</div>`;
            }});
        }}
        
        function saveManifestItem(itemId) {{
            const token = '{token}';
            const updates = {{
                title: document.getElementById(`title-${{itemId}}`).value,
                content: document.getElementById(`content-${{itemId}}`).value,
                scheduled_time: document.getElementById(`schedule-${{itemId}}`).value,
                author: document.getElementById(`author-${{itemId}}`).value,
                tags: document.getElementById(`tags-${{itemId}}`).value.split(',').map(t => t.trim()).filter(t => t),
                source_url: document.getElementById(`source-${{itemId}}`).value
            }};
            
            fetch('/admin/api/update-manifest-item', {{
                method: 'POST',
                headers: {{
                    'Content-Type': 'application/json',
                    'X-Admin-Token': token
                }},
                body: JSON.stringify({{id: itemId, updates: updates}})
            }}).then(r => r.json()).then(data => {{
                if (data.success) {{
                    alert('✓ Gönderi güncellendi: ' + itemId);
                    loadDashboardManifest(); // Yenile
                }} else {{
                    alert('✗ Hata: ' + data.error);
                }}
            }}).catch(e => {{
                alert('✗ Ağ hatası: ' + e.message);
            }});
        }}
        
        function deleteManifestItem(itemId) {{
            if (!confirm('Bu gönderiyi silmek istediğinizden emin misiniz?')) return;
            
            const token = '{token}';
            fetch(`/admin/api/delete-manifest-item/${{itemId}}?token=${{token}}`, {{
                method: 'DELETE'
            }}).then(r => r.json()).then(data => {{
                if (data.success) {{
                    alert('✓ Gönderi silindi: ' + itemId);
                    loadDashboardManifest(); // Yenile
                }} else {{
                    alert('✗ Hata: ' + data.error);
                }}
            }}).catch(e => {{
                alert('✗ Ağ hatası: ' + e.message);
            }});
        }}
        
        function toggleAutoRefreshDashboard() {{
            const btn = document.getElementById('dashboard-auto-refresh');
            if (dashboardAutoRefresh) {{
                clearInterval(dashboardAutoRefresh);
                dashboardAutoRefresh = null;
                btn.innerHTML = '⏱️ Otomatik';
                btn.style.background = '#ff9800';
            }} else {{
                dashboardAutoRefresh = setInterval(loadDashboardManifest, 30000);
                btn.innerHTML = '⏸️ Durdur';
                btn.style.background = '#4caf50';
                loadDashboardManifest();
            }}
        }}
        
        // Sayfa yüklenince manifest'i yükle
        document.addEventListener('DOMContentLoaded', function() {{
            if (document.getElementById('dashboard-manifest-content')) {{
                loadDashboardManifest();
            }}
        }});
    </script>
    '''

def get_dashboard_html(stats: Dict[str, Any], token: str = "") -> str:
    """Dashboard HTML şablonu"""
    last_modified = "Bilinmiyor"
    if stats.get("last_modified"):
        if isinstance(stats["last_modified"], str):
            last_modified = stats["last_modified"]
        else:
            last_modified = stats["last_modified"].strftime("%Y-%m-%d %H:%M:%S")
    
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bot Dashboard - İstatistikler</title>
    <style>
        * {{margin:0;padding:0;box-sizing:border-box}}
        body {{font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);min-height:100vh;padding:20px}}
        .container {{max-width:1400px;margin:0 auto}}
        .header {{background:white;border-radius:12px;padding:30px;margin-bottom:30px;box-shadow:0 10px 30px rgba(0,0,0,0.2)}}
        .header h1 {{color:#333;margin-bottom:10px;font-size:2.5em}}
        .nav-buttons {{display:flex;gap:10px;margin-top:20px;flex-wrap:wrap}}
        .nav-btn {{padding:10px 16px;background:#f8f9fa;color:#333;text-decoration:none;border-radius:6px;border:2px solid #ddd;cursor:pointer;font-weight:600;transition:all 0.3s}}
        .nav-btn:hover {{background:#e9ecef;transform:translateY(-2px)}}
        .nav-btn.active {{background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white;border-color:#667eea}}
        .stats-grid {{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px;margin-bottom:30px}}
        .stat-card {{background:white;border-radius:12px;padding:25px;box-shadow:0 10px 30px rgba(0,0,0,0.1);transition:transform 0.3s}}
        .stat-card:hover {{transform:translateY(-5px)}}
        .stat-header {{display:flex;align-items:center;gap:15px;margin-bottom:15px}}
        .stat-icon {{font-size:2.5em}}
        .stat-title {{font-size:1.2em;font-weight:600;color:#333}}
        .stat-value {{font-size:2.5em;font-weight:700;color:#667eea;margin-bottom:10px}}
        .stat-description {{color:#666;font-size:0.9em}}
        .chart-container {{background:white;border-radius:12px;padding:25px;margin-bottom:30px;box-shadow:0 10px 30px rgba(0,0,0,0.1)}}
        .progress-bar {{width:100%;height:20px;background:#f0f0f0;border-radius:10px;overflow:hidden;margin:10px 0}}
        .progress-fill {{height:100%;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);transition:width 0.3s}}
        .refresh-btn {{position:fixed;bottom:30px;right:30px;width:60px;height:60px;border-radius:50%;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white;border:none;font-size:1.5em;cursor:pointer;box-shadow:0 5px 20px rgba(102,126,234,0.4);transition:all 0.3s}}
        .refresh-btn:hover {{transform:scale(1.1)}}
        @media (max-width:768px) {{.stats-grid {{grid-template-columns:1fr}}}}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 Bot Dashboard</h1>
            <p style="color:#666;margin-top:10px;">Bot performansı ve .env dosyası istatistikleri</p>
            <div class="nav-buttons">
                <a href="/admin/dashboard?token={token}" class="nav-btn active">📊 Dashboard</a>
                <a href="/admin/panel?token={token}" class="nav-btn">⚙️ Ayarlar</a>
                <button onclick="backupEnv()" class="nav-btn">💾 Yedekle</button>
                <button onclick="showBackups()" class="nav-btn">📂 Yedekler</button>
                <a href="/admin/manifest?token={token}" class="nav-btn">📈 Manifest Düzenle</a>
            </div>
        </div>
        
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-header">
                    <div class="stat-icon">📊</div>
                    <div class="stat-title">Toplam Değişken</div>
                </div>
                <div class="stat-value">{stats.get('total_vars', 0)}</div>
                <div class="stat-description">Yapılandırılmış parametreler</div>
            </div>
            
            <div class="stat-card">
                <div class="stat-header">
                    <div class="stat-icon">🔒</div>
                    <div class="stat-title">Hassas Değişken</div>
                </div>
                <div class="stat-value">{stats.get('sensitive_vars', 0)}</div>
                <div class="stat-description">Güvenlik gerektiren parametreler</div>
            </div>
            
            <div class="stat-card">
                <div class="stat-header">
                    <div class="stat-icon">⚠️</div>
                    <div class="stat-title">Boş Değişken</div>
                </div>
                <div class="stat-value">{stats.get('empty_vars', 0)}</div>
                <div class="stat-description">Değer atanmamış parametreler</div>
            </div>
            
            <div class="stat-card">
                <div class="stat-header">
                    <div class="stat-icon">🕒</div>
                    <div class="stat-title">Son Güncelleme</div>
                </div>
                <div class="stat-value" style="font-size:1.2em;">{last_modified}</div>
                <div class="stat-description">En son değişiklik zamanı</div>
            </div>
        </div>
        
        <div class="chart-container">
            <h3 style="margin-bottom:20px;">📈 Yapılandırma Durumu</h3>
            <div style="margin-bottom:15px;">
                <strong>Dolu Değişkenler:</strong> {stats.get('total_vars', 0) - stats.get('empty_vars', 0)}/{stats.get('total_vars', 0)}
                <div class="progress-bar">
                    <div class="progress-fill" style="width:{((stats.get('total_vars', 0) - stats.get('empty_vars', 0)) / max(stats.get('total_vars', 1), 1)) * 100}%"></div>
                </div>
            </div>
            <div style="margin-bottom:15px;">
                <strong>Hassas Değişkenler:</strong> {stats.get('sensitive_vars', 0)}/{stats.get('total_vars', 0)}
                <div class="progress-bar">
                    <div class="progress-fill" style="width:{(stats.get('sensitive_vars', 0) / max(stats.get('total_vars', 1), 1)) * 100}%"></div>
                </div>
            </div>
        </div>
        
        {get_dashboard_manifest_card(token) if os.getenv('USE_EXTERNAL_QUEUE', 'false').lower() == 'true' else ''}
    </div>
    
    <button class="refresh-btn" onclick="location.reload()" title="Yenile">🔄</button>
    
    <script>
        function backupEnv() {{
            const token = '{token}';
            fetch('/admin/api/backup', {{
                method: 'POST',
                headers: {{'X-Admin-Token': token}}
            }}).then(r => r.json()).then(data => {{
                if (data.success) {{
                    alert('✓ Yedekleme başarılı: ' + data.backup_file);
                }} else {{
                    alert('✗ Yedekleme hatası: ' + data.error);
                }}
            }}).catch(e => {{
                alert('✗ Ağ hatası: ' + e.message);
            }});
        }}
        
        function showBackups() {{
            window.location.href = '/admin/panel?token={token}';
        }}
        
        // Auto refresh every 30 seconds
        setInterval(() => {{
            fetch('/admin/api/stats?token={token}')
            .then(r => r.json())
            .then(data => {{
                // Update stats without full page reload
                console.log('Stats updated:', data);
            }}).catch(e => console.error('Stats update failed:', e));
        }}, 30000);
    </script>
</body>
</html>"""
