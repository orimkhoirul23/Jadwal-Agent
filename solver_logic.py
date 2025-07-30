import collections
from ortools.sat.python import cp_model
import random
import json
import time
import calendar
from datetime import datetime

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


def apply_employee_monthly_rules(model, shifts, employees_data, days, roles, non_work_statuses, employee_map, shift_map, max_work_days, forbidden_shifts_by_group, num_weekends,min_work_days,min_libur,code_to_nip_map):
    # Loop untuk setiap karyawan
    forbidden_shifts_for_400201 = ['SOC6', 'SOC2', 'SOCM']
    forbidden_indices_for_400201 = [shift_map.get(s) for s in forbidden_shifts_for_400201]

    target_nip = "400201"
    target_e_idx = -1
    for e_code, nip in code_to_nip_map.items():
        if nip == target_nip:
            if e_code in employee_map:
                target_e_idx = employee_map[e_code]
            break
    for e_name, group in employees_data:
        e_idx = employee_map[e_name]
        
        # --- Aturan Hari Kerja ---
        # Definisikan shift apa saja yang dihitung sebagai hari kerja
        work_indices = [shift_map[s] for s in roles if s in shift_map]
        
        # Hitung total hari kerja untuk karyawan ini
        total_work_days = sum(shifts[(e_idx, d, s_idx)] for d in days for s_idx in work_indices)
        
        # Aturan hari kerja maksimal (dari max_work_days)
        model.Add(total_work_days <= max_work_days)

        
        
        model.Add(total_work_days >= min_work_days)
        
        
        # --- Aturan Libur Wajib yang Fleksibel ---
        total_libur = sum(shifts[(e_idx, d, shift_map.get('Libur'))] for d in days)
        
        model.AddLinearConstraint(total_libur, min_libur, num_weekends)

        if e_idx == target_e_idx:
            for d in days:
                for s_idx in forbidden_indices_for_400201:
                    if s_idx is not None:
                        model.Add(shifts[e_idx, d, s_idx] == 0)
        
 
        # --- Aturan Spesifik per Grup ---
        if group == 'FB':
            if 'M' in shift_map:
                m_shift_idx = shift_map['M']
                total_m_shifts = sum(shifts[(e_idx, d, m_shift_idx)] for d in days)
                model.Add(total_m_shifts == 2)

        # --- Aturan larangan shift berdasarkan grup ---
        forbidden_roles_for_group = forbidden_shifts_by_group.get(group, [])
        if forbidden_roles_for_group:
            forbidden_indices = [shift_map[role] for role in forbidden_roles_for_group if role in shift_map]
            for d in days:
                for s_idx in forbidden_indices:
                    model.Add(shifts[e_idx, d, s_idx] == 0)


def apply_night_shift_rules(model, shifts, employees_data, days, female_employees, night_shifts, employee_map, shift_map):
    num_days = len(days)
    s_night_indices = [shift_map[s] for s in night_shifts if s in shift_map]
    
    # Jika tidak ada shift malam yang terdefinisi, hentikan fungsi
    if not s_night_indices:  
        return

    s_libur_idx = shift_map['Libur']
    # [BARU] Dapatkan index untuk shift 'Cuti'. Menggunakan .get() lebih aman.
    s_cuti_idx = shift_map.get('Cuti', -1)

    # 1. Definisikan semua variabel bantuan 'is_night' untuk setiap karyawan dan hari
    # Ini membuat model lebih bersih dan efisien
    is_night_vars = {}
    for e_idx, _ in enumerate(employees_data):
        for d in range(num_days):
            var = model.NewBoolVar(f'is_night_e{e_idx}_d{d}')
            night_shifts_on_day = [shifts[e_idx, d, s_idx] for s_idx in s_night_indices]
            
            # Hubungkan variabel 'var' dengan kondisi shift malam yang sebenarnya
            model.Add(sum(night_shifts_on_day) == 1).OnlyEnforceIf(var)
            model.Add(sum(night_shifts_on_day) == 0).OnlyEnforceIf(var.Not())
            is_night_vars[(e_idx, d)] = var

    # 2. Terapkan semua aturan untuk setiap karyawan
    for e_idx, (e_name, group) in enumerate(employees_data):
        
        # --- ATURAN LAMA (TETAP BERLAKU) ---
        # Aturan 1: Wajib Libur setelah rangkaian shift malam berhenti
        for d in range(num_days - 1):
            model.Add(shifts[e_idx, d + 1, s_libur_idx] == 1).OnlyEnforceIf([
                is_night_vars[(e_idx, d)],
                is_night_vars[(e_idx, d + 1)].Not()
            ])

        # Aturan 2: Karyawati tidak boleh 2x shift malam berturut-turut
        if e_name in female_employees:
            for d in range(num_days - 1):
                model.Add(is_night_vars[(e_idx, d)] + is_night_vars[(e_idx, d + 1)] <= 1)

        # --- [ATURAN BARU] ---
        # Aturan 3: Jika 2x shift malam, maka 2 hari berikutnya Libur/Cuti
        # Pastikan shift 'Cuti' terdefinisi di sistem Anda
        if s_cuti_idx != -1:
            # Loop berhenti di num_days - 3 untuk menghindari error out-of-index
            for d in range(num_days - 3):
                # Trigger: Jika karyawan kerja malam hari d DAN hari d+1
                trigger = [is_night_vars[(e_idx, d)], is_night_vars[(e_idx, d + 1)]]
                
                # Aksi 1: Hari d+2 harus Libur atau Cuti
                # shifts[..., Libur] + shifts[..., Cuti] == 1
                model.Add(shifts[e_idx, d + 2, s_libur_idx] + shifts[e_idx, d + 2, s_cuti_idx] == 1).OnlyEnforceIf(trigger)
                
                # Aksi 2: Hari d+3 harus Libur atau Cuti
                model.Add(shifts[e_idx, d + 3, s_libur_idx] + shifts[e_idx, d + 3, s_cuti_idx] == 1).OnlyEnforceIf(trigger)

def apply_additional_constraints(model, shifts, employees_data, days, day_types, employee_map, shift_map, male_employees, male_bandung_indices, night_shift_indices, public_holidays, target_year, target_month):
    """Menerapkan semua aturan tambahan yang kompleks."""
    
    # --- Definisi variabel yang relevan (didefinisikan sekali di awal) ---
    s_socm_idx = shift_map.get('SOCM')
    s_libur_idx = shift_map.get('Libur')
    s_cuti_idx = shift_map.get('Cuti')
    s_p6_idx = shift_map.get('P6')
    s_p7_idx = shift_map.get('P7')
    s_p8_idx = shift_map.get('P8')
    s_p9_idx = shift_map.get('P9')
    s_p10_idx = shift_map.get('P10')
    s_p11_idx = shift_map.get('P11')
    s_m_idx = shift_map.get('M')
    
    work_shift_indices = [idx for name, idx in shift_map.items() if name not in ['Libur', 'Cuti']]
    night_indices = [idx for name, idx in shift_map.items() if name in ['M', 'SOCM']]
    forbidden_p_indices = [shift_map.get(r) for r in ['P6', 'P7', 'P8', 'P9'] if r in shift_map]
    
    # Dapatkan daftar indeks karyawan spesifik dan grup
    e_b33_idx = employee_map.get('B33')
    e_b31_idx = employee_map.get('B31')
    e_b32_idx = employee_map.get('B32')
    jakarta_indices = [employee_map.get(e[0]) for e in employees_data if e[1] in ['MJ', 'CJ']]
    
    # Dapatkan daftar hari H-1 tanggal merah
    month_prefix = f"{target_year}-{target_month:02d}-"
    holidays_in_month = {h for h in public_holidays if h.startswith(month_prefix)}
    days_before_holiday = {int(h.split('-')[2]) - 2 for h in holidays_in_month if int(h.split('-')[2]) > 1}

    # =================================================================
    # ATURAN YANG BERLAKU PER INDIVIDU
    # =================================================================
    for e_idx, (e_name, group) in enumerate(employees_data):
        
        # Aturan 1: Maksimal 6 hari kerja berturut-turut
        if s_libur_idx is not None:
            for d in range(len(days) - 6):
                non_off_days_in_window = [shifts[e_idx, d + i, s_libur_idx].Not() for i in range(7)]
                model.Add(sum(non_off_days_in_window) <= 6)

        # Aturan 2: Melarang pola jadwal SOCM -> Libur -> P (untuk laki-laki)
        if e_name in male_employees and s_socm_idx is not None and forbidden_p_indices:
            for d in range(len(days) - 2):
                trigger = [shifts[e_idx, d, s_socm_idx], shifts[e_idx, d + 1, s_libur_idx]]
                model.Add(sum(shifts[e_idx, d + 2, s_idx] for s_idx in forbidden_p_indices) == 0).OnlyEnforceIf(trigger)
        
        # Aturan 3: Batasan Kerja Akhir Pekan per Grup
        weekend_work_days = sum(shifts[e_idx, d, s_idx] for d in days if day_types[d] in ['Sabtu', 'Minggu'] for s_idx in work_shift_indices)
        if group == 'FB': model.AddLinearConstraint(weekend_work_days, 3, 4)
        if group == 'MB': model.AddLinearConstraint(weekend_work_days, 4, 5)

        # Aturan 4: Shift Malam di H-1 Tanggal Merah Dihitung Kerja
        if d in days_before_holiday:
            trigger_night_before = model.NewBoolVar(f'night_before_holiday_e{e_idx}_d{d}')
            model.Add(sum(shifts[e_idx, d, s_idx] for s_idx in night_indices) == 1).OnlyEnforceIf(trigger_night_before)
            model.Add(sum(shifts[e_idx, d, s_idx] for s_idx in night_indices) == 0).OnlyEnforceIf(trigger_night_before.Not())
            model.Add(shifts[e_idx, d + 1, s_libur_idx] == 0).OnlyEnforceIf(trigger_night_before)

        # Aturan 5: Larangan Shift untuk Karyawan Spesifik
        if e_idx == e_b33_idx and s_p9_idx is not None:
            for d in days: model.Add(shifts[e_idx, d, s_p9_idx] == 0)
        if e_idx in [e_b31_idx, e_b32_idx] and s_p10_idx is not None:
            for d in days: model.Add(shifts[e_idx, d, s_p10_idx] == 0)

    # =================================================================
    # ATURAN YANG BERLAKU SECARA GLOBAL PER HARI
    # =================================================================
    
    # Aturan 6: Minimal 2 Laki-laki Bandung shift malam setiap hari
    if male_bandung_indices and night_shift_indices:
        for d in days:
            model.Add(sum(shifts[e_idx, d, s_idx] for e_idx in male_bandung_indices for s_idx in night_shift_indices) >= 2)

    # Aturan 7: Role P9 di akhir pekan hanya untuk Laki-laki Bandung
    if s_p9_idx is not None and male_bandung_indices:
        non_mb_indices = [i for i in range(len(employees_data)) if i not in male_bandung_indices]
        for d in days:
            if day_types[d] in ['Sabtu', 'Minggu']:
                for e_idx in non_mb_indices: model.Add(shifts[e_idx, d, s_p9_idx] == 0)

    # Aturan 8: Aturan Pola Kerja Karyawan Jakarta
    if jakarta_indices:
        for d in days:
            jakarta_off_count = sum(shifts[e_idx, d, s_libur_idx] + shifts[e_idx, d, s_cuti_idx] for e_idx in jakarta_indices)
            jakarta_p7_count = sum(shifts[e_idx, d, s_p7_idx] for e_idx in jakarta_indices)
            jakarta_p8_count = sum(shifts[e_idx, d, s_p8_idx] for e_idx in jakarta_indices)
            jakarta_p9_count = sum(shifts[e_idx, d, s_p9_idx] for e_idx in jakarta_indices)
            jakarta_p10_count = sum(shifts[e_idx, d, s_p10_idx] for e_idx in jakarta_indices)
            jakarta_p11_count = sum(shifts[e_idx, d, s_p11_idx] for e_idx in jakarta_indices)
            jakarta_m_count = sum(shifts[e_idx, d, s_m_idx] for e_idx in jakarta_indices)

            if day_types[d] == 'Weekday':
                trigger_1_off = model.NewBoolVar(f'jkt_1_off_d{d}')
                model.Add(jakarta_off_count == 1).OnlyEnforceIf(trigger_1_off)
                model.Add(jakarta_off_count != 1).OnlyEnforceIf(trigger_1_off.Not())
                model.Add(jakarta_p7_count == 1).OnlyEnforceIf(trigger_1_off)
                model.Add(jakarta_p9_count + jakarta_p10_count == 1).OnlyEnforceIf(trigger_1_off)

            elif day_types[d] in ['Sabtu', 'Minggu'] and len(jakarta_indices) == 3:
                trigger_2_off = model.NewBoolVar(f'jkt_2_off_d{d}')
                model.Add(jakarta_off_count == 2).OnlyEnforceIf(trigger_2_off)
                model.Add(jakarta_off_count != 2).OnlyEnforceIf(trigger_2_off.Not())
                model.Add(jakarta_p8_count == 1).OnlyEnforceIf(trigger_2_off)

            trigger_0_off = model.NewBoolVar(f'jkt_0_off_d{d}')
            model.Add(jakarta_off_count == 0).OnlyEnforceIf(trigger_0_off)
            model.Add(jakarta_off_count != 0).OnlyEnforceIf(trigger_0_off.Not())
            model.Add(jakarta_p11_count + jakarta_m_count <= 1).OnlyEnforceIf(trigger_0_off)
            model.Add(jakarta_p7_count == 1).OnlyEnforceIf(trigger_0_off)
            model.Add(jakarta_p9_count + jakarta_p10_count == 1).OnlyEnforceIf(trigger_0_off)
    

        

def apply_soft_constraints(model, shifts, employees_data, days, day_types, employee_map, shift_map):
    """Menerapkan semua soft constraints dan mengembalikan objective function."""
    
    num_days = len(days)
    total_score_vars = []

    # 1. Preferensi berdasarkan rentang jumlah shift per bulan
    preferences_with_range = [
        ('P6', 'FB', 2, 6, 10), ('P7', 'FB', 2, 6, 10), ('P8', 'FB', 2, 9, 10), 
        ('P9', 'FB', 3, 3, 10), ('SOC6', 'FB', 1, 3, 10), ('P6', 'MB', 0, 1, 10), 
        ('P7', 'MB', 0, 1, 10), ('P8', 'MB', 0, 3, 10), ('P9', 'MB', 0, 4, 10),
        ('P10', 'MB', 0, 5, 10), ('P11', 'MB', 1, 2, 10), ('S12', 'MB', 1, 9, 10),
        ('M', 'MB', 1, 3, 10), ('SOCM', 'MB', 1, 3, 10), ('SOC2', 'MB', 1, 3, 10),
        ('SOC6', 'MB', 0, 1, 10), ('P7', 'MJ', 1, 8, 10), ('P8', 'MJ', 1, 3, 10),
        ('P9', 'MJ', 1, 7, 10), ('P11', 'MJ', 1, 4, 10), ('M', 'MJ', 1, 2, 10),
        ('P7', 'CJ', 1, 8, 10), ('P8', 'CJ', 1, 3, 10), ('P10', 'CJ', 1, 9, 10),
        ('P11', 'CJ', 1, 4, 10), ('M', 'CJ', 1, 2, 10),
    ]
    for shift_name, group, min_val, max_val, weight in preferences_with_range:
        s_idx = shift_map.get(shift_name)
        if s_idx is None: continue
        group_indices = [employee_map[e[0]] for e in employees_data if e[1] == group]
        for e_idx in group_indices:
            total = sum(shifts[e_idx, d, s_idx] for d in days)
            in_range = model.NewBoolVar(f'in_range_{e_idx}_{shift_name}')
            model.Add(total >= min_val).OnlyEnforceIf(in_range)
            model.Add(total <= max_val).OnlyEnforceIf(in_range)
            total_score_vars.append(in_range * weight)

    # 2. Preferensi untuk memaksimalkan libur di akhir pekan
    s_libur_idx = shift_map.get('Libur')
    if s_libur_idx is not None:
        for e_idx in range(len(employees_data)):
            for d in days:
                if day_types[d] in ['Sabtu', 'Minggu']:
                    total_score_vars.append(shifts[e_idx, d, s_libur_idx]) 
    
    # 3. Penyeimbangan shift malam ('M' + 'SOCM') untuk Laki-laki Bandung ('MB')
    s_socm_idx = shift_map.get('SOCM')
    s_m_idx = shift_map.get('M')
    s_p8_idx = shift_map.get('P8')
    if s_socm_idx is not None and s_m_idx is not None:
        male_bandung_indices = [employee_map[e[0]] for e in employees_data if e[1] == 'MB']
        if male_bandung_indices:
            totals = [sum(shifts[e_idx, d, s_socm_idx] + shifts[e_idx, d, s_m_idx] for d in days) for e_idx in male_bandung_indices]
            min_shifts = model.NewIntVar(0, num_days, 'min_night_shifts')
            max_shifts = model.NewIntVar(0, num_days, 'max_night_shifts')
            model.AddMinEquality(min_shifts, totals)
            model.AddMaxEquality(max_shifts, totals)
            shift_range = model.NewIntVar(0, num_days, 'night_shift_range')
            model.Add(shift_range == max_shifts - min_shifts)
            total_score_vars.append(shift_range * -10)

    # 4. Penyeimbangan shift SOC2 vs S12 untuk setiap Laki-laki Bandung ('MB')
    s_soc2_idx = shift_map.get('SOC2')
    s_s12_idx = shift_map.get('S12')
    
    if s_soc2_idx is not None and s_s12_idx is not None:
        
        # a. Dapatkan daftar indeks karyawan yang termasuk grup 'MB'
        male_bandung_indices = [employee_map[e[0]] for e in employees_data if e[1] == 'MB']
        
        if male_bandung_indices:
            # b. Hitung total shift ('SOC2' + 'S12') untuk setiap karyawan dalam grup
            total_shifts_per_employee = []
            for e_idx in male_bandung_indices:
                total = model.NewIntVar(0, num_days, f'total_soc2_s12_e{e_idx}')
                model.Add(total == sum(shifts[e_idx, d, s_soc2_idx] + shifts[e_idx, d, s_s12_idx] for d in days))
                total_shifts_per_employee.append(total)

            # c. Buat variabel untuk nilai minimum dan maksimum dari total shift di atas
            min_val = model.NewIntVar(0, num_days, 'min_soc2_s12')
            max_val = model.NewIntVar(0, num_days, 'max_soc2_s12')
            model.AddMinEquality(min_val, total_shifts_per_employee)
            model.AddMaxEquality(max_val, total_shifts_per_employee)
            
            # d. Buat variabel untuk selisih (range) antara max dan min
            shift_range = model.NewIntVar(0, num_days, 'soc2_s12_range')
            model.Add(shift_range == max_val - min_val)
            
            # e. Tambahkan selisih ini sebagai "penalti" ke dalam skor total
            #    Bobot -10 akan mendorong solver untuk membuat selisih ini sekecil mungkin.
            total_score_vars.append(shift_range * -10)

    # 5. Penyeimbangan shift ('P6' + 'SOC6') untuk Karyawati Bandung ('FB')
    s_p6_idx = shift_map.get('P6')
    s_soc6_idx = shift_map.get('SOC6')
    if s_p6_idx is not None and s_soc6_idx is not None:
        female_bandung_indices = [employee_map[e[0]] for e in employees_data if e[1] == 'FB']
        if female_bandung_indices:
            totals = [sum(shifts[e_idx, d, s_p6_idx] + shifts[e_idx, d, s_soc6_idx] for d in days) for e_idx in female_bandung_indices]
            min_val = model.NewIntVar(0, num_days, 'min_p6_soc6')
            max_val = model.NewIntVar(0, num_days, 'max_p6_soc6')
            model.AddMinEquality(min_val, totals)
            model.AddMaxEquality(max_val, totals)
            shift_range = model.NewIntVar(0, num_days, 'p6_soc6_range')
            model.Add(shift_range == max_val - min_val)
            total_score_vars.append(shift_range * -10)
            
    s_socm_idx = shift_map.get('SOCM')
    s_m_idx = shift_map.get('M')
    if s_socm_idx is not None and s_m_idx is not None:
        male_bandung_indices = [employee_map[e[0]] for e in employees_data if e[1] == 'MB']
        if male_bandung_indices:
            # Hitung total shift malam untuk setiap karyawan dalam grup
            totals = [sum(shifts[e_idx, d, s_socm_idx] + shifts[e_idx, d, s_m_idx] for d in days) for e_idx in male_bandung_indices]
            
            # Cari nilai min dan max dari total tersebut
            min_shifts = model.NewIntVar(0, num_days, 'min_night_shifts_mb')
            max_shifts = model.NewIntVar(0, num_days, 'max_night_shifts_mb')
            model.AddMinEquality(min_shifts, totals)
            model.AddMaxEquality(max_shifts, totals)
            
            # Hitung selisihnya
            shift_range = model.NewIntVar(0, num_days, 'night_shift_range_mb')
            model.Add(shift_range == max_shifts - min_shifts)
            
            # Tambahkan selisih sebagai penalti ke skor total
            total_score_vars.append(shift_range * -10)
    if s_p8_idx is not None and s_libur_idx is not None:
        # a. Dapatkan daftar indeks karyawan Jakarta
        jakarta_indices = [employee_map[e[0]] for e in employees_data if e[1] in ['MJ', 'CJ']]
        
        if len(jakarta_indices) == 3:
            # b. Loop untuk setiap hari di akhir pekan
            for d in days:
                if day_types[d] in ['Sabtu', 'Minggu']:
                    
                    # c. Buat variabel boolean yang mewakili "aturan terpenuhi"
                    rule_met_on_day_d = model.NewBoolVar(f'jakarta_rule_met_d{d}')

                    # d. Definisikan kondisi-kondisi parsial
                    jakarta_p8_shifts = [shifts[e_idx, d, s_p8_idx] for e_idx in jakarta_indices]
                    jakarta_libur_shifts = [shifts[e_idx, d, s_libur_idx] for e_idx in jakarta_indices]
                    
                    # e. Hubungkan variabel utama dengan kondisi-kondisi tersebut
                    #    Aturan terpenuhi JIKA (total P8 == 1) DAN (total Libur == 2)
                    model.Add(sum(jakarta_p8_shifts) == 1).OnlyEnforceIf(rule_met_on_day_d)
                    model.Add(sum(jakarta_libur_shifts) == 2).OnlyEnforceIf(rule_met_on_day_d)

                    # f. Tambahkan skor bonus jika aturan ini terpenuhi
                    #    Bobot 15 berarti ini adalah preferensi yang cukup kuat.
                    total_score_vars.append(rule_met_on_day_d * 15)

    
 
    
   
    return sum(total_score_vars)

import calendar
import collections
from ortools.sat.python import cp_model
from datetime import date


def solve_one_instance(employees_data, target_year, target_month, pre_assignment_requests, public_holidays):
    """Fungsi ini menjalankan solver untuk SATU KALI proses."""
    

    code_to_nip_map = {
        "B1": "400192", "B2": "400091", "B3": "400193", "B4": "400210", "B5": "400204",
        "B6": "400211", "B7": "400092", "B8": "401136", "B9": "400202", "B10": "400216",
        "B11": "400213", "B12": "401144", "B13": "401145", "B14": "400299", "B15": "401108",
        "B16": "401138", "B17": "400218", "B18": "400206", "B19": "401524", "B20": "400198",
        "B21": "400196", "B22": "400217", "B23": "400087", "B24": "400093", "B25": "400209",
        "B26": "401133", "B27": "400090", "B28": "400189", "B29": "401107", "B30": "400201",
        "J1": "400212", "J2": "400203", "J3": "400190"
    }

    nip_to_code_map = {v: k for k, v in code_to_nip_map.items()}
    # --- BAGIAN SETUP (Tidak ada perubahan) ---
    employees = [e[0] for e in employees_data]
    employee_map = {name: i for i, name in enumerate(employees)}
    _, num_days = calendar.monthrange(target_year, target_month)
    days = range(num_days)
    
    
    holiday_dates_str = set(public_holidays)
    month_prefix = f"{target_year}-{target_month:02d}-"
    holidays_in_month = [h for h in holiday_dates_str if h.startswith(month_prefix)]
    
    # 2. Buat kamus day_types dengan logika baru
    day_types = {}
    for d in days:
        day_num = d + 1
        # Format tanggal hari ini menjadi 'YYYY-MM-DD'
        current_date_str = f"{target_year}-{target_month:02d}-{day_num:02d}"
        
        # Dapatkan hari dalam seminggu (Senin=0, ..., Sabtu=5, Minggu=6)
        day_of_week = calendar.weekday(target_year, target_month, day_num)

        # LOGIKA BARU:
        # - Jika tanggal ada di daftar tanggal merah dari parameter, anggap 'Minggu'.
        # - Jika tidak, baru periksa apakah itu Sabtu atau Minggu biasa.
        # - Jika bukan keduanya, maka itu 'Weekday'.
        if current_date_str in holiday_dates_str:
            day_types[d] = 'Minggu'
        elif day_of_week == 5: # Sabtu
            day_types[d] = 'Sabtu'
        elif day_of_week == 6: # Minggu
            day_types[d] = 'Minggu'
        else:
            day_types[d] = 'Weekday'
    
    #day_types = {d: ('Sabtu' if calendar.weekday(target_year, target_month, d+1) == 5 else 'Minggu' if calendar.weekday(target_year, target_month, d+1) == 6 else 'Weekday') for d in days}
    
    num_weekends = len([d for d, type in day_types.items() if type in ['Sabtu', 'Minggu']])
    max_work_days = num_days - num_weekends+len(holidays_in_month)
    print(f"Bulan {target_month}/{target_year}: Total hari={num_days}, Akhir Pekan={num_weekends}, Maks Hari Kerja={max_work_days}")
    min_work_days=num_days-num_weekends
    assignable_roles = ['P6', 'P7', 'P8', 'P9', 'P10', 'P11', 'S12', 'M', 'SOCM', 'SOC2', 'SOC6']
    count_as_work_roles=['P6', 'P7', 'P8', 'P9', 'P10', 'P11', 'S12', 'M', 'SOCM', 'SOC2', 'SOC6','Cuti']
    non_work_statuses = ['Libur', 'Cuti']
    all_shifts = assignable_roles + non_work_statuses
    shift_map = {name: i for i, name in enumerate(all_shifts)}
    night_shifts = ['M', 'SOCM']
    female_employees = [e[0] for e in employees_data if e[1] in ['FB', 'CJ']]
    male_employees=[e[0] for e in employees_data if e[1] in ['MB', 'MJ']]
    min_libur=num_weekends-len(holidays_in_month)
    
    # Data demand, quotas, dan pre-assignments
    demand = { 'P6': {'Weekday': 2, 'Sabtu': 2, 'Minggu': 2}, 'P7': {'Weekday': 3, 'Sabtu': 2, 'Minggu': 1}, 'P8': {'Weekday': (4, 5), 'Sabtu': 2, 'Minggu': 1}, 'P9': {'Weekday': (3, 5), 'Sabtu': 2, 'Minggu': 1}, 'P10': {'Weekday': (2, 4), 'Sabtu': 0, 'Minggu': 0}, 'P11': {'Weekday': 1, 'Sabtu': 1, 'Minggu': 1}, 'S12': {'Weekday': (5), 'Sabtu': 3, 'Minggu': 3}, 'M': {'Weekday': 2, 'Sabtu': 2, 'Minggu': 2}, 'SOCM': {'Weekday': 1, 'Sabtu': 1, 'Minggu': 1}, 'SOC2': {'Weekday': 1, 'Sabtu': 1, 'Minggu': 1}, 'SOC6': {'Weekday': 1, 'Sabtu': 1, 'Minggu': 1}, }
    # quotas = { 'MB': {'S12':(2,9),'P11':(0,2),'P6':(0,2),'P7':(0,2),'P8':(0,3),'SOC6':(0,2),'SOC2':(1,3),'M':(0,3),'SOCM':(0,3)}, 'FB': {'P11':(1,2),'P9':(2,10),'P8':(2,10),'P7':(2,10),'P6':(2,10),'P11':(0,0),'S12':(0,0),"SOC2":(0,0),"P10":(0,0),"SOCM":(0,0),"M":(0,2)}, 'MJ': {'P11':(1,4),'P7':(2,9),'P6':(0,0),'P10':(0,0),"SOC2":(0,0),"SOC6":(0,0),"SOCM":(0,0),"S12":(0,0),'P9':(2,9),"M":(0,2)}, 'CJ': {'P11':(1,4),'P10':(2,9),'P7':(2,9),'P6':(0,0),'P9':(0,0),"SOC2":(0,0),"SOC6":(0,0),"SOCM":(0,0),"S12":(0,0),"M":(0,2)}}
    
    forbidden_shifts_by_group = {
        'FB': ['P10', 'P11', 'S12', 'SOC2', 'SOCM'],
        'MJ': ['P6', 'P10', 'S12', 'SOC2', 'SOC6', 'SOCM'],
        'CJ': ['P6', 'P9', 'S12', 'SOC2', 'SOC6', 'SOCM']
    }

    
    pre_assignments = {}
    for req in pre_assignment_requests:
        real_nip, jenis, tanggal_str = str(req.get('nip')), req.get('jenis'), req.get('tanggal')
        if not (real_nip and jenis and tanggal_str): continue
        
        try:
            # Langkah 1: Terjemahkan NIP asli ke kode internal (e.g., "400192" -> "B1")
            internal_code = nip_to_code_map.get(real_nip)
            
            # Jika NIP dari frontend dikenali
            if internal_code:
                # Langkah 2: Dapatkan indeks karyawan dari kode internal
                e_idx = employee_map.get(internal_code)
                
                # Langkah 3: Proses tanggal dan tambahkan ke pre_assignments
                parsed_date = datetime.strptime(tanggal_str, '%Y-%m-%d')
                if parsed_date.year == target_year and parsed_date.month == target_month:
                    day_idx = parsed_date.day - 1
                    if e_idx is not None:
                        pre_assignments[(e_idx, day_idx)] = jenis
            else:
                print(f"Warning: NIP {real_nip} dari request tidak ditemukan dalam mapping.")

        except ValueError:
            print(f"Warning: Format tanggal tidak valid untuk request: {req}")
            continue
            
    # --- BAGIAN MODEL & CONSTRAINTS (Tidak ada perubahan) ---
    model = cp_model.CpModel()
    shifts = { (employee_map[e], d, shift_map[s]): model.NewBoolVar(f's_{e}_{d}_{s}') for e in employees for d in days for s in all_shifts }
    # Di dalam solve_one_instance, setelah membuat variabel shifts

    s_cuti_idx = shift_map['Cuti']
    male_bandung_indices = [employee_map[e[0]] for e in employees_data if e[1] == 'MB']
    
    # Definisikan daftar index untuk shift malam
    night_shift_indices = [shift_map[s] for s in night_shifts if s in shift_map]

# Dapatkan daftar semua permintaan cuti yang sudah diproses
    requested_cuti_days = {(e, d) for (e, d), s in pre_assignments.items() if s == 'Cuti'}
    
    for e_idx in range(len(employees)):
      for d in days:
        # Jika pasangan (karyawan, hari) ini tidak ada dalam daftar request cuti
        if (e_idx, d) not in requested_cuti_days:
            # Maka karyawan ini tidak boleh mengambil shift Cuti pada hari ini
            model.Add(shifts[e_idx, d, s_cuti_idx] == 0)
    apply_pre_assignments(model, shifts, pre_assignments, shift_map)
    apply_core_constraints(model, shifts, employees, days, demand, day_types, shift_map)
    apply_employee_monthly_rules(model, shifts, employees_data, days, assignable_roles, non_work_statuses, employee_map, shift_map, max_work_days, forbidden_shifts_by_group, num_weekends,min_work_days,min_libur,code_to_nip_map)
    apply_night_shift_rules(model, shifts, employees_data, days, female_employees, night_shifts, employee_map, shift_map)
    apply_additional_constraints(model, shifts, employees_data, days, day_types, employee_map, shift_map, male_employees, male_bandung_indices, night_shift_indices,public_holidays,target_year,target_month)
    
    
    objective_function = apply_soft_constraints(model, shifts, employees_data, days, day_types, employee_map, shift_map)
    
    # Perintahkan solver untuk memaksimalkan hasil dari fungsi tersebut
   
    model.Maximize(objective_function)


    

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 300.0
    solver.parameters.log_search_progress = False
    status = solver.Solve(model)
    
    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        temp_schedule = collections.defaultdict(list)
        daily_summary = collections.defaultdict(lambda: collections.defaultdict(int))
        
        for e_code in employees:
            e_idx = employee_map[e_code]
            for d in days:
                for s_name in all_shifts:
                    s_idx = shift_map[s_name]
                    if solver.Value(shifts[(e_idx, d, s_idx)]):
                        day_str = str(d + 1)
                        temp_schedule[e_code].append(s_name)
                        daily_summary[day_str][s_name] += 1
                        break
        
        final_schedule_with_nip = {}
        for code, daily_schedule_list in temp_schedule.items():
            real_nip = code_to_nip_map.get(code, code)
            final_schedule_with_nip[real_nip] = daily_schedule_list

        return {
            "schedule": final_schedule_with_nip,
            "summary": daily_summary
        }
    else:
        return None


def run_simulation_for_api(base_requests, target_year, target_month,public_holidays,num_runs=10):
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
            employees_data=[ (f'B{i}', 'FB') for i in range(1, 12) ] + [(f'B{i}', 'MB') for i in range(12, 31)] + [('J1', 'MJ'), ('J2', 'MJ')] + [('J3', 'CJ')],
            target_year=target_year,
            target_month=target_month,
            pre_assignment_requests=current_requests,
            public_holidays=public_holidays
        )
        
        # Jika hasilnya bukan None (artinya sukses), tambahkan ke daftar
        if schedule_result:
            successful_schedules.append({
                "simulation_run": i+1,
                # [MODIFIKASI] Langsung satukan schedule dan summary di sini
                "result": schedule_result
            })
        else:
            print(f"Run #{i+1}: ❌ Tidak ada solusi.")
            
    return successful_schedules



# =================================================================================
# TITIK MASUK UTAMA PROGRAM (CONTOH PENGGUNAAN)
# =================================================================================
if __name__ == '__main__':
    import pandas as pd
    # Definisikan parameter di sini agar mudah diakses kembali
    target_year_num = 2025
    target_month_num = 8 # Ganti bulan sesuai kebutuhan
    
    contoh_requests = [
     {
      "nip": 400217,
      "jenis": "Cuti",
      "tanggal": "2025-08-18"
    },
    {
      "nip": 400198,
      "jenis": "Libur",
      "tanggal": "2025-08-02"
    },
    {
      "nip": 400198,
      "jenis": "Libur",
      "tanggal": "2025-08-03"
    },
    {
      "nip": 400198,
      "jenis": "Libur",
      "tanggal": "2025-08-31"
    },
    {
      "nip": 400213,
      "jenis": "Libur",
      "tanggal": "2025-08-07"
    },
    {
      "nip": 400213,
      "jenis": "Libur",
      "tanggal": "2025-08-15"
    },
    {
      "nip": 400213,
      "jenis": "Libur",
      "tanggal": "2025-08-08"
    },
    {
      "nip": 400090,
      "jenis": "Libur",
      "tanggal": "2025-08-09"
    },
    {
      "nip": 400090,
      "jenis": "Libur",
      "tanggal": "2025-08-30"
    },
    {
      "nip": 401107,
      "jenis": "Libur",
      "tanggal": "2025-08-09"
    },
    {
      "nip": 401107,
      "jenis": "Libur",
      "tanggal": "2025-08-10"
    },
    {
      "nip": 401107,
      "jenis": "Libur",
      "tanggal": "2025-08-16"
    },
    {
      "nip": 401107,
      "jenis": "Cuti",
      "tanggal": "2025-08-06"
    },
    {
      "nip": 401107,
      "jenis": "Cuti",
      "tanggal": "2025-08-07"
    },
    {
      "nip": 401107,
      "jenis": "Cuti",
      "tanggal": "2025-08-08"
    },
    {
      "nip": 401107,
      "jenis": "Cuti",
      "tanggal": "2025-08-11"
    },
    {
      "nip": 401107,
      "jenis": "Cuti",
      "tanggal": "2025-08-12"
    },
    {
      "nip": 401107,
      "jenis": "Cuti",
      "tanggal": "2025-08-13"
    },
    {
      "nip": 401107,
      "jenis": "Cuti",
      "tanggal": "2025-08-14"
    },
    {
      "nip": 401107,
      "jenis": "Cuti",
      "tanggal": "2025-08-15"
    },
    {
      "nip": 400202,
      "jenis": "Libur",
      "tanggal": "2025-08-15"
    },
    {
      "nip": 400202,
      "jenis": "Libur",
      "tanggal": "2025-08-22"
    },
    {
      "nip": 400202,
      "jenis": "Cuti",
      "tanggal": "2025-08-29"
    },
    {
      "nip": 400189,
      "jenis": "Libur",
      "tanggal": "2025-08-09"
    },
    {
      "nip": 400189,
      "jenis": "Libur",
      "tanggal": "2025-08-23"
    },
    {
      "nip": 400189,
      "jenis": "Cuti",
      "tanggal": "2025-08-07"
    },
    {
      "nip": 400189,
      "jenis": "Libur",
      "tanggal": "2025-08-24"
    },
    {
      "nip": 400209,
      "jenis": "Libur",
      "tanggal": "2025-08-16"
    },
    {
      "nip": 400209,
      "jenis": "Libur",
      "tanggal": "2025-08-23"
    },
    {
      "nip": 400209,
      "jenis": "Libur",
      "tanggal": "2025-08-24"
    },
    {
      "nip": 401136,
      "jenis": "Libur",
      "tanggal": "2025-08-03"
    },
    {
      "nip": 401136,
      "jenis": "Libur",
      "tanggal": "2025-08-28"
    },
    {
      "nip": 401136,
      "jenis": "Cuti",
      "tanggal": "2025-08-14"
    },
    {
      "nip": 401136,
      "jenis": "Cuti",
      "tanggal": "2025-08-15"
    },
    {
      "nip": 401524,
      "jenis": "Libur",
      "tanggal": "2025-08-02"
    },
    {
      "nip": 401524,
      "jenis": "Libur",
      "tanggal": "2025-08-03"
    },
    {
      "nip": 401524,
      "jenis": "Cuti",
      "tanggal": "2025-08-15"
    },
    {
      "nip": 401524,
      "jenis": "Cuti",
      "tanggal": "2025-08-18"
    },
    {
      "nip": 400092,
      "jenis": "Libur",
      "tanggal": "2025-08-22"
    },
    {
      "nip": 400092,
      "jenis": "Libur",
      "tanggal": "2025-08-29"
    },
    {
      "nip": 400204,
      "jenis": "Libur",
      "tanggal": "2025-08-18"
    },
    {
      "nip": 400204,
      "jenis": "Libur",
      "tanggal": "2025-08-31"
    },
    {
      "nip": 400201,
      "jenis": "Libur",
      "tanggal": "2025-08-03"
    },
    {
      "nip": 400201,
      "jenis": "Libur",
      "tanggal": "2025-08-13"
    },
    {
      "nip": 400201,
      "jenis": "Libur",
      "tanggal": "2025-08-14"
    },
    {
      "nip": 400210,
      "jenis": "Libur",
      "tanggal": "2025-08-05"
    },
    {
      "nip": 400210,
      "jenis": "Libur",
      "tanggal": "2025-08-14"
    },
    {
      "nip": 400210,
      "jenis": "Libur",
      "tanggal": "2025-08-28"
    },
    {
      "nip": 400216,
      "jenis": "Libur",
      "tanggal": "2025-08-02"
    },
    {
      "nip": 400216,
      "jenis": "Libur",
      "tanggal": "2025-08-03"
    },
    {
      "nip": 400216,
      "jenis": "Libur",
      "tanggal": "2025-08-31"
    },
    {
      "nip": 400091,
      "jenis": "Libur",
      "tanggal": "2025-08-06"
    },
    {
      "nip": 400091,
      "jenis": "Libur",
      "tanggal": "2025-08-28"
    },
    {
      "nip": 400212,
      "jenis": "Libur",
      "tanggal": "2025-08-02"
    },
    {
      "nip": 400212,
      "jenis": "Libur",
      "tanggal": "2025-08-03"
    },
    {
      "nip": 400212,
      "jenis": "Libur",
      "tanggal": "2025-08-04"
    },
    {
      "nip": 400193,
      "jenis": "Libur",
      "tanggal": "2025-08-11"
    },
    {
      "nip": 400193,
      "jenis": "Libur",
      "tanggal": "2025-08-18"
    },
    {
      "nip": 400093,
      "jenis": "Libur",
      "tanggal": "2025-08-13"
    },
    {
      "nip": 400093,
      "jenis": "Libur",
      "tanggal": "2025-08-18"
    },
    {
      "nip": 400093,
      "jenis": "Libur",
      "tanggal": "2025-08-29"
    },
    {
      "nip": 400093,
      "jenis": "Cuti",
      "tanggal": "2025-08-28"
    },
    {
      "nip": 401138,
      "jenis": "Libur",
      "tanggal": "2025-08-02"
    },
    {
      "nip": 401138,
      "jenis": "Libur",
      "tanggal": "2025-08-03"
    },
    {
      "nip": 401138,
      "jenis": "Libur",
      "tanggal": "2025-08-16"
    },
    {
      "nip": 401144,
      "jenis": "Libur",
      "tanggal": "2025-08-02"
    },
    {
      "nip": 401144,
      "jenis": "Libur",
      "tanggal": "2025-08-03"
    },
    {
      "nip": 400211,
      "jenis": "Libur",
      "tanggal": "2025-08-29"
    },
    {
      "nip": 400211,
      "jenis": "Libur",
      "tanggal": "2025-08-30"
    },
    {
      "nip": 400211,
      "jenis": "Libur",
      "tanggal": "2025-08-31"
    },
    {
      "nip": 400211,
      "jenis": "Cuti",
      "tanggal": "2025-08-15"
    },
    {
      "nip": 400206,
      "jenis": "Libur",
      "tanggal": "2025-08-03"
    },
    {
      "nip": 400206,
      "jenis": "Libur",
      "tanggal": "2025-08-24"
    },
    {
      "nip": 400206,
      "jenis": "Libur",
      "tanggal": "2025-08-25"
    },
    {
      "nip": 400087,
      "jenis": "Libur",
      "tanggal": "2025-08-02"
    },
    {
      "nip": 400087,
      "jenis": "Libur",
      "tanggal": "2025-08-09"
    },
    {
      "nip": 400087,
      "jenis": "Libur",
      "tanggal": "2025-08-10"
    },
    {
      "nip": 400087,
      "jenis": "Cuti",
      "tanggal": "2025-08-07"
    },
    {
      "nip": 401108,
      "jenis": "Libur",
      "tanggal": "2025-08-09"
    },
    {
      "nip": 401108,
      "jenis": "Libur",
      "tanggal": "2025-08-10"
    },
    {
      "nip": 400203,
      "jenis": "Libur",
      "tanggal": "2025-08-27"
    },
    {
      "nip": 400203,
      "jenis": "Libur",
      "tanggal": "2025-08-28"
    },
    {
      "nip": 400203,
      "jenis": "Libur",
      "tanggal": "2025-08-29"
    },
    {
      "nip": 400192,
      "jenis": "Libur",
      "tanggal": "2025-08-24"
    },
    {
      "nip": 400192,
      "jenis": "Libur",
      "tanggal": "2025-08-25"
    },
    {
      "nip": 400192,
      "jenis": "Libur",
      "tanggal": "2025-08-04"
    },
    {
      "nip": 400196,
      "jenis": "Libur",
      "tanggal": "2025-08-01"
    },
    {
      "nip": 400217,
      "jenis": "Libur",
      "tanggal": "2025-08-24"
    },
    {
      "nip": 400217,
      "jenis": "Libur",
      "tanggal": "2025-08-31"
    },
    {
      "nip": 400090,
      "jenis": "Libur",
      "tanggal": "2025-08-01"
    },
    {
      "nip": 400190,
      "jenis": "Libur",
      "tanggal": "2025-08-08"
    },
    {
      "nip": 400190,
      "jenis": "Libur",
      "tanggal": "2025-08-09"
    },
    {
      "nip": 400190,
      "jenis": "Libur",
      "tanggal": "2025-08-10"
    },
    {
      "nip": 401145,
      "jenis": "Libur",
      "tanggal": "2025-08-09"
    },
    {
      "nip": 401145,
      "jenis": "Libur",
      "tanggal": "2025-08-10"
    },
    {
      "nip": 400299,
      "jenis": "Libur",
      "tanggal": "2025-08-09"
    },
    {
      "nip": 400299,
      "jenis": "Libur",
      "tanggal": "2025-08-10"
    },
    {
      "nip": 400217,
      "jenis": "Libur",
      "tanggal": "2025-08-01"
    },
    {
      "nip": 400209,
      "jenis": "Libur",
      "tanggal": "2025-08-01"
    },
    {
      "nip": 400189,
      "jenis": "Libur",
      "tanggal": "2025-08-01"
    }
    ]
    
    daftar_tanggal_merah = [
        "2025-08-17"  # Contoh: Hari Kemerdekaan
       
    ]
    
    list_of_valid_schedules = run_simulation_for_api(
        base_requests=contoh_requests,
        target_year=target_year_num,
        target_month=target_month_num,
        public_holidays=daftar_tanggal_merah, # <-- Kirim daftar sebagai argumen
        num_runs=1)
    
    
    print("\n" + "="*80)
    print(f"--- SIMULASI SELESAI: {len(list_of_valid_schedules)} JADWAL VALID DITEMUKAN ---")
    print("="*80)
    
    # --- PROSES PEMBUATAN FILE OUTPUT ---

    # 1. Simpan hasil lengkap ke file JSON (tidak berubah)
    output_filename_json = 'hasil_simulasi_jadwal.json'
    try:
        with open(output_filename_json, 'w', encoding='utf-8') as f:
            json.dump(list_of_valid_schedules, f, ensure_ascii=False, indent=4)
        print(f"✅ Hasil simulasi lengkap berhasil disimpan ke file: {output_filename_json}")
    except Exception as e:
        print(f"❌ Gagal menyimpan file JSON: {e}")

    # 2. Simpan tabel jadwal utama ke file Excel
    if list_of_valid_schedules:
        output_filename_excel = 'hasil_jadwal.xlsx'
        try:
            schedule_data = list_of_valid_schedules[0]['result']['schedule']
            df = pd.DataFrame.from_dict(schedule_data, orient='index')
            df.columns = [i + 1 for i in df.columns]
            
            # [PERBAIKAN] Dapatkan nama bulan dari library calendar
            month_name = calendar.month_name[target_month_num]
            
            # [PERBAIKAN] Gunakan nama bulan yang sudah didapat untuk nama sheet
            df.to_excel(output_filename_excel, sheet_name=f'Jadwal Bulan {month_name}')

            print(f"✅ Tabel jadwal berhasil disimpan ke file: {output_filename_excel}")

        except Exception as e:
            print(f"❌ Gagal menyimpan file Excel: {e}")
    elif not list_of_valid_schedules:
        print("Tidak ada jadwal yang valid untuk disimpan ke Excel.")