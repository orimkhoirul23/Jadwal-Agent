from celery import Celery
from solver_logic import run_simulation_for_api

# Konfigurasi Celery untuk terhubung ke Redis
celery = Celery(
    'tasks',
    broker='redis://127.0.0.1:6379/0',
    backend='redis://127.0.0.1:6379/0'
)

@celery.task
def run_solver_task(pre_assignment_requests, target_year, target_month):
    """Tugas yang akan dijalankan oleh Celery di latar belakang."""
    print(f"Menerima tugas untuk {target_month}/{target_year}...")
    result = run_simulation_for_api(pre_assignment_requests, target_year, target_month,num_runs=10)
    print("Tugas selesai.")
    return result