"""
Парсер данных из JSON, полученного из Google Sheets.
Заменяет ExcelParser: загружает data.json, формирует schedule_data и список сотрудников.
Интерфейс полностью совместим с ExcelParser.
"""
import json
import os
import time
import logging
from datetime import datetime, timedelta
import calendar

import pytz

logger = logging.getLogger(__name__)

DATA_FILE = 'data.json'  # файл, который обновляет obras.py


def moscow_now():
    """Текущее московское время (наивный datetime)."""
    tz = pytz.timezone('Europe/Moscow')
    return datetime.now(tz).replace(tzinfo=None)


class GoogleSheetsParser:
    def __init__(self, json_path=DATA_FILE):
        self.json_path = json_path
        self.employees = []
        self.schedule_data = {}   # ключ: "YYYY-MM-DD", значение: список {"employee", "time"}
        self.last_update_time = 0
        self._load_data()

    def _load_data(self):
        """Читает data.json и строит внутренние структуры."""
        if not os.path.exists(self.json_path):
            logger.error(f"Файл {self.json_path} не найден!")
            self.employees = []
            self.schedule_data = {}
            return

        try:
            with open(self.json_path, 'r', encoding='utf-8') as f:
                raw_data = json.load(f)
        except Exception as e:
            logger.error(f"Ошибка чтения JSON: {e}")
            self.employees = []
            self.schedule_data = {}
            return

        # raw_data – список записей (словарей) из Google Sheets
        schedule = {}
        employees_set = set()

        for entry in raw_data:
            # Дата уже в формате "YYYY-MM-DD"
            date_str = entry.get("Дата", "").strip()
            employee = entry.get("Ответственный", "").strip()
            time_val = entry.get("Время", "").strip()

            # Пропускаем записи без даты, сотрудника или времени
            if not date_str or not employee or not time_val:
                continue
            # Проверяем, что время похоже на "HH:MM-HH:MM"
            if ':' not in time_val or '-' not in time_val:
                continue

            # Собираем уникальных сотрудников
            employees_set.add(employee)

            # Формируем запись слота
            if date_str not in schedule:
                schedule[date_str] = []
            schedule[date_str].append({
                'employee': employee,
                'time': time_val
            })

        self.schedule_data = schedule
        self.employees = sorted(list(employees_set))
        self.last_update_time = time.time()
        logger.info(f"Загружено {len(schedule)} дней, {len(self.employees)} сотрудников из {self.json_path}")

    def reload_data(self):
        """Принудительно перечитывает data.json."""
        self._load_data()

    def get_employees(self):
        return self.employees

    def get_schedule_for_date(self, date):
        """Расписание на дату (date – datetime)."""
        date_key = date.strftime('%Y-%m-%d')
        return self.schedule_data.get(date_key, [])

    # ---------- Все остальные методы копируются из ExcelParser БЕЗ изменений ----------
    # Просто скопируйте их из вашего excel_parser.py, заменив self.file_path / self.json_path
    # на self.json_path только в тех местах, где это нужно (здесь они не используются).

    def get_department_stats(self, year, month):
        from collections import defaultdict
        days_in_month = calendar.monthrange(year, month)[1]
        total_hours_all = 0.0
        employee_hours = defaultdict(float)
        unassigned_slots = []

        for day in range(1, days_in_month + 1):
            date = datetime(year, month, day)
            date_key = date.strftime('%Y-%m-%d')
            day_schedule = self.schedule_data.get(date_key, [])

            for entry in day_schedule:
                time_str = entry['time']
                employee = entry.get('employee')
                try:
                    start_str, end_str = time_str.split('-')
                    start_h, start_m = map(int, start_str.split(':'))
                    end_h, end_m = map(int, end_str.split(':'))
                    if end_h < start_h or (end_h == start_h and end_m < start_m):
                        end_h += 24
                    hours = (end_h * 60 + end_m - start_h * 60 - start_m) / 60.0
                except:
                    continue

                total_hours_all += hours
                if employee and employee not in ('nan', 'None', ''):
                    employee_hours[employee] += hours
                else:
                    date_str_short = date.strftime('%d.%m')
                    unassigned_slots.append({'date': date_str_short, 'time': time_str})

        total_hours_all = round(total_hours_all, 1)
        employee_hours = {name: round(h, 1) for name, h in employee_hours.items()}
        return {
            'total_hours': total_hours_all,
            'employee_hours': employee_hours,
            'unassigned_slots': unassigned_slots
        }

    def get_employee_schedule(self, employee_name, date):
        day_schedule = self.get_schedule_for_date(date)
        if not day_schedule:
            return None
        slots = [entry['time'] for entry in day_schedule if entry['employee'] == employee_name]
        if not slots:
            return None
        parsed = []
        for slot in slots:
            try:
                start_str, end_str = slot.split('-')
                start_h, start_m = map(int, start_str.split(':'))
                end_h, end_m = map(int, end_str.split(':'))
                if end_h < start_h or (end_h == start_h and end_m < start_m):
                    end_h += 24
                start_min = start_h * 60 + start_m
                end_min = end_h * 60 + end_m
                parsed.append({'start': start_min, 'end': end_min, 'start_str': start_str, 'end_str': end_str})
            except:
                continue
        if not parsed:
            return None
        parsed.sort(key=lambda x: x['start'])
        combined = []
        current = parsed[0].copy()
        for i in range(1, len(parsed)):
            if parsed[i]['start'] == current['end']:
                current['end'] = parsed[i]['end']
                current['end_str'] = parsed[i]['end_str']
            else:
                combined.append((current['start_str'], current['end_str']))
                current = parsed[i].copy()
        combined.append((current['start_str'], current['end_str']))
        result = []
        for i, (s, e) in enumerate(combined, 1):
            result.append({'shift_number': i, 'time': f"{s}-{e}"})
        return result

    def get_current_employee(self):
        now = moscow_now()
        day_schedule = self.get_schedule_for_date(now)
        if not day_schedule:
            return None
        employees_today = set(entry['employee'] for entry in day_schedule)
        current_minutes = now.hour * 60 + now.minute
        for emp in employees_today:
            shifts = self.get_employee_schedule(emp, now)
            if not shifts:
                continue
            for shift in shifts:
                try:
                    start_str, end_str = shift['time'].split('-')
                    start_h, start_m = map(int, start_str.split(':'))
                    end_h, end_m = map(int, end_str.split(':'))
                    start_min = start_h * 60 + start_m
                    end_min = end_h * 60 + end_m
                    if start_min <= current_minutes < end_min:
                        formatted_time = f"{start_h:02d}:{start_m:02d}-{end_h:02d}:{end_m:02d}"
                        return {'name': emp, 'time': formatted_time}
                except:
                    continue
        return None

    def get_available_months(self):
        months_set = set()
        for date_key in self.schedule_data.keys():
            try:
                dt = datetime.strptime(date_key, '%Y-%m-%d')
                if dt.year >= 2025:
                    months_set.add((dt.year, dt.month))
            except:
                continue
        month_names_ru = {
            1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель',
            5: 'Май', 6: 'Июнь', 7: 'Июль', 8: 'Август',
            9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь'
        }
        months = []
        for year, month in sorted(months_set, reverse=True):
            months.append({
                'year': year,
                'month': month,
                'month_name': month_names_ru[month],
                'name': f"{month_names_ru[month]} {year}"
            })
        return months

    def get_employee_stats_for_month(self, employee_name, year, month):
        days_in_month = calendar.monthrange(year, month)[1]
        total_hours = 0
        worked_days = set()
        now = moscow_now()
        for day in range(1, days_in_month + 1):
            date = datetime(year, month, day)
            shifts = self.get_employee_schedule(employee_name, date)
            if shifts:
                worked_days.add(day)
                for shift in shifts:
                    try:
                        start_str, end_str = shift['time'].split('-')
                        start_h, start_m = map(int, start_str.split(':'))
                        end_h, end_m = map(int, end_str.split(':'))
                        if end_h < start_h or (end_h == start_h and end_m < start_m):
                            end_h += 24
                        hours = (end_h * 60 + end_m - start_h * 60 - start_m) / 60
                        total_hours += hours
                    except:
                        continue
        if year < now.year or (year == now.year and month < now.month):
            worked_hours = total_hours
            remaining_hours = 0
        elif year == now.year and month == now.month:
            worked_hours = 0
            for day in range(1, now.day):
                date = datetime(year, month, day)
                shifts = self.get_employee_schedule(employee_name, date)
                if shifts:
                    for shift in shifts:
                        try:
                            start_str, end_str = shift['time'].split('-')
                            start_h, start_m = map(int, start_str.split(':'))
                            end_h, end_m = map(int, end_str.split(':'))
                            if end_h < start_h or (end_h == start_h and end_m < start_m):
                                end_h += 24
                            hours = (end_h * 60 + end_m - start_h * 60 - start_m) / 60
                            worked_hours += hours
                        except:
                            continue
            remaining_hours = max(0, total_hours - worked_hours)
        else:
            worked_hours = 0
            remaining_hours = total_hours
        return {
            'total_hours': round(total_hours, 1),
            'worked_hours': round(worked_hours, 1),
            'remaining_hours': round(remaining_hours, 1),
            'worked_days': len(worked_days),
            'salary': round(total_hours * 160),
            'earned_salary': round(worked_hours * 160)
        }

    def get_week_schedule(self, start_date, employee_name=None):
        week = {}
        for i in range(7):
            date = start_date + timedelta(days=i)
            date_key = date.strftime('%Y-%m-%d')
            if employee_name:
                shifts = self.get_employee_schedule(employee_name, date)
            else:
                shifts = self.get_schedule_for_date(date)
            week[date_key] = {
                'date': date,
                'weekday': date.weekday(),
                'schedule': shifts
            }
        return week

    def apply_substitutions(self, substitutions: list):
        for sub in substitutions:
            date_str = sub['date_str']
            from_hour = int(sub['from_hour'])
            to_hour = int(sub['to_hour'])
            requester_name = sub['requester_name']
            substitute_name = sub['substitute_name']
            day_entries = self.schedule_data.get(date_str, [])
            for entry in day_entries:
                if entry.get('employee') != requester_name:
                    continue
                try:
                    start_str, end_str = entry['time'].split('-')
                    slot_start_h = int(start_str.split(':')[0])
                    slot_end_h = int(end_str.split(':')[0])
                    if slot_end_h < slot_start_h:
                        slot_end_h += 24
                except:
                    continue
                if slot_start_h >= from_hour and slot_end_h <= to_hour:
                    entry['employee'] = substitute_name
        logger.info(f"Применено {len(substitutions)} подмен к расписанию в памяти")