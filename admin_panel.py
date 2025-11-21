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
            "vars": [
                ("TWITTER_USERNAME", "Twitter Kullanıcı Adı", "text", "Bot'un Twitter hesabı"),
                ("TWITTER_USER_ID", "Twitter User ID", "text", "Bot'un Twitter ID'si"),
                ("TWITTER_BEARER_TOKEN", "Bearer Token", "password", "Twitter API Bearer Token"),
                ("TWITTER_ACCESS_TOKEN", "Access Token", "password", "Twitter API Access Token"),
                ("TWITTER_ACCESS_TOKEN_SECRET", "Access Token Secret", "password", "Twitter API Secret"),
                ("TWITTER_CONSUMER_KEY", "Consumer Key", "password", "Twitter API Consumer Key"),
                ("TWITTER_CONSUMER_SECRET", "Consumer Secret", "password", "Twitter API Consumer Secret"),
                ("TWITTER_CLIENT_ID", "Client ID", "password", "Twitter Client ID"),
                ("TWITTER_CLIENT_ID_SECRET", "Client Secret", "password", "Twitter Client Secret"),
                ("TWSCRAPE_DEBUG", "TWSCRAPE Debug Modu", "checkbox", "Debug çıktısını etkinleştir"),
            ]
        },
        "Reddit Ayarları": {
            "icon": "🔴",
            "vars": [
                ("REDDIT_USERNAME", "Reddit Kullanıcı Adı", "text", "Bot'un Reddit hesabı"),
                ("REDDIT_PASSWORD", "Reddit Şifresi", "password", "Reddit hesap şifresi"),
                ("REDDIT_CLIENT_ID", "Client ID", "text", "Reddit API Client ID"),
                ("REDDIT_CLIENT_SECRET", "Client Secret", "password", "Reddit API Secret"),
                ("REDDIT_USER_AGENT", "User Agent", "text", "Reddit API User Agent"),
                ("SUBREDDIT", "Subreddit Adı", "text", "Hedef subreddit (ör: BF6_TR)"),
                ("REDDIT_FLAIR_ID", "Flair ID", "text", "Varsayılan Flair ID"),
            ]
        },
        "API Anahtarları": {
            "icon": "🔑",
            "vars": [
                ("GEMINI_API_KEY", "Gemini API Key", "password", "Google Gemini API anahtarı"),
                ("OPENAI_API_KEY", "OpenAI API Key", "password", "OpenAI API anahtarı"),
                ("RAPIDAPI_KEY", "RapidAPI Key", "password", "RapidAPI ana anahtarı"),
                ("RAPIDAPI_TWITTER_KEY", "RapidAPI Twitter Key", "password", "RapidAPI Twitter anahtarı"),
                ("RAPIDAPI_TRANSLATE_KEY", "RapidAPI Translate Key", "password", "RapidAPI Çeviri anahtarı"),
                ("TRANSLATION_API_KEY", "Çeviri API Key", "password", "Çeviri servisi anahtarı"),
                ("GITHUB_TOKEN", "GitHub Token", "password", "GitHub API tokeni"),
            ]
        },
        "Veritabanı Ayarları": {
            "icon": "💾",
            "vars": [
                ("DATABASE_URL", "PostgreSQL URL", "password", "PostgreSQL bağlantı dizesi"),
                ("ACCOUNTS_DB_PATH", "Accounts DB Yolu", "text", "Yerel accounts.db yolu"),
                ("FAIL_IF_DB_UNAVAILABLE", "DB Hatası Durur", "checkbox", "Veritabanı yoksa durdur"),
            ]
        },
        "Manifest & Zamanlama": {
            "icon": "📅",
            "vars": [
                ("MANIFEST_URL", "Manifest URL", "text", "Manifest JSON URL'si"),
                ("USE_EXTERNAL_QUEUE", "Harici Kuyruk Kullan", "checkbox", "Manifest'ten işle"),
                ("MANIFEST_IGNORE_SCHEDULE", "Zamanlamayı Yoksay", "checkbox", "Zamanlamayı göz ardı et"),
                ("MANIFEST_POST_INTERVAL_SECONDS", "Gönderim Aralığı (sn)", "number", "Gönderiler arası bekleme"),
                ("MANIFEST_TEST_FIRST_ITEM", "İlk Öğeyi Test Et", "checkbox", "Manifest ilk öğesini test et"),
                ("FORCE_REBUILD_MANIFEST", "Manifest Yeniden Oluştur", "checkbox", "Tüm manifestı yeniden oluştur"),
                ("HIGH_WATERMARK_ENABLED", "High Watermark", "checkbox", "Eski tweet'leri atla"),
            ]
        },
        "Planlı Gönderi": {
            "icon": "📌",
            "vars": [
                ("SCHEDULED_PIN_ENABLED", "Haftalık Pin Etkin", "checkbox", "Haftalık sabit gönderi"),
            ]
        },
        "Diğer Ayarlar": {
            "icon": "⚙️",
            "vars": [
                ("SECONDARY_RETWEET_TARGET", "İkincil RT Hedefi", "text", "İkincil retweet hedefi"),
                ("SECONDARY_RETWEET_TARGET_ID", "İkincil RT Hedefi ID", "text", "İkincil retweet hedefi ID"),
                ("LOCAL_ONLY", "Sadece Lokal Mod", "checkbox", "Sadece lokal işlem yap"),
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
        """Hassas değerleri maskele"""
        sensitive_keywords = ["TOKEN", "SECRET", "KEY", "PASSWORD", "URL", "B64"]
        if any(kw in key.upper() for kw in sensitive_keywords):
            if len(value) > 4:
                return value[:2] + "*" * (len(value) - 4) + value[-2:]
            return "*" * len(value)
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
        
        # Kategoriler HTML'i oluştur
        categories_html = ""
        for category, info in ENV_CATEGORIES.items():
            categories_html += f'<div class="category-card"><div class="category-header"><span class="category-icon">{info["icon"]}</span><h3>{category}</h3></div><div class="category-content">'
            
            for var_name, label, input_type, description in info["vars"]:
                current_value = manager.get_env_var(var_name) or ""
                display_value = _mask_sensitive(var_name, current_value)
                
                if input_type == "checkbox":
                    checked = "checked" if current_value.lower() in ["true", "1", "yes"] else ""
                    categories_html += f'<div class="form-group"><label class="checkbox-label"><input type="checkbox" name="{var_name}" {checked} class="env-input" data-token="{token}"/><span class="checkbox-text">{label}</span></label><small class="description">{description}</small></div>'
                elif input_type == "textarea":
                    categories_html += f'<div class="form-group"><label>{label}</label><small class="description">{description}</small><textarea class="env-input" name="{var_name}" rows="3" data-token="{token}" placeholder="Değer girin...">{current_value}</textarea><button class="btn-save" onclick="saveEnvVar(\'{var_name}\', this)">💾 Kaydet</button></div>'
                elif input_type == "password":
                    categories_html += f'<div class="form-group"><label>{label}</label><small class="description">{description}</small><div class="password-group"><input type="password" class="env-input" name="{var_name}" value="{display_value}" data-token="{token}" placeholder="Değer girin..."/><button class="btn-toggle" onclick="togglePasswordVisibility(this)">👁️</button></div><button class="btn-save" onclick="saveEnvVar(\'{var_name}\', this)">💾 Kaydet</button></div>'
                else:
                    categories_html += f'<div class="form-group"><label>{label}</label><small class="description">{description}</small><input type="{input_type}" class="env-input" name="{var_name}" value="{current_value}" data-token="{token}" placeholder="Değer girin..."/><button class="btn-save" onclick="saveEnvVar(\'{var_name}\', this)">💾 Kaydet</button></div>'
            
            categories_html += "</div></div>"
        
        return HTMLResponse(get_admin_html(categories_html, current_time, token))
    
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


def get_admin_html(categories_html: str, current_time: str, token: str = "") -> str:
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
        .category-card {{background:white;border-radius:12px;overflow:hidden;box-shadow:0 10px 30px rgba(0,0,0,0.1);transition:transform 0.3s,box-shadow 0.3s}}
        .category-card:hover {{transform:translateY(-5px);box-shadow:0 15px 40px rgba(0,0,0,0.15)}}
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
            </div>
        </div>
        <div class="categories-grid">{categories_html}</div>
        <div class="footer">
            <p>💡 İpucu: Değişiklikleri kaydettikten sonra botu yeniden başlatmanız gerekebilir.</p>
            <p style="margin-top:10px;font-size:0.85em;">Hassas veriler maskeli gösterilmektedir.</p>
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
    </script>
</body>
</html>"""


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
