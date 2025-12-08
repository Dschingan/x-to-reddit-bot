"""
Kapsamlı Admin Paneli - .env Parametrelerini Yönetme
Profesyonel, kolay anlaşılır ve tam özellikli admin arayüzü
"""

from flask import Flask, render_template, request, jsonify
from env_manager import get_all_env, set_env, get_env
import json

app = Flask(__name__)

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
            set_env(key, value)
        return jsonify({'status': 'success', 'message': '.env dosyası güncellendi'}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/env/<key>', methods=['POST'])
def update_single_env(key):
    """Tek bir .env değerini güncelle"""
    try:
        data = request.get_json()
        value = data.get('value', '')
        set_env(key, value)
        return jsonify({'status': 'success', 'message': f'{key} güncellendi'}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)
