import collections
from ortools.sat.python import cp_model
import calendar
from datetime import datetime

# =================================================================================
# FUNGSI-FUNGSI ATURAN (CONSTRAINTS) - VERSI DEBUGGING
# =================================================================================

def apply_pre_assignments_debug(model, shifts, pre_assignments, shift_map, assumptions):
    for (e_idx, d), shift_name in pre_assignments.items():
        s_idx = shift_map.get(shift_name)
        if s_idx is not None:
            b = model.NewBoolVar(f'pre_assign_e{e_idx}_d{d+1}_{shift_name}')
            model.Add(shifts[e_idx, d, s_idx] == 1).OnlyEnforceIf(b)
            assumptions.append(b)

def apply_core_constraints_debug(model, shifts, employees, days, demand, day_types, shift_map, assumptions):
    num_employees = len(employees)
    # Aturan: Setiap karyawan punya tepat satu shift per hari
    for e_idx in range(num_employees):
        b_one_shift_per_day = model.NewBoolVar(f'satu_shift_per_hari_e{e_idx}')
        for d in days:
            model.Add(sum(shifts[(e_idx, d, s_idx)] for s_idx in range(len(shift_map))) == 1).OnlyEnforceIf(b_one_shift_per_day)
        assumptions.append(b_one_shift_per_day)

    # Aturan: Penuhi demand harian
    for d in days:
        day_type = day_types[d]
        for role_name, requirements in demand.items():
            s_idx = shift_map.get(role_name)
            if s_idx is not None:
                required = requirements.get(day_type, 0)
                if required == 0: continue
                total_shift = sum(shifts[e_idx, d, s_idx] for e_idx in range(num_employees))
                if isinstance(required, tuple):
                    min_req, max_req = required
                    b_min = model.NewBoolVar(f'demand_min_{role_name}_d{d+1}')
                    b_max = model.NewBoolVar(f'demand_max_{role_name}_d{d+1}')
                    model.Add(total_shift >= min_req).OnlyEnforceIf(b_min)
                    model.Add(total_shift <= max_req).OnlyEnforceIf(b_max)
                    assumptions.extend([b_min, b_max])
                elif required > 0:
                    b_exact = model.NewBoolVar(f'demand_exact_{role_name}_d{d+1}')
                    model.Add(total_shift == required).OnlyEnforceIf(b_exact)
                    assumptions.append(b_exact)

def apply_employee_monthly_rules_debug(model, shifts, employees_data, days, roles, non_work_statuses, employee_map, shift_map, max_work_days, forbidden_shifts_by_group, num_weekends, min_work_days, min_libur, code_to_nip_map, assumptions):
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
        work_indices = [shift_map[s] for s in roles if s in shift_map]
        b_max_work = model.NewBoolVar(f'max_work_days_e{e_idx}_{e_name}')
        total_work_days = sum(shifts[(e_idx, d, s_idx)] for d in days for s_idx in work_indices)
        model.Add(total_work_days <= max_work_days).OnlyEnforceIf(b_max_work)
        assumptions.append(b_max_work)

        b_min_work = model.NewBoolVar(f'min_work_days_e{e_idx}_{e_name}')
        model.Add(total_work_days >= min_work_days).OnlyEnforceIf(b_min_work)
        assumptions.append(b_min_work)

        b_libur_range = model.NewBoolVar(f'libur_range_e{e_idx}_{e_name}')
        total_libur = sum(shifts[(e_idx, d, shift_map.get('Libur'))] for d in days)
        model.AddLinearConstraint(total_libur, min_libur, num_weekends).OnlyEnforceIf(b_libur_range)
        assumptions.append(b_libur_range)

        if e_idx == target_e_idx:
            b_forbidden_400201 = model.NewBoolVar(f'forbidden_400201_e{e_idx}')
            for d in days:
                for s_idx in forbidden_indices_for_400201:
                    if s_idx is not None:
                        model.Add(shifts[e_idx, d, s_idx] == 0).OnlyEnforceIf(b_forbidden_400201)
            assumptions.append(b_forbidden_400201)

        if group == 'FB':
            if 'M' in shift_map:
                m_shift_idx = shift_map['M']
                b_m_shift = model.NewBoolVar(f'exact_2_M_shifts_fb_e{e_idx}_{e_name}')
                total_m_shifts = sum(shifts[(e_idx, d, m_shift_idx)] for d in days)
                model.Add(total_m_shifts == 2).OnlyEnforceIf(b_m_shift)
                assumptions.append(b_m_shift)

        forbidden_roles_for_group = forbidden_shifts_by_group.get(group, [])
        if forbidden_roles_for_group:
            b_forbidden_group = model.NewBoolVar(f'all_forbidden_shifts_e{e_idx}_{e_name}')
            forbidden_indices = [shift_map[role] for role in forbidden_roles_for_group if role in shift_map]
            for d in days:
                for s_idx in forbidden_indices:
                    model.Add(shifts[e_idx, d, s_idx] == 0).OnlyEnforceIf(b_forbidden_group)
            assumptions.append(b_forbidden_group)

def apply_night_shift_rules_debug(model, shifts, employees_data, days, female_employees, night_shifts, employee_map, shift_map, assumptions):
    num_days = len(days)
    s_night_indices = [shift_map[s] for s in night_shifts if s in shift_map]
    if not s_night_indices:
        return
    s_libur_idx = shift_map['Libur']
    s_cuti_idx = shift_map.get('Cuti', -1)
    is_night_vars = {}
    for e_idx, _ in enumerate(employees_data):
        for d in range(num_days):
            var = model.NewBoolVar(f'is_night_e{e_idx}_d{d}')
            night_shifts_on_day = [shifts[e_idx, d, s_idx] for s_idx in s_night_indices]
            model.Add(sum(night_shifts_on_day) == 1).OnlyEnforceIf(var)
            model.Add(sum(night_shifts_on_day) == 0).OnlyEnforceIf(var.Not())
            is_night_vars[(e_idx, d)] = var
    for e_idx, (e_name, group) in enumerate(employees_data):
        b_night_rules = model.NewBoolVar(f'all_night_rules_e{e_idx}_{e_name}')
        for d in range(num_days - 1):
            trigger_off = [is_night_vars[(e_idx, d)], is_night_vars[(e_idx, d + 1)].Not()]
            model.Add(shifts[e_idx, d + 1, s_libur_idx] == 1).OnlyEnforceIf(trigger_off + [b_night_rules])
        if e_name in female_employees:
            for d in range(num_days - 1):
                model.Add(is_night_vars[(e_idx, d)] + is_night_vars[(e_idx, d + 1)] <= 1).OnlyEnforceIf(b_night_rules)
        if s_cuti_idx != -1:
            for d in range(num_days - 3):
                trigger_2_night = [is_night_vars[(e_idx, d)], is_night_vars[(e_idx, d + 1)]]
                model.Add(shifts[e_idx, d + 2, s_libur_idx] + shifts[e_idx, d + 2, s_cuti_idx] == 1).OnlyEnforceIf(trigger_2_night + [b_night_rules])
                model.Add(shifts[e_idx, d + 3, s_libur_idx] + shifts[e_idx, d + 3, s_cuti_idx] == 1).OnlyEnforceIf(trigger_2_night + [b_night_rules])
        assumptions.append(b_night_rules)

def apply_additional_constraints_debug(model, shifts, employees_data, days, day_types, employee_map, shift_map, male_employees, male_bandung_indices, night_shift_indices, public_holidays, target_year, target_month, assumptions):
    s_libur_idx = shift_map.get('Libur')
    s_cuti_idx = shift_map.get('Cuti')
    s_socm_idx = shift_map.get('SOCM')
    s_p9_idx = shift_map.get('P9')
    s_p8_idx = shift_map.get('P8')
    s_p10_idx = shift_map.get('P10')
    s_p11_idx = shift_map.get('P11')
    s_m_idx = shift_map.get('M')
    work_shift_indices = [idx for name, idx in shift_map.items() if name not in ['Libur', 'Cuti']]
    night_indices = [idx for name, idx in shift_map.items() if name in ['M', 'SOCM']]
    forbidden_p_indices = [shift_map.get(r) for r in ['P6', 'P7', 'P8', 'P9'] if r in shift_map]
    e_b33_idx = employee_map.get('B33')
    e_b31_idx = employee_map.get('B31')
    e_b32_idx = employee_map.get('B32')
    jakarta_indices = [employee_map.get(e[0]) for e in employees_data if e[1] in ['MJ', 'CJ']]
    month_prefix = f"{target_year}-{target_month:02d}-"
    holidays_in_month = {h for h in public_holidays if h.startswith(month_prefix)}
    days_before_holiday = {int(h.split('-')[2]) - 2 for h in holidays_in_month if int(h.split('-')[2]) > 1}

    for e_idx, (e_name, group) in enumerate(employees_data):
        b_consecutive = model.NewBoolVar(f'max_6_consecutive_work_e{e_idx}_{e_name}')
        if s_libur_idx is not None:
            for d in range(len(days) - 6):
                non_off_days_in_window = [shifts[e_idx, d + i, s_libur_idx].Not() for i in range(7)]
                model.Add(sum(non_off_days_in_window) <= 6).OnlyEnforceIf(b_consecutive)
        assumptions.append(b_consecutive)

        if e_name in male_employees and s_socm_idx is not None and forbidden_p_indices:
            b_pattern = model.NewBoolVar(f'forbidden_pattern_male_e{e_idx}_{e_name}')
            for d in range(len(days) - 2):
                trigger = [shifts[e_idx, d, s_socm_idx], shifts[e_idx, d + 1, s_libur_idx]]
                valid_indices = [idx for idx in forbidden_p_indices if idx is not None]
                if valid_indices:
                    model.Add(sum(shifts[e_idx, d + 2, s_idx] for s_idx in valid_indices) == 0).OnlyEnforceIf(trigger + [b_pattern])
            assumptions.append(b_pattern)

        b_weekend_work = model.NewBoolVar(f'weekend_work_range_e{e_idx}_{e_name}')
        weekend_work_days = sum(shifts[e_idx, d, s_idx] for d in days if day_types[d] in ['Sabtu', 'Minggu'] for s_idx in work_shift_indices)
        if group == 'FB': model.AddLinearConstraint(weekend_work_days, 3, 4).OnlyEnforceIf(b_weekend_work)
        if group == 'MB': model.AddLinearConstraint(weekend_work_days, 4, 5).OnlyEnforceIf(b_weekend_work)
        if group in ['FB', 'MB']: assumptions.append(b_weekend_work)

    b_min_night_mb = model.NewBoolVar('min_2_mb_on_night_shift_daily')
    if male_bandung_indices and night_shift_indices:
        for d in days:
            model.Add(sum(shifts[e_idx, d, s_idx] for e_idx in male_bandung_indices for s_idx in night_shift_indices) >= 2).OnlyEnforceIf(b_min_night_mb)
    assumptions.append(b_min_night_mb)

    b_p9_weekend = model.NewBoolVar('p9_weekend_only_for_mb')
    if s_p9_idx is not None and male_bandung_indices:
        non_mb_indices = [i for i in range(len(employees_data)) if i not in male_bandung_indices]
        for d in days:
            if day_types[d] in ['Sabtu', 'Minggu']:
                for e_idx in non_mb_indices:
                    model.Add(shifts[e_idx, d, s_p9_idx] == 0).OnlyEnforceIf(b_p9_weekend)
    assumptions.append(b_p9_weekend)

    b_jakarta_weekend = model.NewBoolVar('jakarta_p8_libur_rule_on_weekend')
    if s_p8_idx is not None and s_libur_idx is not None:
        jakarta_indices = [employee_map[e[0]] for e in employees_data if e[1] in ['MJ', 'CJ']]
        if len(jakarta_indices) == 3:
            for d in days:
                if day_types[d] in ['Sabtu', 'Minggu']:
                    model.Add(sum(shifts[e_idx, d, s_p8_idx] for e_idx in jakarta_indices) == 1).OnlyEnforceIf(b_jakarta_weekend)
                    model.Add(sum(shifts[e_idx, d, s_libur_idx] for e_idx in jakarta_indices) == 2).OnlyEnforceIf(b_jakarta_weekend)
    assumptions.append(b_jakarta_weekend)

# =================================================================================
# FUNGSI DEBUGGING UTAMA
# =================================================================================
def debug_infeasible_schedule(employees_data, target_year, target_month, pre_assignment_requests, public_holidays):
    print("\n" + "="*30 + " MODE DEBUG AKTIF " + "="*30)
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
    month_prefix = f"{target_year}-{target_month:02d}-"
    holidays_in_month = [h for h in holiday_dates_str if h.startswith(month_prefix)]
    day_types = {}
    for d in days:
        day_num = d + 1
        current_date_str = f"{target_year}-{target_month:02d}-{day_num:02d}"
        day_of_week = calendar.weekday(target_year, target_month, day_num)
        if current_date_str in holiday_dates_str: day_types[d] = 'Minggu'
        elif day_of_week == 5: day_types[d] = 'Sabtu'
        elif day_of_week == 6: day_types[d] = 'Minggu'
        else: day_types[d] = 'Weekday'
    num_weekends = len([d for d, type in day_types.items() if type in ['Sabtu', 'Minggu']])
    max_work_days = num_days - num_weekends + len(holidays_in_month)
    min_work_days = num_days - num_weekends
    min_libur = num_weekends - len(holidays_in_month)
    assignable_roles = ['P6', 'P7', 'P8', 'P9', 'P10', 'P11', 'S12', 'M', 'SOCM', 'SOC2', 'SOC6']
    count_as_work_roles = assignable_roles + ['Cuti']
    non_work_statuses = ['Libur']
    all_shifts = assignable_roles + ['Libur', 'Cuti']
    shift_map = {name: i for i, name in enumerate(all_shifts)}
    demand = {
        'P6': {'Weekday': 2, 'Sabtu': 2, 'Minggu': 2},
        'P7': {'Weekday': 3, 'Sabtu': 2, 'Minggu': 1},
        'P8': {'Weekday': (4, 5), 'Sabtu': 2, 'Minggu': 1},
        'P9': {'Weekday': (3, 5), 'Sabtu': 2, 'Minggu': 1},
        'P10': {'Weekday': (2, 4), 'Sabtu': 0, 'Minggu': 0},
        'P11': {'Weekday': 1, 'Sabtu': 1, 'Minggu': 1},
        'S12': {'Weekday': 5, 'Sabtu': 3, 'Minggu': 3},
        'M': {'Weekday': 2, 'Sabtu': 2, 'Minggu': 2},
        'SOCM': {'Weekday': 1, 'Sabtu': 1, 'Minggu': 1},
        'SOC2': {'Weekday': 1, 'Sabtu': 1, 'Minggu': 1},
        'SOC6': {'Weekday': 1, 'Sabtu': 1, 'Minggu': 1},
    }
    forbidden_shifts_by_group = {
        'FB': ['P10', 'P11', 'S12', 'SOC2', 'SOCM'],
        'MJ': ['P6', 'P10', 'S12', 'SOC2', 'SOC6', 'SOCM'],
        'CJ': ['P6', 'P9', 'S12', 'SOC2', 'SOC6', 'SOCM']
    }
    female_employees = [e[0] for e in employees_data if e[1] in ['FB', 'CJ']]
    male_employees = [e[0] for e in employees_data if e[1] in ['MB', 'MJ']]
    male_bandung_indices = [employee_map[e[0]] for e in employees_data if e[1] == 'MB']
    night_shifts = ['M', 'SOCM']
    night_shift_indices = [shift_map[s] for s in night_shifts if s in shift_map]
    pre_assignments = {}
    for req in pre_assignment_requests:
        real_nip = str(req.get('nip'))
        jenis = req.get('jenis')
        tanggal_str = req.get('tanggal')
        if not (real_nip and jenis and tanggal_str): continue
        try:
            internal_code = nip_to_code_map.get(real_nip)
            if internal_code:
                e_idx = employee_map.get(internal_code)
                parsed_date = datetime.strptime(tanggal_str, '%Y-%m-%d')
                if parsed_date.year == target_year and parsed_date.month == target_month:
                    day_idx = parsed_date.day - 1
                    if e_idx is not None:
                        pre_assignments[(e_idx, day_idx)] = jenis
        except (ValueError, TypeError):
            continue
    model = cp_model.CpModel()
    shifts = {(employee_map[e], d, shift_map[s]): model.NewBoolVar(f's_{e}_{d}_{s}') for e in employees for d in days for s in all_shifts}
    assumptions = []
    apply_pre_assignments_debug(model, shifts, pre_assignments, shift_map, assumptions)
    apply_core_constraints_debug(model, shifts, employees, days, demand, day_types, shift_map, assumptions)
    #apply_employee_monthly_rules_debug(model, shifts, employees_data, days, assignable_roles, non_work_statuses, employee_map, shift_map, max_work_days, forbidden_shifts_by_group, num_weekends, min_work_days, min_libur, code_to_nip_map, assumptions)
    #apply_night_shift_rules_debug(model, shifts, employees_data, days, female_employees, night_shifts, employee_map, shift_map, assumptions)
    #apply_additional_constraints_debug(model, shifts, employees_data, days, day_types, employee_map, shift_map, male_employees, male_bandung_indices, night_shift_indices, public_holidays, target_year, target_month, assumptions)
    model.Maximize(sum(assumptions))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 300.0
    status = solver.Solve(model)
    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        print("\n--- ANALISIS KONFLIK CONSTRAINT ---")
        violated_constraints = [b.Name() for b in assumptions if solver.Value(b) == 0]
        if not violated_constraints:
            print("✅ Semua hard constraint tampaknya bisa dipenuhi.")
        else:
            print(f"❌ Ditemukan {len(violated_constraints)} KELOMPOK aturan yang dilanggar:")
            for name in violated_constraints:
                print(f"  - {name}")
    else:
        print("❌ Model tetap tidak feasible. Cek constraint yang paling dasar.")

# =================================================================================
# TITIK MASUK UTAMA PROGRAM (CONTOH PENGGUNAAN)
# =================================================================================
import logging

# Configure logging for debugging
logging.basicConfig(format="%(asctime)s - %(message)s", level=logging.DEBUG)
_logger = logging.getLogger(__name__)

def test_debug_infeasible_schedule_trivial():
    """Test with no requests and only 1 employee, should be feasible."""
    employees_data = [('B1', 'FB')]
    contoh_requests = []
    daftar_tanggal_merah = []
    try:
        _logger.debug("Running trivial debug_infeasible_schedule test")
        debug_infeasible_schedule(
            employees_data=employees_data,
            target_year=2025,
            target_month=8,
            pre_assignment_requests=contoh_requests,
            public_holidays=daftar_tanggal_merah
        )
        _logger.debug("Trivial test passed (no crash)")
    except Exception as e:
        _logger.error("Trivial test failed: %s", e)
        assert False, f"Trivial test failed: {e}"

def test_debug_infeasible_schedule_with_holiday():
    """Test with a public holiday and one employee."""
    employees_data = [('B1', 'FB')]
    contoh_requests = []
    daftar_tanggal_merah = ["2025-08-17"]
    try:
        _logger.debug("Running holiday debug_infeasible_schedule test")
        debug_infeasible_schedule(
            employees_data=employees_data,
            target_year=2025,
            target_month=8,
            pre_assignment_requests=contoh_requests,
            public_holidays=daftar_tanggal_merah
        )
        _logger.debug("Holiday test passed (no crash)")
    except Exception as e:
        _logger.error("Holiday test failed: %s", e)
        assert False, f"Holiday test failed: {e}"

def test_debug_infeasible_schedule_with_forbidden_shift():
    """Test with forbidden shift for NIP 400201."""
    employees_data = [('B30', 'MB')]
    contoh_requests = []
    daftar_tanggal_merah = []
    try:
        _logger.debug("Running forbidden shift debug_infeasible_schedule test")
        debug_infeasible_schedule(
            employees_data=employees_data,
            target_year=2025,
            target_month=8,
            pre_assignment_requests=contoh_requests,
            public_holidays=daftar_tanggal_merah
        )
        _logger.debug("Forbidden shift test passed (no crash)")
    except Exception as e:
        _logger.error("Forbidden shift test failed: %s", e)
        assert False, f"Forbidden shift test failed: {e}"

if __name__ == "__main__":
    # Run tests if this file is executed directly
    test_debug_infeasible_schedule_trivial()
    test_debug_infeasible_schedule_with_holiday()
    test_debug_infeasible_schedule_with_forbidden_shift()