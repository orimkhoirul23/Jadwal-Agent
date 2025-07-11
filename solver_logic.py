import collections
from ortools.sat.python import cp_model
import random
import json
import time
import calendar

# =================================================================================
# FUNGSI-FUNGSI ATURAN (CONSTRAINTS) - Tidak ada perubahan
# =================================================================================
def apply_pre_assignments(model, shifts, pre_assignments, shift_map):
    for (e_idx, d), shift_name in pre_assignments.items():
        s_idx = shift_map[shift_name]
        model.Add(shifts[e_idx, d, s_idx] == 1)

def apply_core_constraints(model, shifts, employees, days, demand, day_types, shift_map):
    num_employees = len(employees)
    for e_idx in range(num_employees):
        for d in days:
            model.AddExactlyOne(shifts[(e_idx, d, s_idx)] for s_idx in range(len(shift_map)))
    for d in days:
        day_type = day_types[d]
        for role_name, requirements in demand.items():
            if role_name in shift_map:
                required_count = requirements.get(day_type, 0)
                s_idx = shift_map[role_name]
                if isinstance(required_count, tuple):
                    min_req, max_req = required_count
                    model.AddLinearConstraint(sum(shifts[e_idx, d, s_idx] for e_idx in range(num_employees)), min_req, max_req)
                elif required_count > 0:
                    model.Add(sum(shifts[e_idx, d, s_idx] for e_idx in range(num_employees)) == required_count)

def apply_employee_monthly_rules(model, shifts, employees_data, days, roles, non_work_statuses, quotas, employee_map, shift_map):
    for e_name, group in employees_data:
        e_idx = employee_map[e_name]
        group_quotas = quotas.get(group, {})
        for role_name, (min_val, max_val) in group_quotas.items():
            if role_name in shift_map:
                s_idx = shift_map[role_name]
                model.AddLinearConstraint(sum(shifts[(e_idx, d, s_idx)] for d in days), min_val, max_val)
        work_and_leave_indices = [shift_map[s] for s in roles] + [shift_map['Cuti']]
        model.Add(sum(shifts[(e_idx, d, s_idx)] for d in days for s_idx in work_and_leave_indices) <= 23)
        model.Add(sum(shifts[(e_idx, d, shift_map['Libur'])] for d in days) == 8)

def apply_night_shift_rules(model, shifts, employees_data, days, female_employees, night_shifts, employee_map, shift_map):
    num_days = len(days)
    s_night_indices = [shift_map[s] for s in night_shifts if s in shift_map]
    if not s_night_indices: return
    s_libur_idx = shift_map['Libur']
    for e_idx, (e_name, group) in enumerate(employees_data):
        for d in range(num_days - 1):
            is_night_d = model.NewBoolVar(f'is_night_e{e_idx}_d{d}')
            model.Add(sum(shifts[e_idx, d, s_idx] for s_idx in s_night_indices) >= 1).OnlyEnforceIf(is_night_d)
            model.Add(sum(shifts[e_idx, d, s_idx] for s_idx in s_night_indices) == 0).OnlyEnforceIf(is_night_d.Not())
            is_night_d1 = model.NewBoolVar(f'is_night_e{e_idx}_d{d+1}')
            model.Add(sum(shifts[e_idx, d+1, s_idx] for s_idx in s_night_indices) >= 1).OnlyEnforceIf(is_night_d1)
            model.Add(sum(shifts[e_idx, d+1, s_idx] for s_idx in s_night_indices) == 0).OnlyEnforceIf(is_night_d1.Not())
            model.Add(shifts[e_idx, d + 1, s_libur_idx] == 1).OnlyEnforceIf([is_night_d, is_night_d1.Not()])
        if e_name in female_employees:
            for d in range(num_days - 1):
                model.Add(sum(shifts[e_idx, d, s_idx] for s_idx in s_night_indices) + sum(shifts[e_idx, d + 1, s_idx] for s_idx in s_night_indices) <= 1)

def apply_additional_constraints(model, shifts, employees, days, employee_map, shift_map):
    penalties = []
    forbidden_roles = ['P6', 'P7', 'P8', 'P9']
    forbidden_indices = [shift_map[r] for r in forbidden_roles if r in shift_map]
    s_socm_idx = shift_map.get('SOCM')
    s_libur_idx = shift_map.get('Libur')
    for e_idx, e_name in enumerate(employees):
        for d in range(len(days) - 6):
            non_off_days_in_window = [shifts[e_idx, d + i, s_libur_idx].Not() for i in range(7)]
            model.Add(sum(non_off_days_in_window) <= 6)
        if s_socm_idx is not None and forbidden_indices:
            for d in range(len(days) - 2):
                is_socm_d, is_libur_d1 = shifts[e_idx, d, s_socm_idx], shifts[e_idx, d + 1, s_libur_idx]
                is_forbidden_shift_d2 = model.NewBoolVar(f'is_forbidden_e{e_idx}_d{d+2}')
                model.Add(sum(shifts[e_idx, d + 2, s_idx] for s_idx in forbidden_indices) >= 1).OnlyEnforceIf(is_forbidden_shift_d2)
                model.Add(sum(shifts[e_idx, d + 2, s_idx] for s_idx in forbidden_indices) == 0).OnlyEnforceIf(is_forbidden_shift_d2.Not())
                penalty = model.NewBoolVar(f'penalty_e{e_idx}_d{d}')
                model.AddBoolAnd([is_socm_d, is_libur_d1, is_forbidden_shift_d2]).OnlyEnforceIf(penalty)
                penalties.append(penalty)
    if penalties:
        model.Minimize(sum(penalties))


# =================================================================================
# FUNGSI UTAMA & SIMULASI
# =================================================================================

def solve_one_instance(employees_data, target_year, target_month, pre_assignment_requests):
    """Fungsi ini menjalankan solver untuk SATU KALI proses."""
    # (Fungsi ini berisi semua logika yang sebelumnya ada di solve_employee_scheduling)
    employees = [e[0] for e in employees_data]
    employee_map = {name: i for i, name in enumerate(employees)}
    _, num_days = calendar.monthrange(target_year, target_month)
    days = range(num_days)
    day_types = {d: ('Sabtu' if calendar.weekday(target_year, target_month, d+1) == 5 else 'Minggu' if calendar.weekday(target_year, target_month, d+1) == 6 else 'Weekday') for d in days}
    assignable_roles = ['P6', 'P7', 'P8', 'P9', 'P10', 'P11', 'S12', 'M', 'SOCM', 'SOC2', 'SOC6']
    non_work_statuses = ['Libur', 'Cuti']
    all_shifts = assignable_roles + non_work_statuses
    shift_map = {name: i for i, name in enumerate(all_shifts)}
    night_shifts = ['M', 'SOCM']
    female_employees = [e[0] for e in employees_data if e[1] in ['FB', 'CJ']]
    demand = { 'P6': {'Weekday': 2, 'Sabtu': 2, 'Minggu': 2}, 'P7': {'Weekday': 3, 'Sabtu': 2, 'Minggu': 1}, 'P8': {'Weekday': (4, 5), 'Sabtu': 2, 'Minggu': 1}, 'P9': {'Weekday': (3, 5), 'Sabtu': 2, 'Minggu': 1}, 'P10': {'Weekday': (2, 4), 'Sabtu': 0, 'Minggu': 0}, 'P11': {'Weekday': 1, 'Sabtu': 1, 'Minggu': 1}, 'S12': {'Weekday': 5, 'Sabtu': 3, 'Minggu': 3}, 'M': {'Weekday': 2, 'Sabtu': 2, 'Minggu': 2}, 'SOCM': {'Weekday': 1, 'Sabtu': 1, 'Minggu': 1}, 'SOC2': {'Weekday': 1, 'Sabtu': 1, 'Minggu': 1}, 'SOC6': {'Weekday': 1, 'Sabtu': 1, 'Minggu': 1}, }
    quotas = { 'MB': {'P6':(0,1),'P7':(1,1),'P8':(0,2),'P9':(0,5),'P10':(1,5),'P11':(1,1),'S12':(6,8),'SOC2':(1,2),'SOC6':(0,1),'SOCM':(1,2),'M':(1,2)}, 'FB': {'P6':(4,5),'P7':(3,4),'P8':(6,8),'P9':(3,3),'SOC6':(2,2),'M':(2,2)}, 'MJ': {'P7':(7,8),'P8':(2,3),'P9':(7,7),'P11':(3,4),'M':(2,2)}, 'CJ': {'P7':(7,7),'P8':(2,2),'P10':(9,9),'P11':(3,3),'M':(2,2)}, }

    from datetime import datetime
    pre_assignments = {}
    for req in pre_assignment_requests:
        nip, jenis, tanggal_str = req.get('nip'), req.get('jenis'), req.get('tanggal')
        if not (nip and jenis and tanggal_str): continue
        parsed_date = datetime.fromisoformat(tanggal_str.replace('Z', '+00:00'))
        if parsed_date.year == target_year and parsed_date.month == target_month:
            e_idx = employee_map.get(str(nip))
            day_idx = parsed_date.day - 1
            if e_idx is not None:
                pre_assignments[(e_idx, day_idx)] = jenis

    model = cp_model.CpModel()
    shifts = { (employee_map[e], d, shift_map[s]): model.NewBoolVar(f's_{e}_{d}_{s}') for e in employees for d in days for s in all_shifts }
    apply_pre_assignments(model, shifts, pre_assignments, shift_map)
    apply_core_constraints(model, shifts, employees, days, demand, day_types, shift_map)
    apply_employee_monthly_rules(model, shifts, employees_data, days, assignable_roles, non_work_statuses, quotas, employee_map, shift_map)
    apply_night_shift_rules(model, shifts, employees_data, days, female_employees, night_shifts, employee_map, shift_map)
    apply_additional_constraints(model, shifts, employees, days, employee_map, shift_map)
    
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 300.0
    solver.parameters.log_search_progress = False
    status = solver.Solve(model)
    
    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        schedule = collections.defaultdict(dict)
        for e_name in employees:
            for d in days:
                for s_name in all_shifts:
                    if solver.Value(shifts[(employee_map[e_name], d, shift_map[s_name])]):
                        schedule[e_name][str(d+1)] = s_name
                        break
        return schedule
    else:
        return None

def run_simulation_for_api(base_requests, target_year, target_month, num_runs=10):
    """Menjalankan simulasi dan mengembalikan list berisi semua jadwal yang sukses."""
    print(f"Memulai simulasi untuk {num_runs} kali...")
    successful_schedules = []
    
    for i in range(num_runs):
        print(f"--- Menjalankan Simulasi #{i+1}/{num_runs} ---")
        
        # Di dunia nyata, Anda mungkin ingin menambahkan sedikit variasi acak
        # pada request di setiap run, tapi untuk sekarang kita gunakan request yang sama.
        current_requests = base_requests
        
        # Panggil solver
        schedule_result = solve_one_instance(
            employees_data=[ (f'B{i}', 'FB') for i in range(1, 11) ] + [(f'B{i}', 'MB') for i in range(11, 31)] + [('J1', 'MJ'), ('J2', 'MJ')] + [('J3', 'CJ')],
            target_year=target_year,
            target_month=target_month,
            pre_assignment_requests=current_requests
        )
        
        # Jika hasilnya bukan None (artinya sukses), tambahkan ke daftar
        if schedule_result:
            print(f"Run #{i+1}: ✅ Solusi ditemukan.")
            successful_schedules.append({
                "simulation_run": i+1,
                "schedule": schedule_result
            })
        else:
            print(f"Run #{i+1}: ❌ Tidak ada solusi.")
            
    return successful_schedules

# =================================================================================
# TITIK MASUK UTAMA PROGRAM (CONTOH PENGGUNAAN)
# =================================================================================
if __name__ == '__main__':
    # Ini adalah contoh data request yang akan dikirim oleh API Anda
    contoh_requests = [
        {"nip": "B1", "jenis": "Libur", "tanggal": "2025-07-10T00:00:00.000Z"},
        {"nip": "B2", "jenis": "Libur", "tanggal": "2025-07-11T00:00:00.000Z"},
        {"nip": "J1", "jenis": "Cuti", "tanggal": "2025-07-22T00:00:00.000Z"}
        # Tambahkan 3 request libur per pegawai dan 10-12 cuti di sini
    ]
    
    # Panggil fungsi simulasi
    list_of_valid_schedules = run_simulation_for_api(
        base_requests=contoh_requests,
        target_year=2025,
        target_month=7,
        num_runs=10
    )
    
    print("\n" + "="*50)
    print(f"--- SIMULASI SELESAI: {len(list_of_valid_schedules)} JADWAL VALID DITEMUKAN ---")
    print("="*50)
    
    # Cetak hasil akhir dalam format JSON
    # Di aplikasi API, ini yang akan Anda kirim sebagai response
    print(json.dumps(list_of_valid_schedules, indent=2))