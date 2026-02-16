"""
Модуль для работы с Excel файлом графика смен.
"""
import pandas as pd
import json
import logging
from datetime import datetime, timedelta
import calendar
from pathlib import Path
import time
import os
import glob

logger = logging.getLogger(__name__)


class ExcelParser:
    """Парсер Excel файла с графиком смен"""

    def __init__(self, file_path):
        self.file_path = file_path
        self.json_path = 'schedule_data.json'
        self.employees = []
        self.schedule_data = {}
        self.last_update_time = 0
        self._load_or_parse()

    def _load_or_parse(self):
        """Загружает данные из JSON, если файл существует и не устарел, иначе парсит Excel."""
        try:
            if os.path.exists(self.json_path) and os.path.exists(self.file_path):
                json_mtime = os.path.getmtime(self.json_path)
                excel_mtime = os.path.getmtime(self.file_path)
                if json_mtime > excel_mtime:
                    self._load_from_json()
                    logger.info("Данные загружены из JSON-файла")
                    return
            self._parse_all_and_save()
        except Exception as e:
            logger.error(f"Ошибка в _load_or_parse: {e}")
            if os.path.exists(self.json_path):
                self._load_from_json()
            else:
                self._parse_all_and_save()

    def _find_columns(self, df):
        """Находит колонки с датой, временем и ответственным (более гибкий поиск)"""
        date_col = None
        time_col = None
        emp_col = None

        # Варианты названий колонок
        date_variants = ['дата', 'date', 'день', 'day', 'число']
        time_variants = ['время', 'time', 'часы', 'hours', 'период', 'period']
        emp_variants = ['ответственный', 'responsible', 'сотрудник', 'employee', 'фио', 'fio', 'имя', 'name']

        for col in df.columns:
            col_str = str(col).lower().strip()

            # Поиск колонки с датой
            if not date_col:
                for variant in date_variants:
                    if variant in col_str:
                        date_col = col
                        break

            # Поиск колонки с временем
            if not time_col:
                for variant in time_variants:
                    if variant in col_str:
                        time_col = col
                        break

            # Поиск колонки с ответственным
            if not emp_col:
                for variant in emp_variants:
                    if variant in col_str:
                        emp_col = col
                        break

        return date_col, time_col, emp_col

    def _parse_all_and_save(self):
        """Парсит все листы Excel и сохраняет в JSON."""
        logger.info(f"Начинаем полный парсинг Excel файла: {self.file_path}")
        try:
            if not os.path.exists(self.file_path):
                logger.error(f"Excel файл не найден: {self.file_path}")
                return

            xl_file = pd.ExcelFile(self.file_path)
            all_sheets = xl_file.sheet_names

            # Загружаем список сотрудников из листа "Служебный лист 2"
            try:
                # Пробуем разные варианты названия служебного листа
                service_sheet_names = ['Служебный лист 2', 'Служебный', 'Service', 'Staff', 'Сотрудники']
                service_df = None

                for sheet_name in service_sheet_names:
                    try:
                        service_df = pd.read_excel(self.file_path, sheet_name=sheet_name)
                        logger.info(f"Найден лист с сотрудниками: {sheet_name}")
                        break
                    except:
                        continue

                if service_df is not None:
                    # Берем первую непустую колонку
                    for col in service_df.columns:
                        if service_df[col].notna().any():
                            self.employees = service_df[col].dropna().tolist()
                            self.employees = [str(e).strip() for e in self.employees if str(e).strip()]
                            logger.info(f"Загружено {len(self.employees)} сотрудников из колонки '{col}'")
                            break
                else:
                    logger.warning("Не найден лист с сотрудниками")

            except Exception as e:
                logger.error(f"Ошибка загрузки списка сотрудников: {e}")
                self.employees = []

            # Месяцы на русском
            month_names_ru = {
                'Январь': 1, 'Февраль': 2, 'Март': 3, 'Апрель': 4,
                'Май': 5, 'Июнь': 6, 'Июль': 7, 'Август': 8,
                'Сентябрь': 9, 'Октябрь': 10, 'Ноябрь': 11, 'Декабрь': 12
            }

            schedule = {}

            for sheet in all_sheets:
                # Пропускаем служебные листы
                if any(x in sheet.lower() for x in ['служебный', 'отчет', 'информация', 'тикеты', 'service']):
                    logger.info(f"Пропускаем служебный лист: {sheet}")
                    continue

                logger.info(f"Обрабатываем лист: {sheet}")

                # Определяем месяц и год из названия листа
                year = None
                month = None

                # Пробуем разные форматы названий
                sheet_lower = sheet.lower()
                for month_name, month_num in month_names_ru.items():
                    if month_name.lower() in sheet_lower:
                        month = month_num
                        # Ищем год в названии
                        import re
                        year_match = re.search(r'20\d{2}|\d{2}', sheet)
                        if year_match:
                            year_str = year_match.group()
                            year = 2000 + int(year_str) if len(year_str) == 2 else int(year_str)
                        break

                # Читаем лист
                try:
                    df = pd.read_excel(self.file_path, sheet_name=sheet)
                except Exception as e:
                    logger.error(f"Не удалось прочитать лист {sheet}: {e}")
                    continue

                # Находим колонки
                date_col, time_col, emp_col = self._find_columns(df)

                if not date_col or not time_col or not emp_col:
                    logger.warning(f"В листе {sheet} не найдены нужные колонки")
                    logger.warning(f"Доступные колонки: {list(df.columns)}")
                    continue

                logger.info(f"В листе {sheet} найдены колонки: дата='{date_col}', время='{time_col}', ответственный='{emp_col}'")

                # Проходим по строкам
                for idx, row in df.iterrows():
                    # Получаем дату
                    date_val = row.get(date_col)
                    if pd.isna(date_val):
                        continue

                    # Преобразуем дату
                    try:
                        if isinstance(date_val, (datetime, pd.Timestamp)):
                            current_date = date_val
                        else:
                            current_date = pd.to_datetime(date_val)

                        if isinstance(current_date, pd.Timestamp):
                            current_date = current_date.to_pydatetime()
                    except:
                        continue

                    # Получаем время и ответственного
                    time_val = row.get(time_col)
                    emp_val = row.get(emp_col)

                    if pd.isna(time_val) or pd.isna(emp_val):
                        continue

                    time_str = str(time_val).strip()
                    emp_str = str(emp_val).strip()

                    if not time_str or not emp_str or emp_str.lower() in ('nan', 'none', '', 'ответственный'):
                        continue

                    # Проверяем формат времени
                    if ':' not in time_str or '-' not in time_str:
                        continue

                    # Сохраняем запись
                    date_key = current_date.strftime('%Y-%m-%d')
                    if date_key not in schedule:
                        schedule[date_key] = []
                    schedule[date_key].append({
                        'employee': emp_str,
                        'time': time_str
                    })

            self.schedule_data = schedule

            # Сохраняем в JSON
            with open(self.json_path, 'w', encoding='utf-8') as f:
                json.dump({
                    'employees': self.employees,
                    'schedule': self.schedule_data
                }, f, ensure_ascii=False, indent=2)

            self.last_update_time = time.time()
            logger.info(f"Парсинг завершён. Загружено сотрудников: {len(self.employees)}, дней с данными: {len(self.schedule_data)}")

        except Exception as e:
            logger.error(f"Ошибка при парсинге Excel: {e}")
            import traceback
            traceback.print_exc()
            if os.path.exists(self.json_path):
                self._load_from_json()

    def _load_from_json(self):
        """Загружает данные из JSON-файла."""
        try:
            with open(self.json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.employees = data.get('employees', [])
            self.schedule_data = data.get('schedule', {})
            self.last_update_time = time.time()
            logger.info(f"Данные загружены из {self.json_path}. Сотрудников: {len(self.employees)}")
        except Exception as e:
            logger.error(f"Ошибка загрузки из JSON: {e}")
            self.employees = []
            self.schedule_data = {}

    def reload_data(self):
        """Принудительная перезагрузка данных из Excel."""
        self._parse_all_and_save()

    def get_employees(self):
        """Возвращает список сотрудников"""
        if not self.employees:
            logger.warning("Список сотрудников пуст!")
        return self.employees

    def get_schedule_for_date(self, date):
        """Получает расписание на конкретную дату"""
        date_key = date.strftime('%Y-%m-%d')
        result = self.schedule_data.get(date_key, [])
        logger.info(f"get_schedule_for_date({date_key}): найдено {len(result)} записей")
        if result:
            logger.info(f"Пример: {result[0]}")
        return result

    def get_department_stats(self, year, month):
        """
        Возвращает статистику отдела за указанный месяц, используя уже загруженные данные.
        """
        from collections import defaultdict
        import calendar

        # Собираем все даты месяца
        days_in_month = calendar.monthrange(year, month)[1]
        total_hours_all = 0.0
        employee_hours = defaultdict(float)
        unassigned_slots = []  # список (date_str, time_slot)

        # Проходим по всем дням месяца
        for day in range(1, days_in_month + 1):
            date = datetime(year, month, day)
            date_key = date.strftime('%Y-%m-%d')
            day_schedule = self.schedule_data.get(date_key, [])

            for entry in day_schedule:
                time_str = entry['time']
                employee = entry.get('employee')

                # Считаем длительность
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
                    # нет ответственного
                    date_str = date.strftime('%d.%m')
                    unassigned_slots.append({
                        'date': date_str,
                        'time': time_str
                    })

        # Округляем
        total_hours_all = round(total_hours_all, 1)
        employee_hours = {name: round(h, 1) for name, h in employee_hours.items()}

        return {
            'total_hours': total_hours_all,
            'employee_hours': employee_hours,
            'unassigned_slots': unassigned_slots
        }

    def get_employee_schedule(self, employee_name, date):
        """Возвращает список смен сотрудника на дату (объединённых)."""
        day_schedule = self.get_schedule_for_date(date)
        if not day_schedule:
            return None
        slots = [entry['time'] for entry in day_schedule if entry['employee'] == employee_name]
        if not slots:
            return None
        # Объединяем последовательные слоты
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
                parsed.append({
                    'start': start_min,
                    'end': end_min,
                    'start_str': start_str,
                    'end_str': end_str
                })
            except:
                continue
        if not parsed:
            return None
        parsed.sort(key=lambda x: x['start'])
        # объединение
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
            result.append({
                'shift_number': i,
                'time': f"{s}-{e}"
            })
        return result

    def get_current_employee(self):
        """Определяет текущего дежурного с учётом объединения всех его смен на день."""
        now = datetime.now()
        day_schedule = self.get_schedule_for_date(now)
        if not day_schedule:
            return None

        # Уникальные имена сотрудников, работающих сегодня
        employees_today = set(entry['employee'] for entry in day_schedule)
        current_minutes = now.hour * 60 + now.minute

        for emp in employees_today:
            shifts = self.get_employee_schedule(emp, now)  # уже объединённые смены
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
                        # Форматируем время с ведущим нулём
                        formatted_time = f"{start_h:02d}:{start_m:02d}-{end_h:02d}:{end_m:02d}"
                        return {'name': emp, 'time': formatted_time}
                except:
                    continue
        return None

    def get_available_months(self):
        """Возвращает список доступных месяцев (только с 2025 года)."""
        months_set = set()
        for date_key in self.schedule_data.keys():
            try:
                dt = datetime.strptime(date_key, '%Y-%m-%d')
                # Добавляем только если год >= 2025
                if dt.year >= 2025:
                    months_set.add((dt.year, dt.month))
            except:
                continue
        months = []
        month_names_ru = {
            1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель',
            5: 'Май', 6: 'Июнь', 7: 'Июль', 8: 'Август',
            9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь'
        }
        for year, month in sorted(months_set, reverse=True):
            months.append({
                'year': year,
                'month': month,
                'month_name': month_names_ru[month],
                'name': f"{month_names_ru[month]} {year}"
            })
        return months

    def get_employee_stats_for_month(self, employee_name, year, month):
        """Статистика за месяц."""
        days_in_month = calendar.monthrange(year, month)[1]
        total_hours = 0
        worked_days = set()
        now = datetime.now()

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

        # Расчет отработанных часов
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
        """Расписание на неделю (7 дней)."""
        week = {}
        for i in range(7):
            date = start_date + timedelta(days=i)
            if employee_name:
                shifts = self.get_employee_schedule(employee_name, date)
            else:
                shifts = self.get_schedule_for_date(date)
            week[date.strftime('%Y-%m-%d')] = {
                'date': date,
                'weekday': date.weekday(),
                'schedule': shifts
            }
        return week