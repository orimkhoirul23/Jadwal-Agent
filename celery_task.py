import eventlet
eventlet.monkey_patch()

from celery import Celery
from solver_2 import run_simulation_for_api

# Konfigurasi Celery untuk terhubung ke Redis
celery = Celery(
    'tasks',
    broker='redis://redis:6379/0',
    backend='redis://redis:6379/0'
)

@celery.task
def run_solver_task(pre_assignment_requests, target_year, target_month,public_holidays):
    """Tugas yang akan dijalankan oleh Celery di latar belakang."""
    print(f"Menerima tugas untuk {target_month}/{target_year}...")
    result = run_simulation_for_api(pre_assignment_requests, target_year, target_month,public_holidays,num_runs=1)
    print("Tugas selesai.")
    return result