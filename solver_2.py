

def apply_bandung_rules(model, shifts, employees_data, days, day_types, employee_map, shift_map, roles, max_work_days, min_work_days, num_weekends, min_libur, forbidden_shifts_by_group, night_shifts):
    """Menerapkan SEMUA aturan untuk karyawan Bandung (Grup FB & MB)."""
    
    # --- Definisi variabel relevan untuk Bandung ---
    female_bandung_indices = [employee_map.get(e[0]) for e in employees_data if e[1] == 'FB']
    male_bandung_indices = [employee_map.get(e[0]) for e in employees_data if e[1] == 'MB']
    s_libur_idx = shift_map.get('Libur')
    s_cuti_idx = shift_map.get('Cuti', -1)
    s_m_idx = shift_map.get('M')
    s_p9_idx = shift_map.get('P9')
    work_indices = [shift_map.get(s) for s in roles]
    night_shift_indices = [shift_map.get(s) for s in night_shifts]

    # --- Aturan untuk Karyawati Bandung (FB) ---
    for e_idx in female_bandung_indices:
        # Aturan Bulanan
        model.Add(sum(shifts[e_idx, d, s_idx] for d in days for s_idx in work_indices) <= max_work_days)
        model.Add(sum(shifts[e_idx, d, s_idx] for d in days for s_idx in work_indices) >= min_work_days)
        model.AddLinearConstraint(sum(shifts[e_idx, d, s_libur_idx] for d in days), min_libur, num_weekends)
        model.Add(sum(shifts[e_idx, d, s_m_idx] for d in days) == 2) # Wajib 2 shift M
        
        # Aturan Akhir Pekan
        weekend_work = sum(shifts[e_idx, d, s_idx] for d in days if day_types[d] in ['Sabtu', 'Minggu'] for s_idx in work_indices)
        model.AddLinearConstraint(weekend_work, 3, 4)

        # Aturan 6 hari kerja berurutan
        for d in range(len(days) - 6):
            model.Add(sum(shifts[e_idx, d + i, s_libur_idx].Not() for i in range(7)) <= 6)
            
        # Aturan Shift Malam (jika ada)
        # ... (Anda bisa menambahkan aturan malam spesifik untuk FB di sini jika ada) ...

    # --- Aturan untuk Karyawan Laki-laki Bandung (MB) ---
    for e_idx in male_bandung_indices:
        # Aturan Bulanan
        model.Add(sum(shifts[e_idx, d, s_idx] for d in days for s_idx in work_indices) <= max_work_days)
        model.Add(sum(shifts[e_idx, d, s_idx] for d in days for s_idx in work_indices) >= min_work_days)
        model.AddLinearConstraint(sum(shifts[e_idx, d, s_libur_idx] for d in days), min_libur, num_weekends)

        # Aturan Akhir Pekan
        weekend_work = sum(shifts[e_idx, d, s_idx] for d in days if day_types[d] in ['Sabtu', 'Minggu'] for s_idx in work_indices)
        model.AddLinearConstraint(weekend_work, 4, 5)

        # Aturan 6 hari kerja berurutan
        for d in range(len(days) - 6):
            model.Add(sum(shifts[e_idx, d + i, s_libur_idx].Not() for i in range(7)) <= 6)
    
    # --- Aturan Global untuk Grup Bandung ---
    # Aturan: Minimal 2 Laki-laki Bandung shift malam setiap hari
    if male_bandung_indices and night_shift_indices:
        for d in days:
            model.Add(sum(shifts[e_idx, d, s_idx] for e_idx in male_bandung_indices for s_idx in night_shift_indices) >= 2)

    # Aturan: Role P9 di akhir pekan hanya untuk Laki-laki Bandung
    if s_p9_idx is not None and male_bandung_indices:
        non_mb_indices = [i for i in range(len(employees_data)) if i not in male_bandung_indices]
        for d in days:
            if day_types[d] in ['Sabtu', 'Minggu']:
                for e_idx in non_mb_indices:
                    model.Add(shifts[e_idx, d, s_p9_idx] == 0)


def apply_jakarta_rules(model, shifts, employees_data, days, day_types, employee_map, shift_map, roles, max_work_days, min_work_days, num_weekends, min_libur):
    """Menerapkan SEMUA aturan untuk karyawan Jakarta (Grup MJ & CJ)."""

    # --- Definisi variabel relevan untuk Jakarta ---
    jakarta_indices = [employee_map.get(e[0]) for e in employees_data if e[1] in ['MJ', 'CJ']]
    s_libur_idx = shift_map.get('Libur')
    s_cuti_idx = shift_map.get('Cuti')
    work_indices = [shift_map.get(s) for s in roles]
    
    # --- Aturan Bulanan Umum untuk Karyawan Jakarta ---
    for e_idx in jakarta_indices:
        if e_idx is None: continue
        model.Add(sum(shifts[e_idx, d, s_idx] for d in days for s_idx in work_indices) <= max_work_days)
        model.Add(sum(shifts[e_idx, d, s_idx] for d in days for s_idx in work_indices) >= min_work_days)
        model.AddLinearConstraint(sum(shifts[e_idx, d, s_libur_idx] for d in days), min_libur, num_weekends)
        for d in range(len(days) - 6):
            model.Add(sum(shifts[e_idx, d + i, s_libur_idx].Not() for i in range(7)) <= 6)
    
    # --- Aturan Pola Kerja Harian Grup Jakarta ---
    s_p7_idx = shift_map.get('P7')
    s_p8_idx = shift_map.get('P8')
    s_p9_idx = shift_map.get('P9')
    s_p10_idx = shift_map.get('P10')
    s_p11_idx = shift_map.get('P11')
    s_m_idx = shift_map.get('M')
    
    if jakarta_indices:
        for d in days:
            jakarta_off_count = sum(shifts[e_idx, d, s_libur_idx] + shifts[e_idx, d, s_cuti_idx] for e_idx in jakarta_indices)
            jakarta_p7_count = sum(shifts[e_idx, d, s_p7_idx] for e_idx in jakarta_indices)
            jakarta_p8_count = sum(shifts[e_idx, d, s_p8_idx] for e_idx in jakarta_indices)
            # ... (lanjutkan definisi jakarta_pX_count lainnya) ...
            
            # ... (kode lengkap untuk 3 skenario aturan pola Jakarta) ...