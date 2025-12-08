"""
Kapsamlı Admin Paneli - .env Parametrelerini Yönetme
Profesyonel, kolay anlaşılır ve tam özellikli admin arayüzü
FastAPI ve Flask uyumlu yapı
"""

from flask import Flask, render_template, request, jsonify
from env_manager import get_all_env, set_env, get_env
import json
import os
from functools import wraps

# Flask standalone uygulaması
app = Flask(__name__)

def _check_admin_token(admin_token):
    """Admin token doğrulama decorator'ı"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            token = request.headers.get('X-Admin-Token', '')
            if admin_token and token != admin_token:
                return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def register_admin_routes(app_or_fastapi, env_path=".env", admin_token=""):
    """
    FastAPI veya Flask uygulamasına admin rotalarını kaydeder.
    
    Args:
        app_or_fastapi: FastAPI ya da Flask uygulaması
        env_path: .env dosyasının yolu
        admin_token: İsteğe bağlı admin token
    """
    
    # Decorator oluştur
    token_check = _check_admin_token(admin_token) if admin_token else lambda f: f
    
    # FastAPI mı Flask mi olduğunu kontrol et
    is_fastapi = hasattr(app_or_fastapi, 'add_api_route')
    
    if is_fastapi:
        # FastAPI rotaları
        
        async def get_env_api():
            """Tüm .env değerlerini döndür"""
            return get_all_env()
        
        async def update_env_api(body: dict):
            """Tüm .env değerlerini güncelle"""
            try:
                for key, value in body.items():
                    set_env(key, str(value))
                return {'status': 'success', 'message': '.env dosyası güncellendi'}
            except Exception as e:
                return {'status': 'error', 'message': str(e)}
        
        async def update_single_env_api(key: str, body: dict):
            """Tek bir .env değerini güncelle"""
            try:
                value = body.get('value', '')
                set_env(key, str(value))
                return {'status': 'success', 'message': f'{key} güncellendi'}
            except Exception as e:
                return {'status': 'error', 'message': str(e)}
        
        # Rotaları ekle
        app_or_fastapi.add_api_route("/api/env", get_env_api, methods=["GET"])
        app_or_fastapi.add_api_route("/api/env", update_env_api, methods=["POST"])
        app_or_fastapi.add_api_route("/api/env/{key}", update_single_env_api, methods=["POST"])
    else:
        # Flask rotaları
        
        @app_or_fastapi.route('/api/env', methods=['GET'])
        @token_check
        def get_env_values():
            """Tüm .env değerlerini API olarak döndür"""
            env_values = get_all_env()
            return jsonify(env_values)

        @app_or_fastapi.route('/api/env', methods=['POST'])
        @token_check
        def update_env_values():
            """Gelen .env değerlerini güncelle"""
            try:
                data = request.get_json()
                for key, value in data.items():
                    set_env(key, str(value))
                return jsonify({'status': 'success', 'message': '.env dosyası güncellendi'}), 200
            except Exception as e:
                return jsonify({'status': 'error', 'message': str(e)}), 400

        @app_or_fastapi.route('/api/env/<key>', methods=['POST'])
        @token_check
        def update_single_env(key):
            """Tek bir .env değerini güncelle"""
            try:
                data = request.get_json()
                value = data.get('value', '')
                set_env(key, str(value))
                return jsonify({'status': 'success', 'message': f'{key} güncellendi'}), 200
            except Exception as e:
                return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/')
def index():
    """Admin paneli ana sayfası"""
    env_values = get_all_env()
    return render_template('admin.html', env=env_values)

@app.route('/api/env', methods=['GET'])
def get_env_values():
    """Tüm .env değerlerini API olarak döndür"""
    env_values = get_all_env()
    return jsonify(env_values)

@app.route('/api/env', methods=['POST'])
def update_env_values():
    """Gelen .env değerlerini güncelle"""
    try:
        data = request.get_json()
        for key, value in data.items():
            set_env(key, str(value))
        return jsonify({'status': 'success', 'message': '.env dosyası güncellendi'}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/env/<key>', methods=['POST'])
def update_single_env(key):
    """Tek bir .env değerini güncelle"""
    try:
        data = request.get_json()
        value = data.get('value', '')
        set_env(key, str(value))
        return jsonify({'status': 'success', 'message': f'{key} güncellendi'}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)
