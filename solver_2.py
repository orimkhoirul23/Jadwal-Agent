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
    
    # --- Persiapan untuk aturan spesifik (dilakukan sekali di luar loop) ---
    forbidden_shifts_for_400201 = ['SOC6', 'SOC2', 'SOCM','M']
    forbidden_indices_for_400201 = [shift_map.get(s) for s in forbidden_shifts_for_400201]

    target_nip = "400201"
    target_e_idx = -1
    for e_code, nip in code_to_nip_map.items():
        if nip == target_nip:
            if e_code in employee_map:
                target_e_idx = employee_map[e_code]
            break

    # --- Loop utama per karyawan ---
    for e_idx, (e_name, group) in enumerate(employees_data):
        
        # --- Aturan Hari Kerja ---
        work_indices = [shift_map[s] for s in roles if s in shift_map]
        total_work_days = sum(shifts[(e_idx, d, s_idx)] for d in days for s_idx in work_indices)
        
        # Aturan hari kerja maksimal (dari max_work_days)
        model.Add(total_work_days <= max_work_days)
        # Aturan hari kerja minimal
        model.Add(total_work_days >= min_work_days)
        
        # --- Aturan Libur Wajib yang Fleksibel ---
        total_libur = sum(shifts[(e_idx, d, shift_map.get('Libur'))] for d in days)
        model.AddLinearConstraint(total_libur, min_libur, num_weekends)

        # --- Aturan Larangan Shift untuk NIP Spesifik ---
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
                    if s_idx is not None:
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
    """
    Menerapkan semua aturan penjadwalan tambahan yang kompleks.

    Kode ini telah disatukan ke dalam struktur loop yang lebih efisien.
    """
    
    # --- Definisi Indeks Shift dan Grup (dilakukan sekali di awal) ---
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
    
    # Kelompokkan indeks shift untuk memudahkan penggunaan
    work_shift_indices = [idx for name, idx in shift_map.items() if name not in ['Libur']]
    night_indices = [idx for name, idx in shift_map.items() if name in ['M', 'SOCM']]
    forbidden_p_indices = [shift_map.get(r) for r in ['P6', 'P7', 'P8', 'P9'] if r in shift_map]
    
    # Dapatkan indeks karyawan dan grup spesifik
    e_b33_idx = employee_map.get('B33')
    e_b31_idx = employee_map.get('B31')
    e_b32_idx = employee_map.get('B32')
    jakarta_indices = [employee_map.get(e[0]) for e in employees_data if e[1] in ['MJ', 'CJ']]
    
    # Hitung hari H-1 sebelum tanggal merah di bulan target
    month_prefix = f"{target_year}-{target_month:02d}-"
    holidays_in_month = {h for h in public_holidays if h.startswith(month_prefix)}
    days_before_holiday = {int(h.split('-')[2]) - 2 for h in holidays_in_month if int(h.split('-')[2]) > 1}

    # =================================================================
    # ATURAN YANG BERLAKU PER INDIVIDU (DALAM SATU LOOP UTAMA)
    # =================================================================
    for e_idx, (e_name, group) in enumerate(employees_data):
        
        # Aturan 1: Tidak boleh bekerja lebih dari 7 hari berturut-turut
        # Diterapkan dengan memastikan ada minimal 1 hari libur/cuti dalam setiap jendela 8 hari.
        if s_libur_idx is not None and s_cuti_idx is not None:
            for d in range(len(days) - 7):
                off_days_in_window = []
                for i in range(8):
                    is_libur = shifts[e_idx, d + i, s_libur_idx]
                    is_cuti = shifts[e_idx, d + i, s_cuti_idx]
                    
                    is_off_day = model.NewBoolVar(f'e{e_idx}_d{d+i}_is_off')
                    model.AddBoolOr([is_libur, is_cuti]).OnlyEnforceIf(is_off_day)
                    model.AddImplication(is_off_day.Not(), is_libur.Not())
                    model.AddImplication(is_off_day.Not(), is_cuti.Not())
                    off_days_in_window.append(is_off_day)
                
                model.Add(sum(off_days_in_window) > 0)

        # Aturan 2: Melarang pola jadwal SOCM -> Libur -> P (untuk laki-laki)
        if e_name in male_employees and s_socm_idx is not None and forbidden_p_indices:
            for d in range(len(days) - 2):
                trigger = [shifts[e_idx, d, s_socm_idx], shifts[e_idx, d + 1, s_libur_idx]]
                # Jika trigger terpenuhi, maka jumlah shift P yang dilarang pada hari ke-3 harus 0
                model.Add(sum(shifts[e_idx, d + 2, s_idx] for s_idx in forbidden_p_indices if s_idx is not None) == 0).OnlyEnforceIf(trigger)
        
        # Aturan 3: Batasan Kerja Akhir Pekan per Grup
        
        weekend_work_days = sum(shifts[e_idx, d, s_idx] for d in range(len(days)) if day_types[d] in ['Sabtu', 'Minggu'] for s_idx in work_shift_indices)
        if group == 'FB':
            model.AddLinearConstraint(weekend_work_days, 3, 5)
        if group == 'MB':
            model.AddLinearConstraint(weekend_work_days, 4, 6)

        

        # Aturan 5: Larangan Shift Spesifik untuk Karyawan Tertentu
        if e_idx == e_b33_idx and s_p9_idx is not None:
            for d in range(len(days)):
                model.Add(shifts[e_idx, d, s_p9_idx] == 0)
        
        if e_idx in [e_b31_idx, e_b32_idx] and s_p10_idx is not None:
            for d in range(len(days)):
                model.Add(shifts[e_idx, d, s_p10_idx] == 0)

    # =================================================================
    # ATURAN YANG BERLAKU SECARA GLOBAL PER HARI
    # =================================================================
    
    # Aturan 6: Minimal 2 Laki-laki Bandung shift malam setiap hari
    if male_bandung_indices and night_shift_indices:
        for d in range(len(days)):
            model.Add(sum(shifts[e_idx, d, s_idx] for e_idx in male_bandung_indices for s_idx in night_shift_indices) >= 2)

    # Aturan 7: Role P9 di akhir pekan hanya untuk Laki-laki Bandung
    if s_p9_idx is not None and male_bandung_indices:
        non_mb_indices = [i for i in range(len(employees_data)) if i not in male_bandung_indices]
        for d in range(len(days)):
            if day_types[d] in ['Sabtu', 'Minggu']:
                for e_idx in non_mb_indices:
                    model.Add(shifts[e_idx, d, s_p9_idx] == 0)
    
     
def apply_jakarta_monthly_rules(model, shifts, employees_data, days, day_types, employee_map, shift_map, roles, max_work_days, min_work_days, num_weekends, min_libur, forbidden_shifts_by_group):
    """
    Menerapkan semua aturan bulanan dan aturan wajib akhir pekan
    yang spesifik untuk karyawan Jakarta.
    """
    # --- 1. Definisi Variabel yang Relevan ---
    s_libur_idx = shift_map.get('Libur')
    s_cuti_idx = shift_map.get('Cuti')
    
    jakarta_indices = [employee_map.get(e[0]) for e in employees_data if e[1] in ['MJ', 'CJ']]
    
    if s_libur_idx is None or s_cuti_idx is None or len(jakarta_indices) != 3:
        print("Warning: Aturan bulanan Jakarta tidak dapat diterapkan.")
        return

    # --- 2. Terapkan Aturan ---
    # Loop untuk setiap karyawan Jakarta
    for e_idx in jakarta_indices:
        
        # --- Aturan Bulanan (Total Hari Kerja & Libur) ---
        work_indices = [shift_map.get(s) for s in roles if s in shift_map]
        total_work_days = sum(shifts[(e_idx, d, s_idx)] for d in days for s_idx in work_indices)
        model.Add(total_work_days <= max_work_days)
        model.Add(total_work_days >= min_work_days)
        
        total_libur = sum(shifts[(e_idx, d, s_libur_idx)] for d in days)
        model.AddLinearConstraint(total_libur, min_libur, num_weekends)

        # --- Aturan Larangan Shift berdasarkan Grup ---
        group = 'MJ' if employees_data[e_idx][1] == 'MJ' else 'CJ' # Dapatkan grup dari e_idx
        forbidden_roles = forbidden_shifts_by_group.get(group, [])
        if forbidden_roles:
            forbidden_indices = [shift_map.get(role) for role in forbidden_roles if role in shift_map]
            for d in days:
                for s_idx in forbidden_indices:
                    if s_idx is not None:
                        model.Add(shifts[e_idx, d, s_idx] == 0)

    # =================================================================
    # --- [ATURAN BARU] Aturan Wajib Libur Akhir Pekan untuk Tim Jakarta ---
    # =================================================================
    for d in days:
        if day_types[d] in ['Sabtu', 'Minggu']:
            # Hitung jumlah karyawan Jakarta yang 'Libur' pada hari ini
            jakarta_libur_count = sum(shifts[e_idx, d, s_libur_idx] for e_idx in jakarta_indices)

            # Aturan wajib: Tepat 2 orang harus Libur
            model.Add(jakarta_libur_count == 2)

  
def apply_jakarta_rules(model, shifts, employees_data, days, day_types, employee_map, shift_map):
    """Menerapkan semua aturan pola kerja baru yang spesifik untuk karyawan Jakarta."""

    # --- 1. Definisi Variabel yang Relevan ---
    s_libur_idx = shift_map.get('Libur')
    s_cuti_idx = shift_map.get('Cuti')
    s_p7_idx = shift_map.get('P7')
    s_p8_idx = shift_map.get('P8')
    s_p9_idx = shift_map.get('P9')
    s_p10_idx = shift_map.get('P10')
    s_p11_idx = shift_map.get('P11')
    s_m_idx = shift_map.get('M')
    
    jakarta_indices = [employee_map.get(e[0]) for e in employees_data if e[1] in ['MJ', 'CJ']]
    
    if not all([s_libur_idx, s_cuti_idx, s_p7_idx, s_p8_idx, s_p9_idx, s_p10_idx, s_p11_idx, s_m_idx]) or len(jakarta_indices) != 3:
        print("Warning: Aturan Jakarta tidak dapat diterapkan karena shift atau jumlah karyawan tidak sesuai.")
        return

    # --- 2. Terapkan Aturan untuk Setiap Hari ---
    for d in days:
        # Hitung jumlah shift relevan untuk grup Jakarta pada hari d
        jakarta_off_count = sum(shifts[e_idx, d, s_libur_idx] + shifts[e_idx, d, s_cuti_idx] for e_idx in jakarta_indices)
        jakarta_p7_count = sum(shifts[e_idx, d, s_p7_idx] for e_idx in jakarta_indices)
        jakarta_p8_count = sum(shifts[e_idx, d, s_p8_idx] for e_idx in jakarta_indices)
        jakarta_p9_count = sum(shifts[e_idx, d, s_p9_idx] for e_idx in jakarta_indices)
        jakarta_p10_count = sum(shifts[e_idx, d, s_p10_idx] for e_idx in jakarta_indices)
        jakarta_p11_count = sum(shifts[e_idx, d, s_p11_idx] for e_idx in jakarta_indices)
        jakarta_m_count = sum(shifts[e_idx, d, s_m_idx] for e_idx in jakarta_indices)

        # Aturan Umum: Karyawan Jakarta tidak pernah boleh libur/cuti bertiga di hari yang sama
        model.Add(jakarta_off_count != 3)

        # --- Skenario Hari Biasa (Weekday) ---
        if day_types[d] == 'Weekday':
            # Aturan baru: Di hari biasa, tidak boleh ada 2 orang yang libur/cuti
            model.Add(jakarta_off_count != 2)

            # Pemicu: Jika TEPAT 1 orang libur/cuti
            trigger_1_off = model.NewBoolVar(f'jkt_1_off_d{d}')
            model.Add(jakarta_off_count == 1).OnlyEnforceIf(trigger_1_off)
            model.Add(jakarta_off_count != 1).OnlyEnforceIf(trigger_1_off.Not())
            
            # Konsekuensi: WAJIB memilih salah satu dari dua komposisi tim berikut
            # Pilihan 1: Tim terdiri dari (Libur/Cuti), P7, P9
            combo_p7_p9 = model.NewBoolVar(f'jkt_combo_p7p9_d{d}')
            model.Add(jakarta_p7_count == 1).OnlyEnforceIf(combo_p7_p9)
            model.Add(jakarta_p9_count == 1).OnlyEnforceIf(combo_p7_p9)
            model.Add(jakarta_p10_count == 0).OnlyEnforceIf(combo_p7_p9) # Pastikan P10 tidak ada
            model.Add(jakarta_p8_count == 0).OnlyEnforceIf(combo_p7_p9)
            model.Add(jakarta_p11_count == 0).OnlyEnforceIf(combo_p7_p9)
            model.Add(jakarta_m_count == 0).OnlyEnforceIf(combo_p7_p9)

            # Pilihan 2: Tim terdiri dari (Libur/Cuti), P7, P10
            combo_p7_p10 = model.NewBoolVar(f'jkt_combo_p7p10_d{d}')
            model.Add(jakarta_p7_count == 1).OnlyEnforceIf(combo_p7_p10)
            model.Add(jakarta_p10_count == 1).OnlyEnforceIf(combo_p7_p10)
            model.Add(jakarta_p9_count == 0).OnlyEnforceIf(combo_p7_p10) # Pastikan P9 tidak ada
            model.Add(jakarta_p8_count == 0).OnlyEnforceIf(combo_p7_p10)
            model.Add(jakarta_p11_count == 0).OnlyEnforceIf(combo_p7_p10)
            model.Add(jakarta_m_count == 0).OnlyEnforceIf(combo_p7_p10)
            
            # Constraint utama: Jika 1 orang libur, maka (pilihan 1 + pilihan 2) harus sama dengan 1
            model.Add(combo_p7_p9 + combo_p7_p10 == 1).OnlyEnforceIf(trigger_1_off)

            # Pemicu: Jika TIDAK ADA yang libur/cuti
            trigger_0_off = model.NewBoolVar(f'jkt_0_off_d{d}')
            model.Add(jakarta_off_count == 0).OnlyEnforceIf(trigger_0_off)
            model.Add(jakarta_off_count != 0).OnlyEnforceIf(trigger_0_off.Not())
            
            # Konsekuensi: WAJIB memilih salah satu dari 4 kombinasi tim
            combo1 = model.NewBoolVar(f'jkt_combo1_d{d}') # P7, P9, M
            combo2 = model.NewBoolVar(f'jkt_combo2_d{d}') # P7, P9, P11
            combo3 = model.NewBoolVar(f'jkt_combo3_d{d}') # P7, P10, M
            combo4 = model.NewBoolVar(f'jkt_combo4_d{d}') # P7, P10, P11
            
            model.Add(combo1 + combo2 + combo3 + combo4 == 1).OnlyEnforceIf(trigger_0_off)
            
            # Definisikan setiap kombinasi
            model.Add(jakarta_p7_count == 1).OnlyEnforceIf(combo1); model.Add(jakarta_p9_count == 1).OnlyEnforceIf(combo1); model.Add(jakarta_m_count == 1).OnlyEnforceIf(combo1)
            model.Add(jakarta_p7_count == 1).OnlyEnforceIf(combo2); model.Add(jakarta_p9_count == 1).OnlyEnforceIf(combo2); model.Add(jakarta_p11_count == 1).OnlyEnforceIf(combo2)
            model.Add(jakarta_p7_count == 1).OnlyEnforceIf(combo3); model.Add(jakarta_p10_count == 1).OnlyEnforceIf(combo3); model.Add(jakarta_m_count == 1).OnlyEnforceIf(combo3)
            model.Add(jakarta_p7_count == 1).OnlyEnforceIf(combo4); model.Add(jakarta_p10_count == 1).OnlyEnforceIf(combo4); model.Add(jakarta_p11_count == 1).OnlyEnforceIf(combo4)

        # --- Skenario Akhir Pekan (Weekend) ---
        elif day_types[d] in ['Sabtu', 'Minggu']:
            # Aturan wajib: 2 orang off, 1 orang P8
            model.Add(jakarta_off_count == 2)
            model.Add(jakarta_p8_count == 1)

def apply_bandung_monthly_rules(model, shifts, employees_data, days, roles, employee_map, shift_map, max_work_days, min_work_days, num_weekends, min_libur, forbidden_shifts_by_group, code_to_nip_map):
    """Menerapkan semua aturan bulanan yang spesifik untuk karyawan Bandung."""
    
    # Aturan Larangan Shift untuk NIP 400201 (diasumsikan karyawan Bandung)
    target_nip = "400201"
    target_e_idx = -1
    for e_code, nip in code_to_nip_map.items():
        if nip == target_nip and e_code in employee_map:
            target_e_idx = employee_map[e_code]
            break
    forbidden_shifts_for_target = [shift_map.get(s) for s in ['SOC6', 'SOC2', 'SOCM', 'M']]

    # Loop hanya untuk karyawan Bandung
    for e_idx, (e_name, group) in enumerate(employees_data):
        if group in ['FB', 'MB']:
            
            # --- Aturan Hari Kerja & Libur ---
            work_indices = [shift_map.get(s) for s in roles if s in shift_map]
            total_work_days = sum(shifts[(e_idx, d, s_idx)] for d in days for s_idx in work_indices)
            model.Add(total_work_days <= max_work_days)
            model.Add(total_work_days >= min_work_days)
            
            total_libur = sum(shifts[(e_idx, d, shift_map.get('Libur'))] for d in days)
            model.AddLinearConstraint(total_libur, min_libur, num_weekends)

            # --- Aturan Spesifik Grup & Individu Bandung ---
            if e_idx == target_e_idx:
                for d in days:
                    for s_idx in forbidden_shifts_for_target:
                        if s_idx is not None: model.Add(shifts[e_idx, d, s_idx] == 0)
            
            if group == 'FB' and 'M' in shift_map:
                model.Add(sum(shifts[(e_idx, d, shift_map['M'])] for d in days) == 2)
            
            forbidden_roles = forbidden_shifts_by_group.get(group, [])
            if forbidden_roles:
                forbidden_indices = [shift_map.get(role) for role in forbidden_roles if role in shift_map]
                for d in days:
                    for s_idx in forbidden_indices:
                        if s_idx is not None: model.Add(shifts[e_idx, d, s_idx] == 0)

def apply_jakarta_monthly_rules(model, shifts, employees_data, days, day_types, employee_map, shift_map, roles, max_work_days, min_work_days, num_weekends, min_libur, forbidden_shifts_by_group):
    """
    Menerapkan semua aturan bulanan dan aturan wajib akhir pekan
    yang spesifik untuk karyawan Jakarta.
    """
    # --- 1. Definisi Variabel yang Relevan ---
    s_libur_idx = shift_map.get('Libur')
    s_p8_idx = shift_map.get('P8')
    s_cuti_idx = shift_map.get('Cuti')
    jakarta_indices = [employee_map.get(e[0]) for e in employees_data if e[1] in ['MJ', 'CJ']]
    
    if s_libur_idx is None or len(jakarta_indices) != 3:
        print("Warning: Aturan bulanan Jakarta tidak dapat diterapkan.")
        return

    # --- 2. Terapkan Aturan Bulanan (per Individu) ---
    for e_idx in jakarta_indices:
        
        # --- Aturan Total Hari Kerja & Libur ---
        work_indices = [shift_map.get(s) for s in roles if s in shift_map]
        total_work_days = sum(shifts[(e_idx, d, s_idx)] for d in days for s_idx in work_indices)
        model.Add(total_work_days <= max_work_days)
        model.Add(total_work_days >= min_work_days)
        
        total_libur = sum(shifts[(e_idx, d, s_libur_idx)] for d in days)
        model.AddLinearConstraint(total_libur, min_libur, num_weekends)

        # --- Aturan Larangan Shift berdasarkan Grup ---
        group = employees_data[e_idx][1] # Dapatkan grup dari e_idx
        forbidden_roles = forbidden_shifts_by_group.get(group, [])
        if forbidden_roles:
            forbidden_indices = [shift_map.get(role) for role in forbidden_roles if role in shift_map]
            for d in days:
                for s_idx in forbidden_indices:
                    if s_idx is not None:
                        model.Add(shifts[e_idx, d, s_idx] == 0)

    # =================================================================
    # --- [ATURAN BARU] Aturan Wajib Libur Akhir Pekan untuk Tim Jakarta ---
    # =================================================================
    for d in days:
        if day_types[d] in ['Sabtu', 'Minggu']:
            
            # ✅ PERBAIKAN: Hitung jumlah karyawan Jakarta yang 'Libur' ATAU 'Cuti'
            jakarta_off_count = sum(shifts[e_idx, d, s_libur_idx] + shifts[e_idx, d, s_cuti_idx] for e_idx in jakarta_indices)
            
            

            # Aturan wajib: 2 orang off (Libur/Cuti), 1 orang P8
            model.Add(jakarta_off_count == 2)
            

def apply_jakarta_rules(model, shifts, employees_data, days, day_types, employee_map, shift_map):
    """Menerapkan semua aturan pola kerja baru yang spesifik untuk karyawan Jakarta."""

    # --- 1. Definisi Variabel yang Relevan ---
    s_libur_idx = shift_map.get('Libur')
    s_cuti_idx = shift_map.get('Cuti')
    s_p7_idx = shift_map.get('P7')
    s_p8_idx = shift_map.get('P8')
    s_p9_idx = shift_map.get('P9')
    s_p10_idx = shift_map.get('P10')
    s_p11_idx = shift_map.get('P11')
    s_m_idx = shift_map.get('M')
    
    jakarta_indices = [employee_map.get(e[0]) for e in employees_data if e[1] in ['MJ', 'CJ']]
    
    if not all([s_libur_idx, s_cuti_idx, s_p7_idx, s_p8_idx, s_p9_idx, s_p10_idx, s_p11_idx, s_m_idx]) or len(jakarta_indices) != 3:
        print("Warning: Aturan Jakarta tidak dapat diterapkan.")
        return
    
    print(f"[DEBUG] Jumlah karyawan Jakarta ditemukan: {len(jakarta_indices)}")
    if len(jakarta_indices) != 3:
        print("[DEBUG] GAGAL: Jumlah karyawan Jakarta bukan 3.")
    
    required_shifts_exist = all([s_libur_idx, s_cuti_idx, s_p7_idx, s_p8_idx, s_p9_idx, s_p10_idx, s_p11_idx, s_m_idx])
    if not required_shifts_exist:
        print("[DEBUG] GAGAL: Salah satu shift yang dibutuhkan tidak ada di shift_map.")

    if not required_shifts_exist or len(jakarta_indices) != 3:
        print("Warning: Aturan Jakarta tidak dapat diterapkan.")
        return

    # --- 2. Terapkan Aturan untuk Setiap Hari ---
    for d in days:
        jakarta_off_count = sum(shifts[e_idx, d, s_libur_idx] + shifts[e_idx, d, s_cuti_idx] for e_idx in jakarta_indices)
        jakarta_p7_count = sum(shifts[e_idx, d, s_p7_idx] for e_idx in jakarta_indices)
        jakarta_p8_count = sum(shifts[e_idx, d, s_p8_idx] for e_idx in jakarta_indices)
        jakarta_p9_count = sum(shifts[e_idx, d, s_p9_idx] for e_idx in jakarta_indices)
        jakarta_p10_count = sum(shifts[e_idx, d, s_p10_idx] for e_idx in jakarta_indices)
        jakarta_p11_count = sum(shifts[e_idx, d, s_p11_idx] for e_idx in jakarta_indices)
        jakarta_m_count = sum(shifts[e_idx, d, s_m_idx] for e_idx in jakarta_indices)

        # --- Skenario Hari Biasa (Weekday) ---
        if day_types[d] == 'Weekday':
            # Pemicu: Jika TEPAT 1 orang libur/cuti
            trigger_1_off = model.NewBoolVar(f'jkt_1_off_d{d}')
            model.Add(jakarta_off_count == 1).OnlyEnforceIf(trigger_1_off)
            model.Add(jakarta_off_count != 1).OnlyEnforceIf(trigger_1_off.Not())
            
            # Konsekuensi: WAJIB memilih salah satu dari dua komposisi tim berikut
            # Pilihan 1: Tim terdiri dari (Libur/Cuti), P7, P9
            combo_p7_p9 = model.NewBoolVar(f'jkt_combo_p7p9_d{d}')
            model.Add(jakarta_p7_count == 1).OnlyEnforceIf(combo_p7_p9)
            model.Add(jakarta_p9_count == 1).OnlyEnforceIf(combo_p7_p9)
            

            # Pilihan 2: Tim terdiri dari (Libur/Cuti), P7, P10
            combo_p7_p10 = model.NewBoolVar(f'jkt_combo_p7p10_d{d}')
            model.Add(jakarta_p7_count == 1).OnlyEnforceIf(combo_p7_p10)
            model.Add(jakarta_p10_count == 1).OnlyEnforceIf(combo_p7_p10)
            
            
            # Constraint utama: Jika 1 orang libur, maka (pilihan 1 + pilihan 2) harus sama dengan 1
            model.Add(combo_p7_p9 + combo_p7_p10 == 1).OnlyEnforceIf(trigger_1_off)

            # Pemicu: Jika TIDAK ADA yang libur/cuti
            trigger_0_off = model.NewBoolVar(f'jkt_0_off_d{d}')
            model.Add(jakarta_off_count == 0).OnlyEnforceIf(trigger_0_off)
            model.Add(jakarta_off_count != 0).OnlyEnforceIf(trigger_0_off.Not())
            
            # Konsekuensi: WAJIB memilih salah satu dari 4 kombinasi tim
            combo1 = model.NewBoolVar(f'jkt_combo1_d{d}') # P7, P9, M
            combo2 = model.NewBoolVar(f'jkt_combo2_d{d}') # P7, P9, P11
            combo3 = model.NewBoolVar(f'jkt_combo3_d{d}') # P7, P10, M
            combo4 = model.NewBoolVar(f'jkt_combo4_d{d}') # P7, P10, P11
            
            model.Add(combo1 + combo2 + combo3 + combo4 == 1).OnlyEnforceIf(trigger_0_off)
            
            model.Add(jakarta_p7_count == 1).OnlyEnforceIf(combo1); model.Add(jakarta_p9_count == 1).OnlyEnforceIf(combo1); model.Add(jakarta_m_count == 1).OnlyEnforceIf(combo1)
            model.Add(jakarta_p7_count == 1).OnlyEnforceIf(combo2); model.Add(jakarta_p9_count == 1).OnlyEnforceIf(combo2); model.Add(jakarta_p11_count == 1).OnlyEnforceIf(combo2)
            model.Add(jakarta_p7_count == 1).OnlyEnforceIf(combo3); model.Add(jakarta_p10_count == 1).OnlyEnforceIf(combo3); model.Add(jakarta_m_count == 1).OnlyEnforceIf(combo3)
            model.Add(jakarta_p7_count == 1).OnlyEnforceIf(combo4); model.Add(jakarta_p10_count == 1).OnlyEnforceIf(combo4); model.Add(jakarta_p11_count == 1).OnlyEnforceIf(combo4)

        # --- Skenario Akhir Pekan (Weekend) ---
    
        elif day_types[d] in ['Sabtu', 'Minggu']:
            # Aturan wajib: 2 orang off (Libur/Cuti), 1 orang P8
            model.Add(jakarta_off_count == 2)
            model.Add(jakarta_p8_count == 1)
        
            
   



def apply_soft_constraints(model, shifts, employees_data, days, day_types, employee_map, shift_map):
    """
    Menerapkan semua soft constraints dan mengembalikan objective function.
    Versi ini telah diperbaiki dan distruktur ulang untuk kebenaran dan kejelasan.
    """
    
    num_days = len(days)
    total_score_vars = []

    # --- Definisi Awal yang Dibutuhkan ---
    s_libur_idx = shift_map.get('Libur')
    s_cuti_idx = shift_map.get('Cuti')
    
    # ✅ PERBAIKAN KRITIS: 'Hari kerja' didefinisikan sebagai BUKAN Libur DAN BUKAN Cuti.
    # Logika 'or' sebelumnya salah dan menyebabkan error.
    work_shift_indices = [idx for name, idx in shift_map.items() if name not in ['Libur', 'Cuti']]

    # =================================================================
    # BAGIAN 1: PREFERENSI YANG BERLAKU PER-KARYAWAN SECARA INDIVIDU
    # =================================================================
    for e_idx, (e_name, group) in enumerate(employees_data):

        # Aturan #1 (BARU): Penalti untuk kerja 6 atau 7 hari berturut-turut
        # ----------------------------------------------------------------
        penalty_6_days = -30  # Penalti yang cukup kuat
        penalty_7_days = -60  # Penalti yang sangat kuat

        if s_libur_idx is not None and s_cuti_idx is not None:
            # Penalti untuk 6 hari kerja beruntun
            for d in range(num_days - 5):
                work_days_in_window = [
                    model.NewBoolVar(f'e{e_idx}_d{d+i}_is_work') for i in range(6)
                ]
                for i in range(6):
                    model.AddBoolAnd([
                        shifts[e_idx, d + i, s_libur_idx].Not(),
                        shifts[e_idx, d + i, s_cuti_idx].Not()
                    ]).OnlyEnforceIf(work_days_in_window[i])
                
                works_6_straight = model.NewBoolVar(f'e{e_idx}_works_6_straight_d{d}')
                model.AddBoolAnd(work_days_in_window).OnlyEnforceIf(works_6_straight)
                total_score_vars.append(works_6_straight * penalty_6_days)

            # Penalti untuk 7 hari kerja beruntun
            for d in range(num_days - 6):
                work_days_in_window = [
                    model.NewBoolVar(f'e{e_idx}_d{d+i}_is_work7') for i in range(7)
                ]
                for i in range(7):
                    model.AddBoolAnd([
                        shifts[e_idx, d + i, s_libur_idx].Not(),
                        shifts[e_idx, d + i, s_cuti_idx].Not()
                    ]).OnlyEnforceIf(work_days_in_window[i])

                works_7_straight = model.NewBoolVar(f'e{e_idx}_works_7_straight_d{d}')
                model.AddBoolAnd(work_days_in_window).OnlyEnforceIf(works_7_straight)
                total_score_vars.append(works_7_straight * penalty_7_days)

    # =================================================================
    # BAGIAN 1: PREFERENSI YANG BERLAKU PER-KARYAWAN SECARA INDIVIDU
    # =================================================================

    # Aturan #1: Preferensi jumlah shift SPESIFIK per bulan (misal, P6 antara 2-6 kali)
    preferences_with_range = [
        ('P6', 'FB', 2, 6, 10), ('P7', 'FB', 2, 6, 10), ('P8', 'FB', 2, 9, 10), 
        ('P9', 'FB', 3, 3, 10), ('SOC6', 'FB', 1, 3, 10), ('P6', 'MB', 0, 1, 10), 
        ('P7', 'MB', 0, 1, 10), ('P8', 'MB', 0, 3, 10), ('P9', 'MB', 0, 4, 10),
        ('P10', 'MB', 0, 5, 10), ('P11', 'MB', 1, 2, 10), ('S12', 'MB', 1, 9, 10),
        ('M', 'MB', 1, 3, 10), ('SOCM', 'MB', 1, 3, 10), ('SOC2', 'MB', 1, 3, 10),
        ('SOC6', 'MB', 0, 1, 10), ('P7', 'MJ', 1, 8, 10), ('P8', 'MJ', 2, 5, 10),
        ('P9', 'MJ', 1, 7, 10), ('P11', 'MJ', 1, 4, 10), ('M', 'MJ', 1, 2, 10),
        ('P7', 'CJ', 1, 8, 10), ('P8', 'CJ', 2, 5, 10), ('P10', 'CJ', 1, 9, 10),
        ('P11', 'CJ', 1, 4, 10), ('M', 'CJ', 1, 2, 10),
    ]
    for shift_name, group, min_val, max_val, weight in preferences_with_range:
        s_idx = shift_map.get(shift_name)
        if s_idx is None: continue
        group_indices = [employee_map[e[0]] for e in employees_data if e[1] == group]
        for e_idx in group_indices:
            total = sum(shifts[e_idx, d, s_idx] for d in range(num_days))
            in_range = model.NewBoolVar(f'pref_in_range_e{e_idx}_{shift_name}')
            model.Add(total >= min_val).OnlyEnforceIf(in_range)
            model.Add(total <= max_val).OnlyEnforceIf(in_range)
            total_score_vars.append(in_range * weight)

    # Loop per-karyawan untuk aturan individu lainnya
    for e_idx, (e_name, group) in enumerate(employees_data):
        # Aturan #2: Preferensi jumlah TOTAL kerja di akhir pekan
        weekend_work_days = sum(shifts[e_idx, d, s_idx] 
                                for d in range(num_days) 
                                if day_types[d] in ['Sabtu', 'Minggu'] 
                                for s_idx in work_shift_indices)
        
        weekend_preference_weight = 15
        if group == 'FB':
            min_val, max_val = 3, 4
            is_in_range = model.NewBoolVar(f'weekend_in_range_e{e_idx}_fb')
            model.Add(weekend_work_days >= min_val).OnlyEnforceIf(is_in_range)
            model.Add(weekend_work_days <= max_val).OnlyEnforceIf(is_in_range)
            total_score_vars.append(is_in_range * weekend_preference_weight)
        if group == 'MB':
            min_val, max_val = 4, 5
            is_in_range = model.NewBoolVar(f'weekend_in_range_e{e_idx}_mb')
            model.Add(weekend_work_days >= min_val).OnlyEnforceIf(is_in_range)
            model.Add(weekend_work_days <= max_val).OnlyEnforceIf(is_in_range)
            total_score_vars.append(is_in_range * weekend_preference_weight)

        # Aturan #3: Bonus untuk setiap hari Libur di Akhir Pekan
        if s_libur_idx is not None:
            for d in range(num_days):
                if day_types[d] in ['Sabtu', 'Minggu']:
                    total_score_vars.append(shifts[e_idx, d, s_libur_idx]) # Bobot +1


    # =================================================================
    # BAGIAN 2: ATURAN PENYEIMBANGAN BEBAN KERJA ANTAR KARYAWAN (FAIRNESS)
    # =================================================================

    # Aturan #4: Penyeimbangan jumlah kerja di akhir pekan per kelompok
    balancing_weight = -15
    groups_to_balance = ['FB', 'MB', 'MJ', 'CJ']
    for group_code in groups_to_balance:
        group_indices = [employee_map[e[0]] for e in employees_data if e[1] == group_code]
        if not group_indices: continue
        
        weekend_totals = [sum(shifts[e_idx, d, s_idx] for d in range(num_days) if day_types[d] in ['Sabtu', 'Minggu'] for s_idx in work_shift_indices) for e_idx in group_indices]
        min_val = model.NewIntVar(0, num_days, f'min_wknd_work_{group_code}')
        max_val = model.NewIntVar(0, num_days, f'max_wknd_work_{group_code}')
        model.AddMinEquality(min_val, weekend_totals)
        model.AddMaxEquality(max_val, weekend_totals)
        work_range = model.NewIntVar(0, num_days, f'range_wknd_work_{group_code}')
        model.Add(work_range == max_val - min_val)
        total_score_vars.append(work_range * balancing_weight)

    # Aturan #5: Penyeimbangan shift malam ('M' + 'SOCM') untuk 'MB'
    # ... (dan aturan penyeimbangan shift lainnya yang sudah ada) ...


    # =================================================================
    # BAGIAN 3: PREFERENSI POLA JADWAL TERTENTU
    # =================================================================

    # Aturan #6: Bonus jika di akhir pekan ada 1 P8 dan 2 Libur untuk grup Jakarta
    s_p8_idx = shift_map.get('P8')
    if s_p8_idx is not None and s_libur_idx is not None:
        jakarta_indices = [employee_map[e[0]] for e in employees_data if e[1] in ['MJ', 'CJ']]
        if len(jakarta_indices) >= 3:
            for d in range(num_days):
                if day_types[d] in ['Sabtu', 'Minggu']:
                    # ✅ PERBAIKAN: Definisikan kondisi secara penuh untuk logika yang benar
                    cond1 = model.NewBoolVar(f'cond1_p8_d{d}')
                    model.Add(sum(shifts[e_idx, d, s_p8_idx] for e_idx in jakarta_indices) == 1).OnlyEnforceIf(cond1)
                    model.Add(sum(shifts[e_idx, d, s_p8_idx] for e_idx in jakarta_indices) != 1).OnlyEnforceIf(cond1.Not())

                    cond2 = model.NewBoolVar(f'cond2_libur_d{d}')
                    model.Add(sum(shifts[e_idx, d, s_libur_idx] for e_idx in jakarta_indices) == 2).OnlyEnforceIf(cond2)
                    model.Add(sum(shifts[e_idx, d, s_libur_idx] for e_idx in jakarta_indices) != 2).OnlyEnforceIf(cond2.Not())

                    rule_met = model.NewBoolVar(f'jakarta_rule_met_d{d}')
                    model.AddBoolAnd([cond1, cond2]).OnlyEnforceIf(rule_met)
                    # Implikasi sebaliknya tidak wajib karena solver akan otomatis memaksimalkan rule_met
                    
                    total_score_vars.append(rule_met * 15)

    # Aturan #7: Bonus jika ada selang libur antar akhir pekan
    if s_libur_idx is not None:
        weekend_blocks = []
        for d in range(num_days - 1):
            if day_types[d] == 'Sabtu' and day_types[d + 1] == 'Minggu':
                weekend_blocks.append([d, d + 1])
        
        for e_idx in range(len(employees_data)):
            for w in range(len(weekend_blocks) - 1):
                weekend_A, weekend_B = weekend_blocks[w], weekend_blocks[w+1]
                
                works_weekend_A = model.NewBoolVar(f'e{e_idx}_works_wkndA_{w}')
                model.AddBoolOr([shifts[e_idx, weekend_A[0], s_libur_idx].Not(), shifts[e_idx, weekend_A[1], s_libur_idx].Not()]).OnlyEnforceIf(works_weekend_A)

                off_on_weekend_B = model.NewBoolVar(f'e{e_idx}_off_wkndB_{w}')
                model.AddBoolOr([shifts[e_idx, weekend_B[0], s_libur_idx], shifts[e_idx, weekend_B[1], s_libur_idx]]).OnlyEnforceIf(off_on_weekend_B)

                rule_satisfied = model.NewBoolVar(f'e{e_idx}_weekend_break_rule_{w}')
                model.AddBoolOr([works_weekend_A.Not(), off_on_weekend_B]).OnlyEnforceIf(rule_satisfied)
                total_score_vars.append(rule_satisfied * 20)
    
    # =================================================================
    # FINAL: KEMBALIKAN FUNGSI OBJEKTIF UNTUK DIMAKSIMALKAN
    # =================================================================
    return sum(total_score_vars)

import calendar
import collections
from ortools.sat.python import cp_model
from datetime import date


def solve_one_instance(employees_data, target_year, target_month, pre_assignment_requests, public_holidays):
    """Fungsi ini menjalankan solver untuk SATU KALI proses."""

    # =================================================================
    # --- 1. SETUP DATA ---
    # =================================================================
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
    
    employees = [e[0] for e in employees_data]
    employee_map = {name: i for i, name in enumerate(employees)}
    _, num_days = calendar.monthrange(target_year, target_month)
    days = range(num_days)
    
    holiday_dates_str = set(public_holidays)
    day_types = {}
    for d in days:
        day_num = d + 1
        current_date_str = f"{target_year}-{target_month:02d}-{day_num:02d}"
        day_of_week = calendar.weekday(target_year, target_month, day_num)
        if current_date_str in holiday_dates_str:
            day_types[d] = 'Minggu'
        elif day_of_week == 5: # Sabtu
            day_types[d] = 'Sabtu'
        elif day_of_week == 6: # Minggu
            day_types[d] = 'Minggu'
        else:
            day_types[d] = 'Weekday'
    
    month_prefix = f"{target_year}-{target_month:02d}-"
    holidays_in_month = [h for h in public_holidays if h.startswith(month_prefix)]
    num_weekends = len([d for d, type in day_types.items() if type in ['Sabtu', 'Minggu']])
    print(len(holidays_in_month), public_holidays, num_weekends)
    max_work_days = num_days - num_weekends+len(holidays_in_month)  
    min_work_days = num_days - num_weekends  
    min_libur = num_weekends-len(holidays_in_month) 
    print(f"Max work days: {max_work_days}, Min work days: {min_work_days}, Min libur: {min_libur}, Max libur: {num_weekends}")
    
    

    assignable_roles = ['P6', 'P7', 'P8', 'P9', 'P10', 'P11', 'S12', 'M', 'SOCM', 'SOC2', 'SOC6']
    count_as_work_roles = assignable_roles + ['Cuti']
    non_work_statuses = ['Libur']
    all_shifts = assignable_roles + ['Libur', 'Cuti']
    shift_map = {name: i for i, name in enumerate(all_shifts)}
    
    night_shifts = ['M', 'SOCM']
    female_employees = [e[0] for e in employees_data if e[1] in ['FB', 'CJ']]
    male_employees = [e[0] for e in employees_data if e[1] in ['MB', 'MJ']]
    male_bandung_indices = [employee_map.get(e[0]) for e in employees_data if e[1] == 'MB']
    night_shift_indices = [shift_map.get(s) for s in night_shifts if s]

    demand = { 'P6': {'Weekday': 2, 'Sabtu': 2, 'Minggu': 2}, 'P7': {'Weekday': 3, 'Sabtu': 2, 'Minggu': 1}, 'P8': {'Weekday': (3, 5), 'Sabtu': 2, 'Minggu': 1}, 'P9': {'Weekday': (2, 5), 'Sabtu': 2, 'Minggu': 1}, 'P10': {'Weekday': (2, 4), 'Sabtu': 0, 'Minggu': 0}, 'P11': {'Weekday': 1, 'Sabtu': 1, 'Minggu': 1}, 'S12': {'Weekday': 5, 'Sabtu': 3, 'Minggu': 3}, 'M': {'Weekday': 2, 'Sabtu': 2, 'Minggu': 2}, 'SOCM': {'Weekday': 1, 'Sabtu': 1, 'Minggu': 1}, 'SOC2': {'Weekday': 1, 'Sabtu': 1, 'Minggu': 1}, 'SOC6': {'Weekday': 1, 'Sabtu': 1, 'Minggu': 1} }
    forbidden_shifts_by_group = { 'FB': ['P10', 'P11', 'S12', 'SOC2', 'SOCM'], 'MJ': ['P6', 'P10', 'S12', 'SOC2', 'SOC6', 'SOCM'], 'CJ': ['P6', 'P9', 'S12', 'SOC2', 'SOC6', 'SOCM'] }
    
    pre_assignments = {}
    for req in pre_assignment_requests:
        real_nip, jenis, tanggal_str = str(req.get('nip')), req.get('jenis'), req.get('tanggal')
        if not (real_nip and jenis and tanggal_str): continue
        try:
            internal_code = nip_to_code_map.get(real_nip)
            if internal_code:
                e_idx = employee_map.get(internal_code)
                parsed_date = datetime.strptime(tanggal_str, '%Y-%m-%d')
                if parsed_date.year == target_year and parsed_date.month == target_month and e_idx is not None:
                    day_idx = parsed_date.day - 1
                    pre_assignments[(e_idx, day_idx)] = jenis
        except (ValueError, TypeError):
            continue
            
    # =================================================================
    # --- 2. INISIALISASI MODEL ---
    # =================================================================
    model = cp_model.CpModel()
    shifts = { (employee_map[e], d, shift_map[s]): model.NewBoolVar(f's_{e}_{d}_{s}') for e in employees for d in days for s in all_shifts }
    
    # =================================================================
    # --- 3. TERAPKAN HARD CONSTRAINTS (Aturan Wajib) ---
    # =================================================================
    
    # Larangan Cuti Otomatis
    s_cuti_idx = shift_map['Cuti']
    requested_cuti_days = {(e, d) for (e, d), s in pre_assignments.items() if s == 'Cuti'}
    for e_idx in range(len(employees)):
        for d in days:
            if (e_idx, d) not in requested_cuti_days:
                model.Add(shifts[e_idx, d, s_cuti_idx] == 0)

    
    # Panggil semua fungsi aturan
    apply_pre_assignments(model, shifts, pre_assignments, shift_map)
    apply_core_constraints(model, shifts, employees, days, demand, day_types, shift_map)
    apply_employee_monthly_rules(model, shifts, employees_data, days, count_as_work_roles, non_work_statuses, employee_map, shift_map, max_work_days, forbidden_shifts_by_group, num_weekends,min_work_days,min_libur,code_to_nip_map)
    apply_night_shift_rules(model, shifts, employees_data, days, female_employees, night_shifts, employee_map, shift_map)
    apply_additional_constraints(model, shifts, employees_data, days, day_types, employee_map, shift_map, male_employees, male_bandung_indices, night_shift_indices, public_holidays, target_year, target_month)
    apply_jakarta_rules(model, shifts, employees_data, days, day_types, employee_map, shift_map)
    # =================================================================
    # --- 4. TERAPKAN SOFT CONSTRAINTS (Preferensi) ---
    # =================================================================
    objective_function = apply_soft_constraints(model, shifts, employees_data, days, day_types, employee_map, shift_map)
    model.Maximize(objective_function)
    
    # =================================================================
    # --- 5. JALANKAN SOLVER ---
    # =================================================================
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 400.0
    solver.parameters.log_search_progress = False
    solver.parameters.num_search_workers = 4
    status = solver.Solve(model)
    
    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        temp_schedule = collections.defaultdict(list)
        daily_summary = collections.defaultdict(lambda: collections.defaultdict(int))
        
        for e_code in employees:
            e_idx = employee_map[e_code]
            for d in days:
                for s_name, s_idx in shift_map.items():
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
    # ANGGA APIPUTRA (400189) - Cuti 7 Agt dihapus
    {"nip": "400189", "jenis": "Libur", "tanggal": "2025-08-09"},
    {"nip": "400189", "jenis": "Libur", "tanggal": "2025-08-23"},
    {"nip": "400189", "jenis": "Libur", "tanggal": "2025-08-24"},
    # DIAN KURNIAWAN (400209) - Libur 1 Agt dihapus
    {"nip": "400209", "jenis": "Libur", "tanggal": "2025-08-16"},
    {"nip": "400209", "jenis": "Libur", "tanggal": "2025-08-23"},
    {"nip": "400209", "jenis": "Libur", "tanggal": "2025-08-24"},
    # FEBRI INDRA WIJAYA (401133) - Semua request dihapus
    # INDAH NURUL AFIFAH ABDULLAH (400092) - Request diubah
    {"nip": "400092", "jenis": "Libur", "tanggal": "2025-08-17"},
    {"nip": "400092", "jenis": "Libur", "tanggal": "2025-08-22"},
    {"nip": "400092", "jenis": "Libur", "tanggal": "2025-08-29"},
    # PURI AGI PRATOMO (400217) - Request diubah
    {"nip": "400217", "jenis": "Libur", "tanggal": "2025-08-17"},
    {"nip": "400217", "jenis": "Libur", "tanggal": "2025-08-24"},
    {"nip": "400217", "jenis": "Libur", "tanggal": "2025-08-31"},
    {"nip": "400217", "jenis": "Cuti", "tanggal": "2025-08-18"},
    # REZA APRIANA (400090) - Request diubah
    {"nip": "400090", "jenis": "Libur", "tanggal": "2025-08-09"},
    {"nip": "400090", "jenis": "Libur", "tanggal": "2025-08-17"},
    {"nip": "400090", "jenis": "Libur", "tanggal": "2025-08-30"},
    # SHARAH ISTIQOMAH (400202) - Request diubah
    {"nip": "400202", "jenis": "Libur", "tanggal": "2025-08-15"},
    {"nip": "400202", "jenis": "Libur", "tanggal": "2025-08-17"},
    {"nip": "400202", "jenis": "Libur", "tanggal": "2025-08-22"},
    {"nip": "400202", "jenis": "Cuti", "tanggal": "2025-08-29"},
    # --- SISA KARYAWAN (TIDAK BERUBAH) ---
    {"nip": "400198", "jenis": "Libur", "tanggal": "2025-08-02"},
    {"nip": "400198", "jenis": "Libur", "tanggal": "2025-08-03"},
    {"nip": "400198", "jenis": "Libur", "tanggal": "2025-08-31"},
    {"nip": "400213", "jenis": "Libur", "tanggal": "2025-08-15"},
    {"nip": "400213", "jenis": "Libur", "tanggal": "2025-08-07"},
    {"nip": "400213", "jenis": "Libur", "tanggal": "2025-08-08"},
    {"nip": "401107", "jenis": "Libur", "tanggal": "2025-08-09"},
    {"nip": "401107", "jenis": "Libur", "tanggal": "2025-08-10"},
    {"nip": "401107", "jenis": "Libur", "tanggal": "2025-08-16"},
    {"nip": "401107", "jenis": "Cuti", "tanggal": "2025-08-06"},
    {"nip": "401107", "jenis": "Cuti", "tanggal": "2025-08-07"},
    {"nip": "401107", "jenis": "Cuti", "tanggal": "2025-08-08"},
    {"nip": "401107", "jenis": "Cuti", "tanggal": "2025-08-11"},
    {"nip": "401107", "jenis": "Cuti", "tanggal": "2025-08-12"},
    {"nip": "401107", "jenis": "Cuti", "tanggal": "2025-08-13"},
    {"nip": "401107", "jenis": "Cuti", "tanggal": "2025-08-14"},
    {"nip": "401107", "jenis": "Cuti", "tanggal": "2025-08-15"},
    {"nip": "401136", "jenis": "Libur", "tanggal": "2025-08-03"},
    {"nip": "401136", "jenis": "Libur", "tanggal": "2025-08-28"},
    {"nip": "401136", "jenis": "Cuti", "tanggal": "2025-08-14"},
    {"nip": "401136", "jenis": "Cuti", "tanggal": "2025-08-15"},
    {"nip": "401524", "jenis": "Libur", "tanggal": "2025-08-02"},
    {"nip": "401524", "jenis": "Libur", "tanggal": "2025-08-03"},
    {"nip": "401524", "jenis": "Cuti", "tanggal": "2025-08-15"},
    {"nip": "401524", "jenis": "Cuti", "tanggal": "2025-08-18"},
    {"nip": "400204", "jenis": "Libur", "tanggal": "2025-08-18"},
    {"nip": "400204", "jenis": "Libur", "tanggal": "2025-08-31"},
    {"nip": "400201", "jenis": "Libur", "tanggal": "2025-08-03"},
    {"nip": "400201", "jenis": "Libur", "tanggal": "2025-08-13"},
    {"nip": "400201", "jenis": "Libur", "tanggal": "2025-08-14"},
    {"nip": "400210", "jenis": "Libur", "tanggal": "2025-08-05"},
    {"nip": "400210", "jenis": "Libur", "tanggal": "2025-08-14"},
    {"nip": "400210", "jenis": "Libur", "tanggal": "2025-08-28"},
    {"nip": "400216", "jenis": "Libur", "tanggal": "2025-08-02"},
    {"nip": "400216", "jenis": "Libur", "tanggal": "2025-08-03"},
    {"nip": "400216", "jenis": "Libur", "tanggal": "2025-08-31"},
    {"nip": "400091", "jenis": "Libur", "tanggal": "2025-08-06"},
    {"nip": "400091", "jenis": "Libur", "tanggal": "2025-08-28"},
    {"nip": "400212", "jenis": "Cuti", "tanggal": "2025-08-01"},
    {"nip": "400212", "jenis": "Cuti", "tanggal": "2025-08-02"},
    {"nip": "400212", "jenis": "Cuti", "tanggal": "2025-08-03"},
    {"nip": "400212", "jenis": "Libur", "tanggal": "2025-08-04"},
    {"nip": "400193", "jenis": "Libur", "tanggal": "2025-08-11"},
    {"nip": "400193", "jenis": "Libur", "tanggal": "2025-08-18"},
    {"nip": "401138", "jenis": "Libur", "tanggal": "2025-08-02"},
    {"nip": "401138", "jenis": "Libur", "tanggal": "2025-08-03"},
    {"nip": "401138", "jenis": "Libur", "tanggal": "2025-08-16"},
    {"nip": "401144", "jenis": "Libur", "tanggal": "2025-08-02"},
    {"nip": "401144", "jenis": "Libur", "tanggal": "2025-08-03"},
    {"nip": "400211", "jenis": "Libur", "tanggal": "2025-08-30"},
    {"nip": "400211", "jenis": "Libur", "tanggal": "2025-08-31"},
    {"nip": "400211", "jenis": "Cuti", "tanggal": "2025-08-15"},
    {"nip": "400206", "jenis": "Libur", "tanggal": "2025-08-24"},
    {"nip": "400206", "jenis": "Libur", "tanggal": "2025-08-25"},
    {"nip": "400087", "jenis": "Libur", "tanggal": "2025-08-10"},
    {"nip": "400087", "jenis": "Cuti", "tanggal": "2025-08-07"},
    {"nip": "401108", "jenis": "Libur", "tanggal": "2025-08-09"},
    {"nip": "401108", "jenis": "Libur", "tanggal": "2025-08-10"},
    {"nip": "400203", "jenis": "Libur", "tanggal": "2025-08-27"},
    {"nip": "400203", "jenis": "Libur", "tanggal": "2025-08-28"},
    {"nip": "400203", "jenis": "Libur", "tanggal": "2025-08-29"},
    {"nip": "400192", "jenis": "Libur", "tanggal": "2025-08-25"},
    {"nip": "400192", "jenis": "Libur", "tanggal": "2025-08-04"},
    {"nip": "400196", "jenis": "Libur", "tanggal": "2025-08-01"},
    {"nip": "400190", "jenis": "Libur", "tanggal": "2025-08-23"},
    {"nip": "400190", "jenis": "Libur", "tanggal": "2025-08-24"},
    {"nip": "400190", "jenis": "Libur", "tanggal": "2025-08-25"},
]
    
    daftar_tanggal_merah = [
          # Contoh: Hari Kemerdekaan
        "2025-08-18",
        "2025-08-17"
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