"""
Admin Panel için Rate Limiter Kontrolleri
X API Free Plan limit yönetimi için gelişmiş arayüz
"""

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from typing import Dict, Any
import os


def register_rate_limiter_routes(app: FastAPI, admin_token: str = ""):
    """Rate limiter yönetimi için admin route'ları"""
    
    def _is_admin(request: Request) -> bool:
        """Admin token kontrolü"""
        if not admin_token:
            return True
        token = request.headers.get("X-Admin-Token") or request.query_params.get("token")
        return token == admin_token
    
    @app.get("/admin/rate-limiter", response_class=HTMLResponse)
    def rate_limiter_panel(request: Request):
        """Rate limiter yönetim paneli"""
        if not _is_admin(request):
            return HTMLResponse("<h1>Unauthorized</h1>", status_code=401)
        
        token = request.query_params.get("token", "")
        return HTMLResponse(get_rate_limiter_html(token))
    
    @app.get("/admin/api/rate-limiter/status")
    def api_rate_limiter_status(request: Request):
        """Rate limiter durumunu al"""
        if not _is_admin(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        
        try:
            from api_rate_limiter import get_rate_limiter
            limiter = get_rate_limiter()
            
            remaining = limiter.get_remaining_requests()
            stats = limiter.get_stats()
            
            return JSONResponse({
                "success": True,
                "remaining": remaining,
                "stats": stats,
                "config": {
                    "daily_limit": remaining["daily_limit"],
                    "monthly_limit": remaining["monthly_limit"],
                    "enabled_hours": stats["enabled_hours"],
                    "disabled_hours": stats["disabled_hours"]
                }
            })
        except Exception as e:
            return JSONResponse({"success": False, "error": str(e)})
    
    @app.post("/admin/api/rate-limiter/set-daily-limit")
    async def api_set_daily_limit(request: Request):
        """Günlük limiti ayarla"""
        if not _is_admin(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        
        try:
            data = await request.json()
            limit = int(data.get("limit", 50))
            
            from api_rate_limiter import get_rate_limiter
            limiter = get_rate_limiter()
            limiter.set_daily_limit(limit)
            
            return JSONResponse({"success": True, "limit": limit})
        except Exception as e:
            return JSONResponse({"success": False, "error": str(e)})
    
    @app.post("/admin/api/rate-limiter/set-enabled-hours")
    async def api_set_enabled_hours(request: Request):
        """Aktif saatleri ayarla"""
        if not _is_admin(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        
        try:
            data = await request.json()
            hours = data.get("hours", [])
            
            # Validate hours
            hours = [int(h) for h in hours if 0 <= int(h) <= 23]
            
            from api_rate_limiter import get_rate_limiter
            limiter = get_rate_limiter()
            limiter.set_enabled_hours(hours)
            
            return JSONResponse({"success": True, "enabled_hours": hours})
        except Exception as e:
            return JSONResponse({"success": False, "error": str(e)})
    
    @app.post("/admin/api/rate-limiter/toggle-hour")
    async def api_toggle_hour(request: Request):
        """Belirli bir saati aktif/pasif yap"""
        if not _is_admin(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        
        try:
            data = await request.json()
            hour = int(data.get("hour", 0))
            enabled = data.get("enabled", True)
            
            from api_rate_limiter import get_rate_limiter
            limiter = get_rate_limiter()
            limiter.toggle_hour(hour, enabled)
            
            return JSONResponse({"success": True, "hour": hour, "enabled": enabled})
        except Exception as e:
            return JSONResponse({"success": False, "error": str(e)})
    
    @app.post("/admin/api/rate-limiter/reset-daily")
    def api_reset_daily(request: Request):
        """Günlük kullanımı sıfırla"""
        if not _is_admin(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        
        try:
            from api_rate_limiter import get_rate_limiter
            limiter = get_rate_limiter()
            limiter.reset_daily_usage()
            
            return JSONResponse({"success": True})
        except Exception as e:
            return JSONResponse({"success": False, "error": str(e)})
    
    @app.post("/admin/api/rate-limiter/reset-monthly")
    def api_reset_monthly(request: Request):
        """Aylık kullanımı sıfırla"""
        if not _is_admin(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        
        try:
            from api_rate_limiter import get_rate_limiter
            limiter = get_rate_limiter()
            limiter.reset_monthly_usage()
            
            return JSONResponse({"success": True})
        except Exception as e:
            return JSONResponse({"success": False, "error": str(e)})


def get_rate_limiter_html(token: str = "") -> str:
    """Rate limiter yönetim paneli HTML"""
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>X API Rate Limiter - Yönetim Paneli</title>
    <style>
        * {{margin:0;padding:0;box-sizing:border-box}}
        body {{font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);min-height:100vh;padding:20px}}
        .container {{max-width:1200px;margin:0 auto}}
        .header {{background:white;border-radius:12px;padding:30px;margin-bottom:30px;box-shadow:0 10px 30px rgba(0,0,0,0.2)}}
        .header h1 {{color:#333;margin-bottom:10px;font-size:2.5em}}
        .card {{background:white;border-radius:12px;padding:25px;margin-bottom:20px;box-shadow:0 10px 30px rgba(0,0,0,0.1)}}
        .card h2 {{color:#667eea;margin-bottom:20px;font-size:1.5em}}
        .stats-grid {{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:15px;margin-bottom:25px}}
        .stat-box {{background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white;padding:20px;border-radius:8px;text-align:center}}
        .stat-box h3 {{font-size:2em;margin-bottom:5px}}
        .stat-box p {{font-size:0.9em;opacity:0.9}}
        .progress-bar {{background:#e0e0e0;border-radius:10px;height:20px;overflow:hidden;margin:10px 0}}
        .progress-fill {{background:linear-gradient(90deg,#4caf50,#8bc34a);height:100%;transition:width 0.3s}}
        .hours-grid {{display:grid;grid-template-columns:repeat(auto-fill,minmax(60px,1fr));gap:10px;margin:20px 0}}
        .hour-btn {{padding:15px;border:2px solid #ddd;border-radius:8px;background:white;cursor:pointer;text-align:center;transition:all 0.3s;font-weight:600}}
        .hour-btn.active {{background:linear-gradient(135deg,#4caf50,#8bc34a);color:white;border-color:#4caf50}}
        .hour-btn.disabled {{background:#f44336;color:white;border-color:#f44336}}
        .hour-btn:hover {{transform:translateY(-2px);box-shadow:0 4px 12px rgba(0,0,0,0.15)}}
        .btn {{padding:12px 24px;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white;border:none;border-radius:6px;cursor:pointer;font-weight:600;transition:all 0.3s;font-size:1em}}
        .btn:hover {{transform:translateY(-2px);box-shadow:0 5px 15px rgba(102,126,234,0.4)}}
        .btn-danger {{background:linear-gradient(135deg,#f44336,#e91e63)}}
        .btn-success {{background:linear-gradient(135deg,#4caf50,#8bc34a)}}
        .input-group {{margin:15px 0}}
        .input-group label {{display:block;font-weight:600;margin-bottom:8px;color:#333}}
        .input-group input {{width:100%;padding:12px;border:2px solid #ddd;border-radius:6px;font-size:1em}}
        .notification {{position:fixed;top:20px;right:20px;padding:16px 20px;background:white;border-radius:8px;box-shadow:0 5px 20px rgba(0,0,0,0.2);z-index:1000;animation:slideIn 0.3s}}
        .notification.success {{border-left:4px solid #4CAF50}}
        .notification.error {{border-left:4px solid #f44336}}
        @keyframes slideIn {{from {{transform:translateX(400px);opacity:0}} to {{transform:translateX(0);opacity:1}}}}
        .nav-buttons {{display:flex;gap:10px;margin-top:20px;flex-wrap:wrap}}
        .nav-btn {{padding:10px 16px;background:#f8f9fa;color:#333;text-decoration:none;border-radius:6px;border:2px solid #ddd;cursor:pointer;font-weight:600;transition:all 0.3s}}
        .nav-btn:hover {{background:#e9ecef;transform:translateY(-2px)}}
        .chart-container {{background:#fafafa;padding:20px;border-radius:8px;margin:20px 0}}
        @media (max-width:768px) {{.stats-grid {{grid-template-columns:1fr}} .hours-grid {{grid-template-columns:repeat(6,1fr)}}}}
    
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>⚡ X API Rate Limiter</h1>
            <p style="color:#666;margin-top:10px;">X API Free Plan limit yönetimi ve zamanlama</p>
            <div class="nav-buttons">
                <a href="/admin/panel?token={token}" class="nav-btn">⚙️ Ana Panel</a>
                <a href="/admin/dashboard?token={token}" class="nav-btn">📊 Dashboard</a>
                <a href="/admin/rate-limiter?token={token}" class="nav-btn" style="background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white;border-color:#667eea;">⚡ Rate Limiter</a>
                <button onclick="loadStatus()" class="nav-btn">🔄 Yenile</button>
            </div>
        </div>
        
        <!-- İstatistikler -->
        <div class="card">
            <h2>📊 Kullanım İstatistikleri</h2>
            <div class="stats-grid">
                <div class="stat-box">
                    <h3 id="daily-remaining">-</h3>
                    <p>Günlük Kalan</p>
                </div>
                <div class="stat-box">
                    <h3 id="daily-used">-</h3>
                    <p>Bugün Kullanılan</p>
                </div>
                <div class="stat-box">
                    <h3 id="monthly-remaining">-</h3>
                    <p>Aylık Kalan</p>
                </div>
                <div class="stat-box">
                    <h3 id="monthly-used">-</h3>
                    <p>Bu Ay Kullanılan</p>
                </div>
            </div>
            
            <div>
                <strong>Günlük Kullanım:</strong>
                <div class="progress-bar">
                    <div class="progress-fill" id="daily-progress" style="width:0%"></div>
                </div>
                <span id="daily-percentage">0%</span>
            </div>
            
            <div style="margin-top:15px;">
                <strong>Aylık Kullanım:</strong>
                <div class="progress-bar">
                    <div class="progress-fill" id="monthly-progress" style="width:0%"></div>
                </div>
                <span id="monthly-percentage">0%</span>
            </div>
        </div>
        
        <!-- Günlük Limit Ayarı -->
        <div class="card">
            <h2>🎯 Günlük İstek Limiti</h2>
            <p style="color:#666;margin-bottom:15px;">X API Free Plan varsayılan: 1,500 tweet/ay → ~50 tweet/gün (güvenli limit)</p>
            <div class="input-group">
                <label>Günlük Maksimum İstek Sayısı:</label>
                <input type="number" id="daily-limit-input" min="1" max="500" value="50" />
            </div>
            <button onclick="setDailyLimit()" class="btn">💾 Limiti Kaydet</button>
            <button onclick="resetDaily()" class="btn btn-danger" style="margin-left:10px;">🔄 Günlük Kullanımı Sıfırla</button>
        </div>
        
        <!-- Saatlik Zamanlama -->
        <div class="card">
            <h2>⏰ Saatlik İstek Zamanlaması</h2>
            <p style="color:#666;margin-bottom:15px;">Hangi saatlerde API isteği yapılacağını seçin. Yeşil = Aktif, Kırmızı = Pasif</p>
            
            <div style="margin:15px 0;">
                <button onclick="enableAllHours()" class="btn btn-success">✅ Tümünü Aktif Et</button>
                <button onclick="disableAllHours()" class="btn btn-danger" style="margin-left:10px;">❌ Tümünü Pasif Et</button>
                <button onclick="setBusinessHours()" class="btn" style="margin-left:10px;">🏢 Mesai Saatleri (9-18)</button>
            </div>
            
            <div class="hours-grid" id="hours-grid">
                <!-- JavaScript ile doldurulacak -->
            </div>
            
            <div style="margin-top:20px;">
                <button onclick="saveHours()" class="btn">💾 Saatleri Kaydet</button>
            </div>
        </div>
        
        <!-- Gelişmiş İstatistikler -->
        <div class="card">
            <h2>📈 Gelişmiş İstatistikler</h2>
            <div class="chart-container">
                <h3 style="margin-bottom:15px;">Saatlik Dağılım</h3>
                <div id="hourly-chart" style="min-height:200px;">
                    <!-- Chart buraya gelecek -->
                </div>
            </div>
            
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:15px;margin-top:20px;">
                <div style="padding:15px;background:#e3f2fd;border-radius:8px;">
                    <strong style="color:#1976d2;">Toplam İstek:</strong>
                    <h3 id="total-requests" style="color:#1976d2;margin-top:5px;">-</h3>
                </div>
                <div style="padding:15px;background:#e8f5e9;border-radius:8px;">
                    <strong style="color:#388e3c;">Başarılı:</strong>
                    <h3 id="total-allowed" style="color:#388e3c;margin-top:5px;">-</h3>
                </div>
                <div style="padding:15px;background:#ffebee;border-radius:8px;">
                    <strong style="color:#d32f2f;">Engellenen:</strong>
                    <h3 id="total-blocked" style="color:#d32f2f;margin-top:5px;">-</h3>
                </div>
            </div>
        </div>
        
        <!-- Tehlikeli İşlemler -->
        <div class="card" style="border:2px solid #f44336;">
            <h2 style="color:#f44336;">⚠️ Tehlikeli İşlemler</h2>
            <p style="color:#666;margin-bottom:15px;">Bu işlemler geri alınamaz. Dikkatli kullanın!</p>
            <button onclick="resetMonthly()" class="btn btn-danger">🔄 Aylık Kullanımı Sıfırla</button>
        </div>
    </div>
    
    <script>
        const TOKEN = '{token}';
        let currentEnabledHours = [];
        
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
        
        function loadStatus() {{
            fetch('/admin/api/rate-limiter/status?token=' + TOKEN)
            .then(r => r.json())
            .then(data => {{
                if (!data.success) {{
                    showNotification('Hata: ' + data.error, 'error');
                    return;
                }}
                
                // İstatistikleri güncelle
                const remaining = data.remaining;
                const stats = data.stats;
                
                document.getElementById('daily-remaining').textContent = remaining.daily_remaining;
                document.getElementById('daily-used').textContent = remaining.daily_used;
                document.getElementById('monthly-remaining').textContent = remaining.monthly_remaining;
                document.getElementById('monthly-used').textContent = remaining.monthly_used;
                
                // Progress bar'ları güncelle
                const dailyPercent = (remaining.daily_used / remaining.daily_limit * 100).toFixed(1);
                const monthlyPercent = (remaining.monthly_used / remaining.monthly_limit * 100).toFixed(1);
                
                document.getElementById('daily-progress').style.width = dailyPercent + '%';
                document.getElementById('daily-percentage').textContent = dailyPercent + '%';
                document.getElementById('monthly-progress').style.width = monthlyPercent + '%';
                document.getElementById('monthly-percentage').textContent = monthlyPercent + '%';
                
                // Limit input'u güncelle
                document.getElementById('daily-limit-input').value = remaining.daily_limit;
                
                // Gelişmiş istatistikler
                document.getElementById('total-requests').textContent = stats.total_requests || 0;
                document.getElementById('total-allowed').textContent = stats.total_allowed || 0;
                document.getElementById('total-blocked').textContent = stats.total_blocked || 0;
                
                // Aktif saatleri güncelle
                currentEnabledHours = stats.enabled_hours || [];
                renderHoursGrid();
                
                // Saatlik dağılım grafiği
                renderHourlyChart(stats.hourly_distribution || {{}});
            }})
            .catch(e => {{
                showNotification('Ağ hatası: ' + e.message, 'error');
            }});
        }}
        
        function renderHoursGrid() {{
            const grid = document.getElementById('hours-grid');
            grid.innerHTML = '';
            
            for (let hour = 0; hour < 24; hour++) {{
                const btn = document.createElement('div');
                btn.className = 'hour-btn';
                btn.textContent = hour.toString().padStart(2, '0') + ':00';
                
                if (currentEnabledHours.includes(hour)) {{
                    btn.classList.add('active');
                }} else {{
                    btn.classList.add('disabled');
                }}
                
                btn.onclick = function() {{
                    toggleHour(hour);
                }};
                
                grid.appendChild(btn);
            }}
        }}
        
        function toggleHour(hour) {{
            const index = currentEnabledHours.indexOf(hour);
            if (index > -1) {{
                currentEnabledHours.splice(index, 1);
            }} else {{
                currentEnabledHours.push(hour);
            }}
            currentEnabledHours.sort((a, b) => a - b);
            renderHoursGrid();
        }}
        
        function enableAllHours() {{
            currentEnabledHours = Array.from({{length: 24}}, (_, i) => i);
            renderHoursGrid();
        }}
        
        function disableAllHours() {{
            currentEnabledHours = [];
            renderHoursGrid();
        }}
        
        function setBusinessHours() {{
            currentEnabledHours = [9, 10, 11, 12, 13, 14, 15, 16, 17, 18];
            renderHoursGrid();
        }}
        
        function saveHours() {{
            fetch('/admin/api/rate-limiter/set-enabled-hours', {{
                method: 'POST',
                headers: {{
                    'Content-Type': 'application/json',
                    'X-Admin-Token': TOKEN
                }},
                body: JSON.stringify({{hours: currentEnabledHours}})
            }})
            .then(r => r.json())
            .then(data => {{
                if (data.success) {{
                    showNotification('✓ Saatler kaydedildi', 'success');
                    loadStatus();
                }} else {{
                    showNotification('✗ Hata: ' + data.error, 'error');
                }}
            }})
            .catch(e => {{
                showNotification('✗ Ağ hatası: ' + e.message, 'error');
            }});
        }}
        
        function setDailyLimit() {{
            const limit = parseInt(document.getElementById('daily-limit-input').value);
            
            if (limit < 1 || limit > 500) {{
                showNotification('✗ Limit 1-500 arasında olmalı', 'error');
                return;
            }}
            
            fetch('/admin/api/rate-limiter/set-daily-limit', {{
                method: 'POST',
                headers: {{
                    'Content-Type': 'application/json',
                    'X-Admin-Token': TOKEN
                }},
                body: JSON.stringify({{limit: limit}})
            }})
            .then(r => r.json())
            .then(data => {{
                if (data.success) {{
                    showNotification('✓ Günlük limit ayarlandı: ' + limit, 'success');
                    loadStatus();
                }} else {{
                    showNotification('✗ Hata: ' + data.error, 'error');
                }}
            }})
            .catch(e => {{
                showNotification('✗ Ağ hatası: ' + e.message, 'error');
            }});
        }}
        
        function resetDaily() {{
            if (!confirm('Günlük kullanımı sıfırlamak istediğinizden emin misiniz?')) return;
            
            fetch('/admin/api/rate-limiter/reset-daily', {{
                method: 'POST',
                headers: {{'X-Admin-Token': TOKEN}}
            }})
            .then(r => r.json())
            .then(data => {{
                if (data.success) {{
                    showNotification('✓ Günlük kullanım sıfırlandı', 'success');
                    loadStatus();
                }} else {{
                    showNotification('✗ Hata: ' + data.error, 'error');
                }}
            }})
            .catch(e => {{
                showNotification('✗ Ağ hatası: ' + e.message, 'error');
            }});
        }}
        
        function resetMonthly() {{
            if (!confirm('UYARI: Aylık kullanımı sıfırlamak istediğinizden emin misiniz? Bu işlem geri alınamaz!')) return;
            
            fetch('/admin/api/rate-limiter/reset-monthly', {{
                method: 'POST',
                headers: {{'X-Admin-Token': TOKEN}}
            }})
            .then(r => r.json())
            .then(data => {{
                if (data.success) {{
                    showNotification('✓ Aylık kullanım sıfırlandı', 'success');
                    loadStatus();
                }} else {{
                    showNotification('✗ Hata: ' + data.error, 'error');
                }}
            }})
            .catch(e => {{
                showNotification('✗ Ağ hatası: ' + e.message, 'error');
            }});
        }}
        
        function renderHourlyChart(distribution) {{
            const chartDiv = document.getElementById('hourly-chart');
            let html = '<div style="display:flex;align-items:flex-end;gap:5px;height:150px;">';
            
            const maxValue = Math.max(...Object.values(distribution), 1);
            
            for (let hour = 0; hour < 24; hour++) {{
                const value = distribution[hour] || 0;
                const height = (value / maxValue * 100).toFixed(1);
                const color = currentEnabledHours.includes(hour) ? '#4caf50' : '#f44336';
                
                html += '<div style="flex:1;display:flex;flex-direction:column;align-items:center;">';
                html += '<div style="font-size:0.7em;margin-bottom:2px;">' + value + '</div>';
                html += '<div style="width:100%;background:' + color + ';height:' + height + '%;min-height:2px;border-radius:3px 3px 0 0;"></div>';
                html += '<div style="font-size:0.7em;margin-top:2px;">' + hour + '</div>';
                html += '</div>';
            }}
            
            html += '</div>';
            chartDiv.innerHTML = html;
        }}
        
        // Sayfa yüklendiğinde durumu yükle
        document.addEventListener('DOMContentLoaded', loadStatus);
        
        // Otomatik yenileme (30 saniyede bir)
        setInterval(loadStatus, 30000);
    </script>
</body>
</html>"""


# Admin panel kategorilerine rate limiter eklemek için
def get_rate_limiter_category():
    """Admin panel için rate limiter kategorisi"""
    return {
        "icon": "⚡",
        "hidden_if_external_queue": False,
        "vars": [
            ("X_API_MONTHLY_LIMIT", "Aylık API Limiti", "number", "X API Free Plan aylık tweet okuma limiti (varsayılan: 1500)"),
            ("X_API_DAILY_LIMIT_OVERRIDE", "Günlük Limit (Manuel)", "number", "Manuel günlük limit (boş bırakılırsa otomatik hesaplanır)"),
            ("RATE_LIMITER_ENABLED", "Rate Limiter Aktif", "checkbox", "✅ API rate limiting aktif | ❌ Sınırsız istek"),
        ]
    }
