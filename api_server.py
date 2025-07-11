from flask import Flask, request, jsonify, url_for
from celery_task import run_solver_task

app = Flask(__name__)

@app.route('/generate-schedule', methods=['POST'] )
def start_schedule_generation():
    """Endpoint untuk memulai proses pembuatan jadwal."""
    if not request.is_json:
        return jsonify({"error": "Request harus JSON"}), 400

    data = request.get_json()
    requests = data.get('requests')
    year = data.get('year')
    month = data.get('month')

    if not all([requests, year, month]):
        return jsonify({"error": "Parameter 'requests', 'year', dan 'month' dibutuhkan"}), 400

    # Jalankan tugas di background dan dapatkan ID-nya
    task = run_solver_task.delay(requests, year, month)

    # Kembalikan response yang berisi URL untuk mengecek status
    return jsonify({
        "message": "Proses pembuatan jadwal dimulai.",
        "task_id": task.id,
        "status_check_url": url_for('check_task_status', task_id=task.id, _external=True)
    }), 202

@app.route('/check-status/<task_id>', methods=['GET'])
def check_task_status(task_id):
    """Endpoint untuk mengecek status dan mengambil hasil."""
    task = run_solver_task.AsyncResult(task_id)

    if task.state == 'PENDING':
        response = {"state": task.state, "status": "Proses masih dalam antrian..."}
    elif task.state != 'FAILURE':
        response = {"state": task.state, "status": "Proses sedang berjalan..."}
        if task.result:
            response['result'] = task.result
    else:
        # Terjadi error
        response = {"state": task.state, "status": str(task.info)}

    return jsonify(response)

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1',port=5001)