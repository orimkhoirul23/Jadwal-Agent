# file: api_server.py

import eventlet
eventlet.monkey_patch()

from flask_cors import CORS
from flask import Flask, request, jsonify, url_for
from celery_task import run_solver_task

app = Flask(__name__)
CORS(app)

@app.route('/generate-schedule', methods=['POST'])
def start_schedule_generation():
    """Endpoint untuk memulai proses pembuatan jadwal."""
    if not request.is_json:
        return jsonify({"error": "Request harus JSON"}), 400

    data = request.get_json()
    requests = data.get('requests')
    year = data.get('year')
    month = data.get('month')
    public_holidays=data.get('public_holidays')

    if requests is None or year is None or month is None:
        return jsonify({"error": "Parameter 'requests', 'year', dan 'month' dibutuhkan"}), 400

    task = run_solver_task.delay(requests, year, month,public_holidays)

    return jsonify({
        "message": "Proses pembuatan jadwal dimulai.",
        "task_id": task.id,
        "status_check_url": url_for('check_task_status', task_id=task.id, _external=True)
    }), 202

# [MODIFIKASI UTAMA DI FUNGSI INI]
@app.route('/check-status/<task_id>', methods=['GET'])
def check_task_status(task_id):
    """Endpoint untuk mengecek status dan mengambil hasil dengan lebih detail."""
    task = run_solver_task.AsyncResult(task_id)

    # 1. Jika tugas masih dalam antrian
    if task.state == 'PENDING':
        response = {"state": task.state, "status": "Proses masih dalam antrian..."}
    
    # 2. Jika tugas gagal (terjadi error di dalam Celery)
    elif task.state == 'FAILURE':
        response = {"state": task.state, "status": f"Terjadi error pada server: {str(task.info)}", "result": []}
    
    # 3. Jika tugas sudah selesai dengan SUKSES
    elif task.state == 'SUCCESS':
        # Periksa isi dari hasilnya
        if task.result and isinstance(task.result, list) and len(task.result) > 0:
            # Jika ada hasil (ditemukan jadwal)
            response = {
                "state": "SUCCESS",
                "status": "Proses selesai, jadwal ditemukan.",
                "result": task.result
            }
        else:
            # Jika hasilnya kosong (tidak ditemukan jadwal)
            response = {
                "state": "NO_SOLUTION",  # Kita gunakan state custom agar mudah dikenali di frontend
                "status": "Proses selesai, namun tidak ada jadwal valid yang bisa ditemukan.",
                "result": []
            }
    
    # 4. Jika status lainnya (misal: 'PROGRESS', 'RETRY')
    else:
        response = {"state": task.state, "status": "Proses sedang berjalan..."}

    return jsonify(response)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)