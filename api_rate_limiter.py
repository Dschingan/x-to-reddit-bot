"""
X API Free Plan Rate Limiter
Otomatik limit algılama ve günlük istek dağıtımı
"""

import os
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import threading


class XAPIRateLimiter:
    """X API Free Plan için akıllı rate limiter"""
    
    # X API Free Plan varsayılan limitleri (aylık)
    DEFAULT_MONTHLY_TWEET_CAP = 1500  # Free plan: 1,500 tweet reads/month
    DEFAULT_MONTHLY_USER_LOOKUP = 50   # Free plan: 50 user lookups/month
    
    def __init__(self, config_file: str = "rate_limit_config.json"):
        self.config_file = Path(config_file)
        self.lock = threading.Lock()
        self.config = self._load_config()
        self._ensure_daily_reset()
        
    def _load_config(self) -> Dict:
        """Konfigürasyonu yükle veya varsayılan oluştur"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # Eksik alanları tamamla
                    return self._ensure_config_fields(config)
            except Exception as e:
                print(f"[UYARI] Konfigürasyon yüklenemedi: {e}")
        
        # Varsayılan konfigürasyon
        return self._create_default_config()
    
    def _create_default_config(self) -> Dict:
        """Varsayılan konfigürasyon oluştur"""
        # Çevre değişkenlerinden limitleri al
        monthly_limit = int(os.getenv("X_API_MONTHLY_LIMIT", str(self.DEFAULT_MONTHLY_TWEET_CAP)))
        
        # Aylık limiti 30 güne eşit dağıt
        daily_safe_limit = int(monthly_limit / 30 * 0.9)  # %10 güvenlik marjı
        
        config = {
            "api_plan": "free",  # free, basic, pro, enterprise
            "monthly_limit": monthly_limit,
            "daily_limit": daily_safe_limit,
            "manual_daily_limit": None,  # Kullanıcı manuel ayarlarsa
            "current_month": datetime.now().strftime("%Y-%m"),
            "monthly_usage": 0,
            "daily_usage": 0,
            "last_reset_date": datetime.now().strftime("%Y-%m-%d"),
            "enabled_hours": list(range(24)),  # Tüm saatler aktif
            "disabled_hours": [],  # Devre dışı saatler
            "hourly_distribution": {},  # Saatlik dağıtım
            "request_history": [],  # Son 100 istek
            "stats": {
                "total_requests": 0,
                "total_blocked": 0,
                "total_allowed": 0,
                "last_request_time": None
            }
        }
        
        self._save_config(config)
        return config
    
    def _ensure_config_fields(self, config: Dict) -> Dict:
        """Eksik konfigürasyon alanlarını tamamla"""
        default = self._create_default_config()
        for key, value in default.items():
            if key not in config:
                config[key] = value
        return config
    
    def _save_config(self, config: Optional[Dict] = None):
        """Konfigürasyonu kaydet"""
        if config is None:
            config = self.config
        
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[HATA] Konfigürasyon kaydedilemedi: {e}")
    
    def _ensure_daily_reset(self):
        """Günlük reset kontrolü"""
        today = datetime.now().strftime("%Y-%m-%d")
        current_month = datetime.now().strftime("%Y-%m")
        
        with self.lock:
            # Günlük reset
            if self.config.get("last_reset_date") != today:
                print(f"[+] Günlük limit sıfırlanıyor: {self.config.get('daily_usage', 0)} istek kullanıldı")
                self.config["daily_usage"] = 0
                self.config["last_reset_date"] = today
                self._save_config()
            
            # Aylık reset
            if self.config.get("current_month") != current_month:
                print(f"[+] Aylık limit sıfırlanıyor: {self.config.get('monthly_usage', 0)} istek kullanıldı")
                self.config["monthly_usage"] = 0
                self.config["current_month"] = current_month
                self._save_config()
    
    def can_make_request(self) -> Tuple[bool, str]:
        """İstek yapılabilir mi kontrol et"""
        self._ensure_daily_reset()
        
        with self.lock:
            current_hour = datetime.now().hour
            
            # Saat kontrolü
            if current_hour in self.config.get("disabled_hours", []):
                return False, f"Saat {current_hour}:00 devre dışı"
            
            if current_hour not in self.config.get("enabled_hours", list(range(24))):
                return False, f"Saat {current_hour}:00 aktif değil"
            
            # Günlük limit kontrolü
            daily_limit = self.config.get("manual_daily_limit") or self.config.get("daily_limit", 50)
            if self.config.get("daily_usage", 0) >= daily_limit:
                return False, f"Günlük limit aşıldı ({daily_limit})"
            
            # Aylık limit kontrolü
            monthly_limit = self.config.get("monthly_limit", self.DEFAULT_MONTHLY_TWEET_CAP)
            if self.config.get("monthly_usage", 0) >= monthly_limit:
                return False, f"Aylık limit aşıldı ({monthly_limit})"
            
            return True, "OK"
    
    def record_request(self, success: bool = True):
        """İstek kaydı tut"""
        with self.lock:
            self.config["daily_usage"] = self.config.get("daily_usage", 0) + 1
            self.config["monthly_usage"] = self.config.get("monthly_usage", 0) + 1
            
            # İstatistikler
            stats = self.config.get("stats", {})
            stats["total_requests"] = stats.get("total_requests", 0) + 1
            if success:
                stats["total_allowed"] = stats.get("total_allowed", 0) + 1
            stats["last_request_time"] = datetime.now().isoformat()
            self.config["stats"] = stats
            
            # İstek geçmişi (son 100)
            history = self.config.get("request_history", [])
            history.append({
                "timestamp": datetime.now().isoformat(),
                "hour": datetime.now().hour,
                "success": success
            })
            self.config["request_history"] = history[-100:]  # Son 100 kayıt
            
            self._save_config()
    
    def get_remaining_requests(self) -> Dict:
        """Kalan istek sayılarını döndür"""
        self._ensure_daily_reset()
        
        with self.lock:
            daily_limit = self.config.get("manual_daily_limit") or self.config.get("daily_limit", 50)
            monthly_limit = self.config.get("monthly_limit", self.DEFAULT_MONTHLY_TWEET_CAP)
            
            return {
                "daily_remaining": max(0, daily_limit - self.config.get("daily_usage", 0)),
                "daily_limit": daily_limit,
                "daily_used": self.config.get("daily_usage", 0),
                "monthly_remaining": max(0, monthly_limit - self.config.get("monthly_usage", 0)),
                "monthly_limit": monthly_limit,
                "monthly_used": self.config.get("monthly_usage", 0),
                "current_hour": datetime.now().hour,
                "hour_enabled": datetime.now().hour in self.config.get("enabled_hours", list(range(24)))
            }
    
    def set_daily_limit(self, limit: int):
        """Manuel günlük limit ayarla"""
        with self.lock:
            self.config["manual_daily_limit"] = limit
            self._save_config()
            print(f"[+] Günlük limit ayarlandı: {limit}")
    
    def set_enabled_hours(self, hours: List[int]):
        """Aktif saatleri ayarla"""
        with self.lock:
            # 0-23 arası geçerli saatler
            valid_hours = [h for h in hours if 0 <= h <= 23]
            self.config["enabled_hours"] = valid_hours
            self.config["disabled_hours"] = [h for h in range(24) if h not in valid_hours]
            self._save_config()
            print(f"[+] Aktif saatler ayarlandı: {valid_hours}")
    
    def toggle_hour(self, hour: int, enabled: bool):
        """Belirli bir saati aktif/pasif yap"""
        if not 0 <= hour <= 23:
            return
        
        with self.lock:
            enabled_hours = set(self.config.get("enabled_hours", list(range(24))))
            
            if enabled:
                enabled_hours.add(hour)
            else:
                enabled_hours.discard(hour)
            
            self.config["enabled_hours"] = sorted(list(enabled_hours))
            self.config["disabled_hours"] = [h for h in range(24) if h not in enabled_hours]
            self._save_config()
            print(f"[+] Saat {hour}:00 {'aktif' if enabled else 'pasif'} edildi")
    
    def get_stats(self) -> Dict:
        """İstatistikleri döndür"""
        self._ensure_daily_reset()
        
        with self.lock:
            stats = self.config.get("stats", {})
            history = self.config.get("request_history", [])
            
            # Saatlik dağılım hesapla
            hourly_dist = {}
            for record in history:
                hour = record.get("hour", 0)
                hourly_dist[hour] = hourly_dist.get(hour, 0) + 1
            
            return {
                "total_requests": stats.get("total_requests", 0),
                "total_allowed": stats.get("total_allowed", 0),
                "total_blocked": stats.get("total_blocked", 0),
                "last_request_time": stats.get("last_request_time"),
                "hourly_distribution": hourly_dist,
                "enabled_hours": self.config.get("enabled_hours", []),
                "disabled_hours": self.config.get("disabled_hours", []),
                "daily_usage": self.config.get("daily_usage", 0),
                "monthly_usage": self.config.get("monthly_usage", 0)
            }
    
    def reset_daily_usage(self):
        """Günlük kullanımı manuel sıfırla"""
        with self.lock:
            self.config["daily_usage"] = 0
            self._save_config()
            print("[+] Günlük kullanım manuel olarak sıfırlandı")
    
    def reset_monthly_usage(self):
        """Aylık kullanımı manuel sıfırla"""
        with self.lock:
            self.config["monthly_usage"] = 0
            self._save_config()
            print("[+] Aylık kullanım manuel olarak sıfırlandı")


# Global rate limiter instance
_rate_limiter = None
_limiter_lock = threading.Lock()


def get_rate_limiter() -> XAPIRateLimiter:
    """Global rate limiter instance'ını al"""
    global _rate_limiter
    
    if _rate_limiter is None:
        with _limiter_lock:
            if _rate_limiter is None:
                _rate_limiter = XAPIRateLimiter()
    
    return _rate_limiter


def can_make_api_request() -> Tuple[bool, str]:
    """API isteği yapılabilir mi kontrol et (kolay kullanım)"""
    limiter = get_rate_limiter()
    return limiter.can_make_request()


def record_api_request(success: bool = True):
    """API isteğini kaydet (kolay kullanım)"""
    limiter = get_rate_limiter()
    limiter.record_request(success)


def get_api_limits() -> Dict:
    """API limitlerini al (kolay kullanım)"""
    limiter = get_rate_limiter()
    return limiter.get_remaining_requests()


if __name__ == "__main__":
    # Test
    limiter = XAPIRateLimiter()
    
    print("\n=== X API Rate Limiter Test ===\n")
    
    # Mevcut durumu göster
    remaining = limiter.get_remaining_requests()
    print(f"Günlük kalan: {remaining['daily_remaining']}/{remaining['daily_limit']}")
    print(f"Aylık kalan: {remaining['monthly_remaining']}/{remaining['monthly_limit']}")
    print(f"Aktif saat: {remaining['current_hour']} ({'Evet' if remaining['hour_enabled'] else 'Hayır'})")
    
    # İstek testi
    can_request, reason = limiter.can_make_request()
    print(f"\nİstek yapılabilir: {can_request} ({reason})")
    
    if can_request:
        limiter.record_request(success=True)
        print("Test isteği kaydedildi")
    
    # İstatistikler
    stats = limiter.get_stats()
    print(f"\nToplam istek: {stats['total_requests']}")
    print(f"Aktif saatler: {stats['enabled_hours']}")
