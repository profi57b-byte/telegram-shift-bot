"""
Telegram бот для управления графиком смен L1.5
Версия 2.0 - финальная
"""
import os
import logging
from datetime import datetime, timedelta, time
import asyncio
import sys
import glob
from pathlib import Path
from typing import Optional

import pytz  # добавлено для работы с часовыми поясами

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

from excel_parser import ExcelParser
from logger import BotLogger
from database import UserDatabase
from access_control import AccessControl

# Конфигурация
BOT_TOKEN = os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN')
LOG_CHAT_ID = '-5242231135'  # Ваш ID чата для логов
EXCEL_FILE = os.getenv('EXCEL_FILE', 'graph.xlsx')

# Инициализация
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
excel_parser = ExcelParser(EXCEL_FILE)
db = UserDatabase()
access_control = AccessControl()
bot_logger = BotLogger(bot, LOG_CHAT_ID)
# Активные счётчики смен: user_id -> {message_id, chat_id, shift_start, shift_end}
active_shift_counters = {}

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def moscow_now():
    """Возвращает текущее московское время (GMT+3) как наивный datetime."""
    tz = pytz.timezone('Europe/Moscow')
    return datetime.now(tz).replace(tzinfo=None)


# FSM States
class UserStates(StatesGroup):
    choosing_name = State()
    main_menu = State()
    choosing_date = State()
    choosing_stats_month = State()
    choosing_daily_remind_time = State()
    director_choosing_employee = State()


# Функция поиска Excel файла
def find_excel_file():
    """Ищет любой Excel файл в текущей директории"""
    # Сначала проверяем переменную окружения
    env_file = os.getenv('EXCEL_FILE')
    if env_file and Path(env_file).exists():
        return env_file

    # Ищем .xlsx файлы
    xlsx_files = glob.glob("*.xlsx")
    if xlsx_files:
        return xlsx_files[0]

    # Ищем .xls файлы
    xls_files = glob.glob("*.xls")
    if xls_files:
        return xls_files[0]

    return None

# Находим Excel файл
EXCEL_FILE = find_excel_file()
if not EXCEL_FILE:
    print("❌ КРИТИЧЕСКАЯ ОШИБКА: Не найден Excel файл!")
    print("📝 Поместите файл графика (.xlsx или .xls) в директорию бота")
    sys.exit(1)

print(f"📊 Загружен Excel файл: {EXCEL_FILE}")

# Middleware для логирования всех входящих сообщений (должен быть ПЕРВЫМ)
@dp.message.middleware()
async def log_all_messages_middleware(handler, event: types.Message, data: dict):
    user_id = event.from_user.id
    # Определяем роль пользователя
    if access_control.is_admin(user_id):
        role = "👑 АДМИН"
    elif await access_control.is_director(user_id):
        role = "🎯 РУКОВОДИТЕЛЬ"
    else:
        role = "👤 ПОЛЬЗОВАТЕЛЬ"

    # Логируем сообщение (метод log_incoming_message должен быть в logger.py)
    await bot_logger.log_incoming_message(event, role)

    # Передаём управление дальше по цепочке middleware
    return await handler(event, data)


# Middleware для проверки доступа
@dp.message.middleware()
async def access_check_middleware(handler, event: types.Message, data: dict):
    """Middleware для проверки доступа к боту"""
    user_id = event.from_user.id

    # Админ всегда имеет доступ
    if access_control.is_admin(user_id):
        return await handler(event, data)

    # Проверяем, является ли пользователь руководителем
    if await access_control.is_director(user_id):
        return await handler(event, data)

    # Проверка обычного доступа
    has_access = await access_control.check_access(user_id)

    if not has_access and not (event.text and event.text.startswith('/start')):
        admin_info = access_control.get_admin_info()
        await event.answer(
            "🚫 <b>Доступ к боту ограничен</b>\n\n"
            f"Для получения доступа обратитесь к администратору бота:\n"
            f"👤 {admin_info['mention']}\n"
            f"ID: <code>{admin_info['id']}</code>",
            parse_mode="HTML"
        )
        await bot_logger.log_action(
            event.from_user.username or str(user_id),
            f"❌ Попытка доступа без разрешения (ID: {user_id})"
        )
        return

    if event.text and event.text.startswith('/start') and not has_access:
        admin_info = access_control.get_admin_info()
        await event.answer(
            "🚫 <b>Доступ к боту ограничен</b>\n\n"
            f"Для получения доступа обратитесь к администратору:\n"
            f"👤 {admin_info['mention']}\n\n"
            f"Укажите ваш Telegram ID: <code>{user_id}</code>",
            parse_mode="HTML"
        )
        return

    return await handler(event, data)


@dp.message.middleware()
async def load_user_middleware(handler, event: types.Message, data: dict):
    """Middleware для загрузки данных пользователя"""
    # Получаем state из data (он уже должен быть там от FSM middleware)
    state: FSMContext = data.get('state')

    if not state:
        # Если state нет, создаем новый
        state = FSMContext(
            storage=dp.storage,
            key=dp.fsm.get_key(
                chat_id=event.chat.id,
                user_id=event.from_user.id
            )
        )
        data['state'] = state

    user_id = event.from_user.id

    # Получаем текущее состояние
    current_state = await state.get_state()

    # Проверяем, не находится ли пользователь в процессе выбора имени
    if current_state == UserStates.choosing_name:
        return await handler(event, data)

    # Проверяем, является ли пользователь директором
    is_director = await access_control.is_director(user_id)
    if is_director:
        await state.update_data(is_director=True)
        if current_state is None:
            await state.set_state(UserStates.main_menu)
        return await handler(event, data)

    # Загружаем данные из БД
    user_data_db = await db.get_user(user_id)
    if user_data_db and user_data_db.get('employee_name'):
        # Сохраняем имя в состояние
        await state.update_data(employee_name=user_data_db['employee_name'])

        # Если состояние не установлено, переходим в главное меню
        if current_state is None:
            await state.set_state(UserStates.main_menu)

    return await handler(event, data)

# Клавиатуры
def get_name_keyboard(employees):
    """Клавиатура выбора имени сотрудника"""
    keyboard = []
    for emp in employees:
        keyboard.append([KeyboardButton(text=emp)])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True, one_time_keyboard=True)


def get_main_menu_keyboard(is_director=False):
    if is_director:
        keyboard = [
            [KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="📅 Завтра")],
            [KeyboardButton(text="📅 Неделя"), KeyboardButton(text="📅 Дата")],
            [KeyboardButton(text="👥 Кто на смене?")],
            [KeyboardButton(text="📊 По сотрудникам"), KeyboardButton(text="📊 Отдел")],
            [KeyboardButton(text="ℹ️ О боте")]
        ]
    else:
        # полное меню для сотрудников
        keyboard = [
            [KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="📅 Завтра")],
            [KeyboardButton(text="📅 Неделя"), KeyboardButton(text="📅 Дата")],
            [KeyboardButton(text="👥 Кто на смене?")],
            [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="⚙️ Настройки")],
            [KeyboardButton(text="ℹ️ О боте")]
        ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_date_keyboard(year=None, month=None):
    """Клавиатура выбора даты с навигацией по месяцам"""
    today = moscow_now()  # изменено

    if year is None or month is None:
        year = today.year
        month = today.month

    keyboard = []

    month_names = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
                   'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']

    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1

    keyboard.append([
        InlineKeyboardButton(text="◀️", callback_data=f"cal_nav:{prev_year}:{prev_month}"),
        InlineKeyboardButton(text=f"📆 {month_names[month - 1]} {year}", callback_data="ignore"),
        InlineKeyboardButton(text="▶️", callback_data=f"cal_nav:{next_year}:{next_month}")
    ])

    keyboard.append([
        InlineKeyboardButton(text="Пн", callback_data="ignore"),
        InlineKeyboardButton(text="Вт", callback_data="ignore"),
        InlineKeyboardButton(text="Ср", callback_data="ignore"),
        InlineKeyboardButton(text="Чт", callback_data="ignore"),
        InlineKeyboardButton(text="Пт", callback_data="ignore"),
        InlineKeyboardButton(text="Сб", callback_data="ignore"),
        InlineKeyboardButton(text="Вс", callback_data="ignore"),
    ])

    first_day = datetime(year, month, 1)
    import calendar
    days_in_month = calendar.monthrange(year, month)[1]

    start_weekday = first_day.weekday()

    week = []
    for _ in range(start_weekday):
        week.append(InlineKeyboardButton(text=" ", callback_data="ignore"))

    for day in range(1, days_in_month + 1):
        date_str = f"{year}-{month:02d}-{day:02d}"
        week.append(InlineKeyboardButton(text=str(day), callback_data=f"date:{date_str}"))

        if len(week) == 7:
            keyboard.append(week)
            week = []

    if week:
        while len(week) < 7:
            week.append(InlineKeyboardButton(text=" ", callback_data="ignore"))
        keyboard.append(week)

    keyboard.append([InlineKeyboardButton(text="◀️ Главное меню", callback_data="back_to_menu")])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# Вспомогательные функции
def _get_weekday(date):
    """Получить название дня недели"""
    weekdays = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
    return weekdays[date.weekday()]

def _pad_hour(time_str):
    """Добавляет ведущий ноль к часу, если нужно."""
    if ':' in time_str:
        h, m = time_str.split(':')
        return f"{int(h):02d}:{m}"
    return time_str


# Обработчики команд
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    """Обработчик команды /start"""
    user_id = message.from_user.id
    is_admin = access_control.is_admin(user_id)
    is_director = await access_control.is_director(user_id)

    admin_text = " 👑 <b>(Админ)</b>" if is_admin else ""
    director_text = " 🎯 <b>(Руководитель)</b>" if is_director else ""

    await bot_logger.log_action(
        message.from_user.username or str(user_id),
        f"Запустил бота{' [ADMIN]' if is_admin else ''}{' [DIRECTOR]' if is_director else ''}"
    )

    # Если пользователь – руководитель, сразу показываем его меню
    if is_director:
        await state.update_data(is_director=True)
        await state.set_state(UserStates.main_menu)
        await message.answer(
            f"👋 Добро пожаловать!{admin_text}{director_text}\n\n"
            "Вам доступен расширенный функционал.",
            reply_markup=get_main_menu_keyboard(is_director=True),
            parse_mode="HTML"
        )
        return

    # Для обычных пользователей (L1.5) – проверяем БД
    user_data_db = await db.get_user(user_id)

    if user_data_db and user_data_db['employee_name']:
        await state.update_data(employee_name=user_data_db['employee_name'])
        employee_name = user_data_db['employee_name']
        welcome_text = f"👋 С возвращением{admin_text}, {employee_name}!\n\n"
        welcome_text += "Ваши данные восстановлены.\n"
        welcome_text += "Можете изменить настройки через меню ⚙️"

        await state.set_state(UserStates.main_menu)
        await message.answer(
            welcome_text,
            reply_markup=get_main_menu_keyboard(is_director=False),
            parse_mode="HTML"
        )
    else:
        # Новый пользователь – выбор имени
        await state.set_state(UserStates.choosing_name)
        employees = excel_parser.get_employees()
        if not employees:
            await message.answer(
                "⚠️ Не удалось загрузить список сотрудников.\n"
                "Попробуйте позже или обратитесь к администратору."
            )
            return
        await message.answer(
            f"👋 Добро пожаловать в бот управления графиком L1.5!{admin_text}\n\n"
            "Выберите ваше имя из списка:",
            reply_markup=get_name_keyboard(employees),
            parse_mode="HTML"
        )

@dp.message(StateFilter(UserStates.main_menu), F.text == "📊 Отдел")
async def department_stats_start(message: types.Message, state: FSMContext):
    """Начало статистики отдела: выбор месяца."""
    user_id = message.from_user.id
    is_director = await access_control.is_director(user_id)
    if not is_director:
        await message.answer("⛔ Эта функция доступна только руководителям.")
        return

    available_months = excel_parser.get_available_months()
    if not available_months:
        await message.answer("⚠️ Нет доступных месяцев.")
        return

    # Создаём инлайн-кнопки с месяцами
    keyboard = []
    for month_data in available_months[:12]:  # покажем много
        month_name = month_data['month_name']
        year = month_data['year']
        callback_data = f"dept_stats:{year}:{month_data['month']}"
        keyboard.append([
            InlineKeyboardButton(
                text=f"{month_name} {year}",
                callback_data=callback_data
            )
        ])
    keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")])

    await message.answer(
        "📊 <b>Выберите месяц для статистики отдела:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("dept_stats:"))
async def process_department_stats(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    is_director = await access_control.is_director(user_id)
    if not is_director:
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    _, year_str, month_str = callback.data.split(":")
    year = int(year_str)
    month = int(month_str)

    # Получаем статистику
    stats = excel_parser.get_department_stats(year, month)
    if not stats:
        await callback.message.edit_text("⚠️ Данные за этот месяц недоступны.")
        return

    total = stats['total_hours']
    employee_hours = stats['employee_hours']
    unassigned = stats['unassigned_slots']

    month_names = {
        1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель',
        5: 'Май', 6: 'Июнь', 7: 'Июль', 8: 'Август',
        9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь'
    }
    response = f"📊 <b>Статистика отдела за {month_names[month]} {year}</b>\n\n"
    response += f"Всего часов в месяце: <b>{total:.1f}</b>\n\n"

    # Сотрудники (только те, у кого >0)
    if employee_hours:
        response += "<b>Часы по сотрудникам:</b>\n"
        for name, hours in sorted(employee_hours.items()):
            response += f"• {name}: {hours:.1f} ч\n"
    else:
        response += "Нет данных по сотрудникам.\n"

    # Незанятые часы
    if unassigned:
        response += f"\n<b>Незанятые часы ({len(unassigned)}):</b>\n"
        from collections import defaultdict
        by_date = defaultdict(list)
        for slot in unassigned:
            by_date[slot['date']].append(slot['time'])
        for date, times in sorted(by_date.items()):
            times_str = ", ".join(times)
            response += f"{date}: {times_str}\n"
    else:
        response += "\n✅ Все смены распределены."

    # Кнопки: Назад к месяцам и Главное меню
    keyboard = [
        [InlineKeyboardButton(text="◀️ К выбору месяца", callback_data="back_to_dept_months")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_menu")]
    ]
    await callback.message.edit_text(
        response,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await bot_logger.log_action(
        callback.from_user.username or str(callback.from_user.id),
        f"Запросил статистику отдела за {month_names[month]} {year}"
    )

@dp.callback_query(F.data == "back_to_dept_months")
async def back_to_dept_months(callback: types.CallbackQuery, state: FSMContext):
    # Повторно показываем список месяцев
    available_months = excel_parser.get_available_months()
    keyboard = []
    for month_data in available_months[:12]:
        month_name = month_data['month_name']
        year = month_data['year']
        callback_data = f"dept_stats:{year}:{month_data['month']}"
        keyboard.append([
            InlineKeyboardButton(
                text=f"{month_name} {year}",
                callback_data=callback_data
            )
        ])
    keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")])
    await callback.message.edit_text(
        "📊 <b>Выберите месяц для статистики отдела:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML"
    )

@dp.message(StateFilter(UserStates.main_menu), F.text == "📊 По сотрудникам")
async def director_stats_choose_employee(message: types.Message, state: FSMContext):
    """Показываем список сотрудников для выбора (руководитель)."""
    # Проверяем, что пользователь – руководитель (можно по флагу в состоянии или через БД)
    user_data = await state.get_data()
    is_director = user_data.get('is_director', False) or await access_control.is_director(message.from_user.id)
    if not is_director:
        await message.answer("⛔ Эта функция доступна только руководителям.")
        return

    employees = excel_parser.get_employees()
    if not employees:
        await message.answer("⚠️ Нет списка сотрудников.")
        return

    # Создаём инлайн-клавиатуру с сотрудниками
    keyboard = []
    for emp in employees:
        keyboard.append([InlineKeyboardButton(text=emp, callback_data=f"dir_stats_emp:{emp}")])
    # Добавляем кнопку "Назад"
    keyboard.append([InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_to_menu")])

    await message.answer(
        "📊 Выберите сотрудника для просмотра статистики:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    # Можно установить состояние, но не обязательно
    await state.set_state(UserStates.director_choosing_employee)

@dp.callback_query(F.data.startswith("dir_stats_emp:"))
async def director_stats_choose_month(callback: types.CallbackQuery, state: FSMContext):
    """После выбора сотрудника показываем список месяцев (как в /stats)."""
    employee_name = callback.data.split(":", 1)[1]
    await state.update_data(selected_employee=employee_name)

    # Получаем доступные месяцы
    available_months = excel_parser.get_available_months()
    if not available_months:
        await callback.message.edit_text("⚠️ Нет доступных месяцев.")
        return

    # Создаём инлайн-кнопки для месяцев
    keyboard = []
    for month_data in available_months[:12]:  # можно показать последние 12
        month_name = month_data['month_name']
        year = month_data['year']
        callback_data = f"dir_stats_month:{year}:{month_data['month']}"
        keyboard.append([InlineKeyboardButton(text=f"{month_name} {year}", callback_data=callback_data)])

    # Кнопка "Назад" к списку сотрудников
    keyboard.append([InlineKeyboardButton(text="◀️ Назад к сотрудникам", callback_data="dir_stats_back_to_employees")])
    keyboard.append([InlineKeyboardButton(text="◀️ Главное меню", callback_data="back_to_menu")])

    await callback.message.edit_text(
        f"📊 Выберите месяц для {employee_name}:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@dp.callback_query(F.data.startswith("dir_stats_month:"))
async def director_stats_show(callback: types.CallbackQuery, state: FSMContext):
    """Показываем статистику по выбранному сотруднику и месяцу."""
    _, year_str, month_str = callback.data.split(":")
    year = int(year_str)
    month = int(month_str)

    user_data = await state.get_data()
    employee_name = user_data.get('selected_employee')
    if not employee_name:
        await callback.message.edit_text("⚠️ Ошибка: сотрудник не выбран.")
        return

    stats = excel_parser.get_employee_stats_for_month(employee_name, year, month)
    if not stats:
        await callback.message.edit_text("⚠️ Статистика за этот месяц недоступна.")
        return

    month_names = {
        1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель',
        5: 'Май', 6: 'Июнь', 7: 'Июль', 8: 'Август',
        9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь'
    }

    # Расчёт даты выплаты (5 число следующего месяца)
    if month == 12:
        pay_year = year + 1
        pay_month = 1
    else:
        pay_year = year
        pay_month = month + 1
    pay_date = datetime(pay_year, pay_month, 5).date()

    today = moscow_now().date()  # изменено
    if pay_date < today:
        days_until_pay = 0
    else:
        days_until_pay = (pay_date - today).days

    response = f"📊 <b>Статистика за {month_names[month]} {year}</b>\n\n"
    response += f"👤 <b>{employee_name}</b>\n\n"
    response += f"⏰ Всего часов в месяце: <b>{stats['total_hours']:.1f} ч</b>\n"
    response += f"✅ Уже отработано: <b>{stats['worked_hours']:.1f} ч</b>\n"
    response += f"📋 Осталось отработать: <b>{stats['remaining_hours']:.1f} ч</b>\n"
    response += f"📅 Рабочих дней: <b>{stats['worked_days']}</b>\n\n"
    response += f"💰 Ожидаемая зарплата за месяц: <b>{stats['salary']:.0f} ₽</b>\n"
    response += f"💵 Уже заработано: <b>{stats['earned_salary']:.0f} ₽</b>\n\n"
    response += f"📅 Дата выплаты: <b>{pay_date.strftime('%d.%m.%Y')}</b>\n"
    if days_until_pay > 0:
        response += f"⏳ Дней до зарплаты: <b>{days_until_pay}</b>"
    else:
        response += f"✅ Зарплата уже выплачена"

    # Кнопки навигации
    keyboard = [
        [InlineKeyboardButton(text="◀️ Другой месяц", callback_data=f"dir_stats_back_to_months")],
        [InlineKeyboardButton(text="◀️ Другой сотрудник", callback_data="dir_stats_back_to_employees")],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="back_to_menu")]
    ]

    await callback.message.edit_text(response, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

@dp.callback_query(F.data == "dir_stats_back_to_employees")
async def director_stats_back_to_employees(callback: types.CallbackQuery, state: FSMContext):
    """Возврат к списку сотрудников."""
    employees = excel_parser.get_employees()
    keyboard = []
    for emp in employees:
        keyboard.append([InlineKeyboardButton(text=emp, callback_data=f"dir_stats_emp:{emp}")])
    keyboard.append([InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_to_menu")])

    await callback.message.edit_text(
        "📊 Выберите сотрудника для просмотра статистики:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )


@dp.callback_query(F.data == "dir_stats_back_to_months")
async def director_stats_back_to_months(callback: types.CallbackQuery, state: FSMContext):
    """Возврат к выбору месяца (после просмотра статистики)."""
    user_data = await state.get_data()
    employee_name = user_data.get('selected_employee')
    if not employee_name:
        await callback.message.edit_text("⚠️ Ошибка: сотрудник не выбран.")
        return

    available_months = excel_parser.get_available_months()
    keyboard = []
    for month_data in available_months[:12]:
        month_name = month_data['month_name']
        year = month_data['year']
        callback_data = f"dir_stats_month:{year}:{month_data['month']}"
        keyboard.append([InlineKeyboardButton(text=f"{month_name} {year}", callback_data=callback_data)])

    keyboard.append([InlineKeyboardButton(text="◀️ Назад к сотрудникам", callback_data="dir_stats_back_to_employees")])
    keyboard.append([InlineKeyboardButton(text="◀️ Главное меню", callback_data="back_to_menu")])

    await callback.message.edit_text(
        f"📊 Выберите месяц для {employee_name}:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Обработчик команды /help"""
    is_admin = access_control.is_admin(message.from_user.id)

    help_text = (
        "🤖 <b>Telegram бот для графика L1.5</b>\n\n"
        "📋 <b>Доступные команды:</b>\n"
        "/start - Начать работу с ботом\n"
        "/menu - Главное меню\n"
        "/today - Расписание на сегодня\n"
        "/tomorrow - Расписание на завтра\n"
        "/week - Расписание на неделю\n"
        "/whoisnow - Кто сейчас на смене\n"
        "/stats - Статистика за месяц\n"
        "/settings - Настройки\n"
        "/help - Показать эту справку\n"
    )

    if is_admin:
        help_text += "\n<b>🔧 Команды администратора:</b>\n"
        help_text += "/add [user_id] - Выдать доступ\n"
        help_text += "/revoke [user_id] - Забрать доступ\n"
        help_text += "/makeadmin [user_id] - Назначить админа\n"
        help_text += "/users - Список пользователей\n"
        help_text += "/broadcast [текст] - Отправить сообщение всем пользователям\n"

    help_text += (
        "\n🔹 <b>Возможности бота:</b>\n"
        "• Просмотр расписания на сегодня, завтра или любую дату\n"
        "• Информация о текущем дежурном\n"
        "• Статистика работы и расчет зарплаты\n\n"
        "💡 Используйте кнопки меню для навигации!"
    )
    await message.answer(help_text, parse_mode="HTML")


@dp.message(Command("menu"))
async def cmd_menu(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    is_director = user_data.get('is_director', False) or await access_control.is_director(message.from_user.id)
    await state.set_state(UserStates.main_menu)
    await message.answer(
        "📋 Главное меню:",
        reply_markup=get_main_menu_keyboard(is_director)
    )


@dp.message(Command("today"))
@dp.message(F.text == "📅 Сегодня")
async def cmd_today(message: types.Message, state: FSMContext):
    """Команда: расписание на сегодня"""
    # Проверяем, есть ли имя в состоянии
    user_data = await state.get_data()
    employee_name = user_data.get('employee_name')

    if not employee_name:
        # Если имени нет, проверяем БД
        user_db = await db.get_user(message.from_user.id)
        if user_db and user_db.get('employee_name'):
            employee_name = user_db['employee_name']
            await state.update_data(employee_name=employee_name)
        else:
            # Отправляем на выбор имени
            await state.set_state(UserStates.choosing_name)
            employees = excel_parser.get_employees()
            if employees:
                await message.answer(
                    "⚠️ Сначала выберите ваше имя:",
                    reply_markup=get_name_keyboard(employees)
                )
            else:
                await message.answer("⚠️ Список сотрудников не загружен. Попробуйте позже.")
            return

    await state.set_state(UserStates.main_menu)

    await bot_logger.log_action(
        message.from_user.username or str(message.from_user.id),
        "Запросил расписание на сегодня"
    )

    today = moscow_now()  # изменено
    schedule = excel_parser.get_schedule_for_date(today)
    all_employees = excel_parser.get_employees()

    response = f"📅 <b>Расписание на {today.strftime('%d.%m.%Y')} ({_get_weekday(today)})</b>\n\n"

    if not schedule:
        response += "Нет данных о сменах на сегодня."
    else:
        formatted_schedule = _format_full_day_schedule(all_employees, schedule, employee_name)
        response += formatted_schedule if formatted_schedule else "Нет данных о сменах."

    await message.answer(response, parse_mode="HTML")


@dp.message(Command("tomorrow"))
@dp.message(F.text == "📅 Завтра")
async def cmd_tomorrow(message: types.Message, state: FSMContext):
    """Команда: расписание на завтра"""
    user_data = await state.get_data()
    employee_name = user_data.get('employee_name')

    if not employee_name:
        user_db = await db.get_user(message.from_user.id)
        if user_db and user_db.get('employee_name'):
            employee_name = user_db['employee_name']
            await state.update_data(employee_name=employee_name)
        else:
            await state.set_state(UserStates.choosing_name)
            employees = excel_parser.get_employees()
            if employees:
                await message.answer(
                    "⚠️ Сначала выберите ваше имя:",
                    reply_markup=get_name_keyboard(employees)
                )
            else:
                await message.answer("⚠️ Список сотрудников не загружен.")
            return

    await state.set_state(UserStates.main_menu)

    await bot_logger.log_action(
        message.from_user.username or str(message.from_user.id),
        "Запросил расписание на завтра"
    )

    tomorrow = moscow_now() + timedelta(days=1)  # изменено
    schedule = excel_parser.get_schedule_for_date(tomorrow)
    all_employees = excel_parser.get_employees()

    response = f"📅 <b>Расписание на {tomorrow.strftime('%d.%m.%Y')} ({_get_weekday(tomorrow)})</b>\n\n"

    if not schedule:
        response += "Нет данных о сменах на завтра."
    else:
        formatted_schedule = _format_full_day_schedule(all_employees, schedule, employee_name)
        response += formatted_schedule if formatted_schedule else "Нет данных о сменах."

    await message.answer(response, parse_mode="HTML")


@dp.message(Command("week"))
@dp.message(F.text == "📅 Неделя")
async def cmd_week(message: types.Message, state: FSMContext):
    """Команда: расписание на неделю"""
    user_data = await state.get_data()
    employee_name = user_data.get('employee_name')

    if not employee_name:
        user_db = await db.get_user(message.from_user.id)
        if user_db and user_db.get('employee_name'):
            employee_name = user_db['employee_name']
            await state.update_data(employee_name=employee_name)
        else:
            await state.set_state(UserStates.choosing_name)
            employees = excel_parser.get_employees()
            if employees:
                await message.answer(
                    "⚠️ Сначала выберите ваше имя:",
                    reply_markup=get_name_keyboard(employees)
                )
            else:
                await message.answer("⚠️ Список сотрудников не загружен.")
            return

    await state.set_state(UserStates.main_menu)

    await bot_logger.log_action(
        message.from_user.username or str(message.from_user.id),
        "Запросил расписание на неделю"
    )

    today = moscow_now()  # изменено
    all_employees = excel_parser.get_employees()

    response = "📅 <b>Расписание на неделю</b>\n\n"
    weekdays_short = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
    has_data = False

    for i in range(7):
        date = today + timedelta(days=i)
        schedule = excel_parser.get_schedule_for_date(date)
        if schedule:
            has_data = True
            response += f"<b>{weekdays_short[date.weekday()]} {date.strftime('%d.%m')}</b>\n"
            formatted = _format_full_day_schedule(all_employees, schedule, employee_name)
            response += formatted + "\n\n"
        else:
            response += f"<b>{weekdays_short[date.weekday()]} {date.strftime('%d.%m')}</b>\n"
            response += "   Нет данных\n\n"

    if not has_data:
        response = "📅 <b>Расписание на неделю</b>\n\nНет данных о сменах на ближайшую неделю."

    await message.answer(response, parse_mode="HTML")

# Добавьте где-нибудь рядом с другими админскими командами (после /users например)

@dp.message(Command("drop"))
async def cmd_drop_bot(message: types.Message):
    """Команда для остановки бота (только для админов)"""
    if not access_control.is_admin(message.from_user.id):
        await message.answer("⛔ Эта команда доступна только администратору.")
        return

    # Отправляем подтверждение
    await message.answer(
        "🛑 <b>Бот останавливается...</b>\n\n"
        "Команда выполнена. Бот будет перезапущен автоматически через систему.",
        parse_mode="HTML"
    )

    # Логируем действие
    await bot_logger.log_action(
        message.from_user.username or str(message.from_user.id),
        f"👑 [ADMIN] Инициировал остановку бота командой /drop"
    )

    # Даем время на отправку сообщения
    await asyncio.sleep(1)

    # Останавливаем бота (завершаем процесс)
    logger.warning(f"Бот остановлен командой /drop от админа {message.from_user.id}")
    os._exit(0)  # Принудительное завершение процесса

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message):
    """Отправить сообщение всем пользователям (только для админа)"""
    if not access_control.is_admin(message.from_user.id):
        await message.answer("⛔ Эта команда доступна только администратору.")
        return

    # Получаем текст сообщения
    text = message.text.replace('/broadcast', '', 1).strip()
    if not text:
        await message.answer(
            "❌ <b>Неверный формат команды</b>\n\n"
            "Используйте: <code>/broadcast [текст сообщения]</code>\n\n"
            "Пример: <code>/broadcast Всем привет! Мы обновили бота.</code>",
            parse_mode="HTML"
        )
        return

    await message.answer("🔄 Начинаю рассылку... Это может занять некоторое время.")

    # Получаем всех пользователей с доступом
    users = await access_control.get_all_users()
    if not users:
        await message.answer("📭 Нет пользователей для рассылки.")
        return

    success_count = 0
    fail_count = 0

    for user in users:
        user_id = user['user_id']
        try:
            await bot.send_message(
                user_id,
                f"{text}",
                parse_mode="HTML"
            )
            success_count += 1
            # Небольшая задержка, чтобы не спамить Telegram API
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
            fail_count += 1

    # Логируем
    await bot_logger.log_action(
        message.from_user.username or str(message.from_user.id),
        f"📢 Отправил рассылку. Успешно: {success_count}, ошибок: {fail_count}"
    )

    await message.answer(
        f"✅ <b>Рассылка завершена</b>\n\n"
        f"📨 Успешно отправлено: {success_count}\n"
        f"❌ Ошибок: {fail_count}",
        parse_mode="HTML"
    )

@dp.message(Command("whoisnow"))
async def cmd_whoisnow(message: types.Message, state: FSMContext):
    """Команда: кто сейчас на смене"""
    await state.set_state(UserStates.main_menu)

    await bot_logger.log_action(
        message.from_user.username or str(message.from_user.id),
        "Запросил текущего дежурного"
    )

    current_employee = excel_parser.get_current_employee()

    if current_employee:
        response = f"👤 <b>Сейчас на смене:</b>\n\n{current_employee['name']}\n⏰ {current_employee['time']}"
    else:
        response = "⚠️ Сейчас никто не дежурит или смена не найдена."

    await message.answer(response, parse_mode="HTML")


@dp.message(Command("stats"))
async def cmd_stats(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    if user_data.get('is_director'):
        await message.answer("⛔ Эта команда предназначена для дежурных.")
        return
    """Команда: статистика за месяц"""
    await state.set_state(UserStates.main_menu)

    user_data = await state.get_data()
    employee_name = user_data.get('employee_name')

    if not employee_name:
        await message.answer("⚠️ Сначала выберите свое имя через /start")
        return

    available_months = excel_parser.get_available_months()

    if not available_months:
        await message.answer("⚠️ Нет доступных месяцев для просмотра статистики")
        return

    keyboard = []
    for month_data in available_months[:6]:
        month_name = month_data['month_name']
        year = month_data['year']
        callback_data = f"stats:{year}:{month_data['month']}"

        keyboard.append([
            InlineKeyboardButton(
                text=f"{month_name} {year}",
                callback_data=callback_data
            )
        ])

    keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")])

    await message.answer(
        "📊 <b>Выберите месяц для просмотра статистики:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML"
    )


@dp.message(Command("settings"))
async def cmd_settings(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    if user_data.get('is_director'):
        await message.answer("⛔ Эта команда недоступна для руководителей.")
        return
    """Команда: настройки (главное меню настроек)."""
    await state.set_state(UserStates.main_menu)
    user_data = await state.get_data()
    employee_name = user_data.get('employee_name', 'Не указано')

    # Получаем текущие настройки из БД
    settings = await db.get_user_settings(message.from_user.id)
    remind_hour = settings.get('remind_before_hour', False) if settings else False
    daily_time = settings.get('daily_remind_time', 'не задано') if settings and settings.get('daily_remind_time') else 'выключено'

    status_text = f"⚙️ <b>Настройки</b>\n\n"
    status_text += f"👤 Ваше имя: {employee_name}\n"
    status_text += f"🔔 Напоминание за час: {'✅ включено' if remind_hour else '❌ выключено'}\n"
    status_text += f"📅 Ежедневное напоминание: {daily_time if daily_time != 'не задано' else '❌ выключено'}\n\n"
    status_text += "Выберите действие:"

    keyboard = [
        [KeyboardButton(text="👤 Изменить имя")],
        [KeyboardButton(text="🔔 Напоминание за час")],
        [KeyboardButton(text="📅 Ежедневное напоминание")],
        [KeyboardButton(text="◀️ Назад в меню")]
    ]

    await message.answer(
        status_text,
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
    )

# Админские команды
@dp.message(Command("add"))
async def cmd_add_user(message: types.Message):
    """Команда для выдачи доступа"""
    if not access_control.is_admin(message.from_user.id):
        await message.answer("⛔ Эта команда доступна только администратору.")
        return

    parts = message.text.split()
    if len(parts) != 2:
        await message.answer(
            "❌ <b>Неверный формат команды</b>\n\n"
            "Используйте: <code>/add [user_id]</code>\n\n"
            "Пример: <code>/add 123456789</code>",
            parse_mode="HTML"
        )
        return

    try:
        user_id = int(parts[1])

        await access_control.grant_access(
            user_id,
            f"user_{user_id}",
            message.from_user.id
        )

        await message.answer(
            f"✅ <b>Доступ выдан</b>\n\n"
            f"Пользователь ID: <code>{user_id}</code>\n"
            f"Пользователь может начать работу с ботом.",
            parse_mode="HTML"
        )

        await bot_logger.log_action(
            message.from_user.username or str(message.from_user.id),
            f"👑 [ADMIN] Выдал доступ пользователю ID: {user_id}"
        )

    except ValueError:
        await message.answer("❌ User ID должен быть числом")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        logger.error(f"Ошибка выдачи доступа: {e}")


@dp.message(Command("revoke"))
async def cmd_revoke_user(message: types.Message):
    """Команда для отзыва доступа"""
    if not access_control.is_admin(message.from_user.id):
        await message.answer("⛔ Эта команда доступна только администратору.")
        return

    parts = message.text.split()
    if len(parts) != 2:
        await message.answer(
            "❌ <b>Неверный формат команды</b>\n\n"
            "Используйте: <code>/revoke [user_id]</code>\n\n"
            "Пример: <code>/revoke 123456789</code>",
            parse_mode="HTML"
        )
        return

    try:
        user_id = int(parts[1])

        if access_control.is_admin(user_id):
            await message.answer("⛔ Нельзя отозвать доступ у администратора")
            return

        await access_control.revoke_access(user_id)

        await message.answer(
            f"✅ <b>Доступ отозван</b>\n\n"
            f"Пользователь ID: <code>{user_id}</code>",
            parse_mode="HTML"
        )

        await bot_logger.log_action(
            message.from_user.username or str(message.from_user.id),
            f"👑 [ADMIN] Отозвал доступ у пользователя ID: {user_id}"
        )

    except ValueError:
        await message.answer("❌ User ID должен быть числом")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


@dp.message(Command("makeadmin"))
async def cmd_make_admin(message: types.Message):
    """Команда для назначения администратора"""
    if not access_control.is_admin(message.from_user.id):
        await message.answer("⛔ Эта команда доступна только администратору.")
        return

    parts = message.text.split()
    if len(parts) != 2:
        await message.answer(
            "❌ <b>Неверный формат команды</b>\n\n"
            "Используйте: <code>/makeadmin [user_id]</code>\n\n"
            "Пример: <code>/makeadmin 123456789</code>",
            parse_mode="HTML"
        )
        return

    try:
        user_id = int(parts[1])

        await access_control.add_admin(user_id)

        # Автоматически даём доступ, если ещё нет
        await access_control.grant_access(
            user_id,
            f"admin_{user_id}",
            message.from_user.id
        )

        await message.answer(
            f"✅ <b>Администратор назначен</b>\n\n"
            f"Пользователь ID: <code>{user_id}</code>\n"
            f"Теперь имеет права администратора.",
            parse_mode="HTML"
        )

        await bot_logger.log_action(
            message.from_user.username or str(message.from_user.id),
            f"👑 [ADMIN] Назначил администратора ID: {user_id}"
        )

    except ValueError:
        await message.answer("❌ User ID должен быть числом")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        logger.error(f"Ошибка назначения админа: {e}")


@dp.message(Command("users"))
async def cmd_list_users(message: types.Message):
    """Команда для просмотра списка пользователей"""
    if not access_control.is_admin(message.from_user.id):
        await message.answer("⛔ Эта команда доступна только администратору.")
        return

    users = await access_control.get_all_users()

    if not users:
        await message.answer("📋 Список пользователей пуст")
        return

    response = "📋 <b>Список пользователей с доступом:</b>\n\n"

    for user in users[:20]:
        user_id = user['user_id']
        username = user['username']
        is_admin = access_control.is_admin(user_id)

        admin_badge = " 👑" if is_admin else ""
        response += f"• {username} (<code>{user_id}</code>){admin_badge}\n"

    if len(users) > 20:
        response += f"\n... и ещё {len(users) - 20} пользователей"

    await message.answer(response, parse_mode="HTML")

@dp.message(Command("adddir"))
async def cmd_add_director(message: types.Message):
    """Назначить руководителя (только для админа)."""
    if not access_control.is_admin(message.from_user.id):
        await message.answer("⛔ Эта команда доступна только администратору.")
        return

    parts = message.text.split()
    if len(parts) != 2:
        await message.answer(
            "❌ <b>Неверный формат команды</b>\n\n"
            "Используйте: <code>/adddir [user_id]</code>\n\n"
            "Пример: <code>/adddir 123456789</code>",
            parse_mode="HTML"
        )
        return

    try:
        user_id = int(parts[1])

        if access_control.is_admin(user_id):
            await message.answer("⛔ Нельзя назначить администратора руководителем (он и так главный).")
            return

        await access_control.add_director(user_id, message.from_user.id)

        await message.answer(
            f"✅ <b>Руководитель назначен</b>\n\n"
            f"Пользователь ID: <code>{user_id}</code>\n"
            f"Теперь имеет доступ к боту и права руководителя.",
            parse_mode="HTML"
        )

        await bot_logger.log_action(
            message.from_user.username or str(message.from_user.id),
            f"👑 [ADMIN] Назначил руководителя ID: {user_id}"
        )

    except ValueError:
        await message.answer("❌ User ID должен быть числом")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        logger.error(f"Ошибка назначения руководителя: {e}")


@dp.message(Command("deldir"))
async def cmd_remove_director(message: types.Message):
    """Снять руководителя (только для админа)."""
    if not access_control.is_admin(message.from_user.id):
        await message.answer("⛔ Эта команда доступна только администратору.")
        return

    parts = message.text.split()
    if len(parts) != 2:
        await message.answer(
            "❌ <b>Неверный формат команды</b>\n\n"
            "Используйте: <code>/deldir [user_id]</code>\n\n"
            "Пример: <code>/deldir 123456789</code>",
            parse_mode="HTML"
        )
        return

    try:
        user_id = int(parts[1])

        if access_control.is_admin(user_id):
            await message.answer("⛔ Нельзя снять администратора.")
            return

        # Проверяем, является ли он руководителем
        if not await access_control.is_director(user_id):
            await message.answer("❌ Этот пользователь не является руководителем.")
            return

        await access_control.remove_director(user_id)

        await message.answer(
            f"✅ <b>Руководитель снят</b>\n\n"
            f"Пользователь ID: <code>{user_id}</code>",
            parse_mode="HTML"
        )

        await bot_logger.log_action(
            message.from_user.username or str(message.from_user.id),
            f"👑 [ADMIN] Снял руководителя ID: {user_id}"
        )

    except ValueError:
        await message.answer("❌ User ID должен быть числом")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        logger.error(f"Ошибка снятия руководителя: {e}")

@dp.message(StateFilter(UserStates.main_menu), F.text == "🔔 Напоминание за час")
async def toggle_remind_hour(message: types.Message, state: FSMContext):
    """Включить/выключить напоминание за час до смены."""
    user_id = message.from_user.id
    settings = await db.get_user_settings(user_id)
    current = settings.get('remind_before_hour', False) if settings else False

    # Переключаем
    new_value = not current
    await db.update_user_settings(user_id, remind_before_hour=new_value)

    status = "включено" if new_value else "выключено"
    await message.answer(f"🔔 Напоминание за час до смены теперь <b>{status}</b>.", parse_mode="HTML")
    # Возвращаем в меню настроек
    await cmd_settings(message, state)


@dp.message(StateFilter(UserStates.main_menu), F.text == "📅 Ежедневное напоминание")
async def daily_remind_menu(message: types.Message, state: FSMContext):
    """Меню для настройки ежедневного напоминания."""
    user_id = message.from_user.id
    settings = await db.get_user_settings(user_id)
    current_time = settings.get('daily_remind_time') if settings else None

    if current_time:
        status = f"⏰ Текущее время: {current_time}"
    else:
        status = "❌ Ежедневные напоминания выключены"

    keyboard = [
        [KeyboardButton(text="⏰ Установить время")],
        [KeyboardButton(text="❌ Выключить")],
        [KeyboardButton(text="◀️ Назад")]
    ]

    await message.answer(
        f"📅 <b>Ежедневное напоминание</b>\n\n{status}\n\n"
        "Вы можете установить время, в которое бот будет напоминать о смене на следующий день.\n"
        "Если время не выбрано, напоминания не приходят.",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
    )


@dp.message(StateFilter(UserStates.main_menu), F.text == "⏰ Установить время")
async def ask_daily_remind_time(message: types.Message, state: FSMContext):
    """Запросить время для ежедневного напоминания."""
    await state.set_state(UserStates.choosing_daily_remind_time)
    # Клавиатура с часами
    hours_keyboard = []
    for hour in range(18, 24):
        hours_keyboard.append([KeyboardButton(text=str(hour))])
    hours_keyboard.append([KeyboardButton(text="◀️ Назад")])
    await message.answer(
        "Выберите час для ежедневного напоминания (от 18 до 23):",
        reply_markup=ReplyKeyboardMarkup(keyboard=hours_keyboard, resize_keyboard=True, one_time_keyboard=True)
    )


@dp.message(StateFilter(UserStates.choosing_daily_remind_time))
async def set_daily_remind_time(message: types.Message, state: FSMContext):
    """Сохранить выбранное время."""
    if message.text == "◀️ Назад":
        await state.set_state(UserStates.main_menu)
        await cmd_settings(message, state)
        return

    try:
        hour = int(message.text)
        if 18 <= hour <= 23:
            time_str = f"{hour:02d}:00"
            await db.update_user_settings(message.from_user.id, daily_remind_time=time_str)
            await message.answer(f"✅ Время ежедневного напоминания установлено на {time_str}.")
            await state.set_state(UserStates.main_menu)
            await cmd_settings(message, state)
        else:
            await message.answer("❌ Пожалуйста, выберите час от 18 до 23.")
    except ValueError:
        await message.answer("❌ Пожалуйста, выберите час из предложенных кнопок.")


@dp.message(StateFilter(UserStates.main_menu), F.text == "Выключить")
async def disable_daily_remind(message: types.Message, state: FSMContext):
    """Выключить ежедневное напоминание."""
    await db.update_user_settings(message.from_user.id, daily_remind_time=None)
    await message.answer("✅ Ежедневные напоминания отключены.")
    await state.set_state(UserStates.main_menu)
    await cmd_settings(message, state)


# Обработчики состояний
@dp.message(StateFilter(UserStates.choosing_name))
async def process_name_selection(message: types.Message, state: FSMContext):
    """Обработка выбора имени сотрудника"""
    employees = excel_parser.get_employees()

    # Проверяем, есть ли имя в списке
    if message.text in employees:
        # Сохраняем имя в состояние
        await state.update_data(employee_name=message.text)

        # Получаем обновленные данные состояния
        user_data = await state.get_data()
        logger.info(f"Сохраняем имя {message.text} для пользователя {message.from_user.id}")

        # Сохраняем в БД
        await db.save_user(
            message.from_user.id,
            message.from_user.username or str(message.from_user.id),
            is_l15=True,
            employee_name=message.text
        )

        await bot_logger.log_action(
            message.from_user.username or str(message.from_user.id),
            f"Выбрал имя: {message.text}"
        )

        # Переходим в главное меню
        await state.set_state(UserStates.main_menu)

        # Проверяем, является ли пользователь директором
        is_director = await access_control.is_director(message.from_user.id)

        await message.answer(
            f"✅ Отлично, {message.text}!\n\n"
            f"Теперь вы можете использовать все функции бота:",
            reply_markup=get_main_menu_keyboard(is_director)
        )
    else:
        await message.answer(
            "⚠️ Пожалуйста, выберите имя из предложенного списка.",
            reply_markup=get_name_keyboard(employees)
        )

@dp.message(Command("smena"))
async def cmd_test_smena(message: types.Message):
    """Тестовая команда: симулирует начало смены на 4 часа"""
    if not access_control.is_admin(message.from_user.id):
        await message.answer("⛔ Только для администратора.")
        return

    now = moscow_now()
    shift_start = now.replace(second=0, microsecond=0)
    shift_end   = shift_start + timedelta(hours=4)

    msg = await message.answer(
        f"⏱ <b>Смена началась!</b>\n\n"
        f"💰 <b>0.00 руб.</b> уже заработано за смену.\n"
        f"⏳ Осталось работать: считаю...",
        parse_mode="HTML"
    )
    active_shift_counters[message.from_user.id] = {
        'message_id':  msg.message_id,
        'chat_id':     msg.chat.id,
        'shift_start': shift_start,
        'shift_end':   shift_end
    }
    await bot.pin_chat_message(chat_id=msg.chat.id, message_id=msg.message_id, disable_notification=True)

    await message.answer(
        f"✅ Тестовая смена запущена.\n"
        f"Начало: {shift_start.strftime('%H:%M')}, конец: {shift_end.strftime('%H:%M')}"
    )


@dp.message(Command("nesmena"))
async def cmd_test_nesmena(message: types.Message):
    """Тестовая команда: останавливает счётчик и показывает финальное сообщение"""
    if not access_control.is_admin(message.from_user.id):
        await message.answer("⛔ Только для администратора.")
        return

    user_id = message.from_user.id
    if user_id not in active_shift_counters:
        await message.answer("⚠️ Активной тестовой смены нет. Сначала запусти /smena.")
        return

    data = active_shift_counters.pop(user_id)
    shift_start   = data['shift_start']
    now           = moscow_now()
    elapsed_min   = (now - shift_start).total_seconds() / 60
    total_earned  = elapsed_min * (160 / 60)

    try:
        await bot.edit_message_text(
            chat_id=data['chat_id'],
            message_id=data['message_id'],
            text=(
                f"✅ <b>{total_earned:.2f} руб. заработано за смену.</b>\n\n"
                f"Владислав гордится тобой!"
            ),
            parse_mode="HTML"
        )
        await bot.unpin_chat_message(chat_id=data['chat_id'], message_id=data['message_id'])
    except Exception as e:
        await message.answer(f"❌ Не удалось отредактировать сообщение: {e}")
        return

    await message.answer("✅ Тестовая смена остановлена.")

# Обработчики главного меню (кнопки)
@dp.message(StateFilter(UserStates.main_menu), F.text == "📅 Сегодня")
async def show_today_schedule(message: types.Message, state: FSMContext):
    """Показать расписание на сегодня"""
    await cmd_today(message, state)


@dp.message(StateFilter(UserStates.main_menu), F.text == "📅 Завтра")
async def show_tomorrow_schedule(message: types.Message, state: FSMContext):
    """Показать расписание на завтра"""
    await cmd_tomorrow(message, state)


@dp.message(StateFilter(UserStates.main_menu), F.text == "📅 Неделя")
async def show_week_button(message: types.Message, state: FSMContext):
    """Кнопка расписания на неделю"""
    await cmd_week(message, state)


@dp.message(StateFilter(UserStates.main_menu), F.text == "📅 Дата")
async def show_date_picker(message: types.Message, state: FSMContext):
    """Показать календарь для выбора даты"""
    await bot_logger.log_action(
        message.from_user.username or str(message.from_user.id),
        "Открыл календарь выбора даты"
    )

    await state.set_state(UserStates.choosing_date)
    await message.answer(
        "📆 Выберите дату:",
        reply_markup=get_date_keyboard()
    )


@dp.message(StateFilter(UserStates.main_menu), F.text == "👥 Кто на смене?")
async def show_current_shift(message: types.Message, state: FSMContext):
    """Показать текущего дежурного"""
    await cmd_whoisnow(message, state)


@dp.message(StateFilter(UserStates.main_menu), F.text == "📊 Статистика")
async def show_stats_button(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    if user_data.get('is_director'):
        await message.answer("⛔ Эта функция предназначена для дежурных.")
        return
    await cmd_stats(message, state)


@dp.message(StateFilter(UserStates.main_menu), F.text == "ℹ️ О боте")
async def show_about(message: types.Message):
    """Показать информацию о боте"""
    about_text = (
        "🤖 <b>Бот управления графиком L1.5</b>\n\n"
        "📊 Версия: 1.8\n\n"
        "🔹 <b>Возможности:</b>\n"
        "• Просмотр расписания смен\n"
        "• Информация о текущем дежурном\n"
        "• Статистика работы\n\n"
        "💡 По вопросам обращайтесь к @photon_27."
    )
    await message.answer(about_text, parse_mode="HTML")


@dp.message(StateFilter(UserStates.main_menu), F.text == "⚙️ Настройки")
async def show_settings(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    if user_data.get('is_director'):
        await message.answer("⛔ Эта функция предназначена для дежурных.")
        return
    await cmd_settings(message, state)


@dp.message(StateFilter(UserStates.main_menu), F.text == "👤 Изменить имя")
async def change_name_button(message: types.Message, state: FSMContext):
    """Изменить имя сотрудника"""
    await bot_logger.log_action(
        message.from_user.username or str(message.from_user.id),
        "Открыл меню изменения имени"
    )

    employees = excel_parser.get_employees()
    await state.set_state(UserStates.choosing_name)
    await message.answer(
        "Выберите новое имя из списка:",
        reply_markup=get_name_keyboard(employees)
    )


@dp.message(StateFilter(UserStates.main_menu), F.text == "◀️ Назад в меню")
async def back_to_menu_button(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    is_director = await access_control.is_director(user_id)
    await message.answer(
        "📋 Главное меню:",
        reply_markup=get_main_menu_keyboard(is_director)
    )

@dp.message(F.text)
async def auto_start(message: types.Message, state: FSMContext):
    """Автоматический вход для пользователей из БД."""
    # Проверка доступа (middleware уже проверит, но для надёжности)
    has_access = await access_control.check_access(message.from_user.id)
    if not has_access:
        return  # middleware отправит сообщение о блокировке

    user_data_db = await db.get_user(message.from_user.id)
    if not user_data_db:
        # Пользователь не в БД – предлагаем /start
        await message.answer("👋 Для начала работы используйте /start")
        return

    # Есть в БД – восстанавливаем
    await state.update_data(employee_name=user_data_db['employee_name'])
    await state.set_state(UserStates.main_menu)
    user_id = message.from_user.id
    is_director = await access_control.is_director(user_id)
    await message.answer(
        f"👋 С возвращением, {user_data_db['employee_name']}!\n\n"
        f"Повторите ваш запрос, пожалуйста.\n"
        f"Можете изменить настройки через меню ⚙️",
        reply_markup=get_main_menu_keyboard(is_director)
    )

@dp.message(StateFilter(UserStates.main_menu))
async def handle_unknown_message(message: types.Message):
    """Обработка неизвестных команд"""
    await message.answer(
        "❓ Не знаю такой команды.\n\n"
        "Используйте кнопки меню или команду /help для просмотра доступных команд."
    )


# Callback обработчики
@dp.callback_query(F.data.startswith("cal_nav:"))
async def process_calendar_navigation(callback: types.CallbackQuery):
    """Обработка навигации по календарю"""
    _, year_str, month_str = callback.data.split(":")
    year = int(year_str)
    month = int(month_str)

    available_months = excel_parser.get_available_months()
    month_exists = any(m['year'] == year and m['month'] == month for m in available_months)

    if not month_exists:
        month_names = {
            1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель',
            5: 'Май', 6: 'Июнь', 7: 'Июль', 8: 'Август',
            9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь'
        }
        await callback.answer(
            f"⚠️ Расписание на {month_names[month]} {year} пока недоступно",
            show_alert=True
        )
        return

    try:
        await callback.message.edit_reply_markup(
            reply_markup=get_date_keyboard(year, month)
        )
    except:
        pass


@dp.callback_query(F.data.startswith("date:"))
async def process_date_selection(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора даты из календаря"""
    date_str = callback.data.split(":")[1]
    selected_date = datetime.strptime(date_str, "%Y-%m-%d")

    user_id = callback.from_user.id
    is_director = await access_control.is_director(user_id)

    user_data = await state.get_data()
    employee_name = user_data.get('employee_name')

    await bot_logger.log_action(
        callback.from_user.username or str(callback.from_user.id),
        f"Выбрал дату: {selected_date.strftime('%d.%m.%Y')}"
    )

    # Проверяем доступность месяца
    available_months = excel_parser.get_available_months()
    month_exists = any(
        m['year'] == selected_date.year and m['month'] == selected_date.month
        for m in available_months
    )

    if not month_exists:
        month_names = {
            1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель',
            5: 'Май', 6: 'Июнь', 7: 'Июль', 8: 'Август',
            9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь'
        }
        await callback.message.edit_text(
            f"⚠️ Расписание на {month_names[selected_date.month]} {selected_date.year} пока недоступно"
        )
        await state.set_state(UserStates.main_menu)
        await callback.message.answer(
            "📋 Главное меню:",
            reply_markup=get_main_menu_keyboard(is_director)
        )
        return

    schedule = excel_parser.get_schedule_for_date(selected_date) or []
    all_employees = excel_parser.get_employees()

    response = f"📅 <b>Расписание на {selected_date.strftime('%d.%m.%Y')} ({_get_weekday(selected_date)})</b>\n\n"
    response += _format_full_day_schedule(all_employees, schedule, employee_name)

    await callback.message.edit_text(response, parse_mode="HTML")

    await state.set_state(UserStates.main_menu)
    await callback.message.answer(
        "📋 Главное меню:",
        reply_markup=get_main_menu_keyboard(is_director)
    )


@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: types.CallbackQuery, state: FSMContext):
    """Возврат в главное меню из календаря"""
    await state.set_state(UserStates.main_menu)

    await callback.message.edit_text("Возвращаемся в главное меню...")
    user_id = callback.from_user.id
    is_director = await access_control.is_director(user_id)
    await callback.message.answer(
        "📋 Главное меню:",
        reply_markup=get_main_menu_keyboard(is_director)
    )

@dp.callback_query(F.data.startswith("stats:"))
async def process_stats_selection(callback: types.CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    employee_name = user_data.get('employee_name')
    if not employee_name:
        await callback.message.edit_text("⚠️ Ошибка: имя сотрудника не найдено")
        return

    _, year_str, month_str = callback.data.split(":")
    year = int(year_str)
    month = int(month_str)

    stats = excel_parser.get_employee_stats_for_month(employee_name, year, month)
    if not stats:
        await callback.message.edit_text("⚠️ Статистика за этот месяц недоступна")
        return

    # Месяцы на русском
    month_names = {
        1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель',
        5: 'Май', 6: 'Июнь', 7: 'Июль', 8: 'Август',
        9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь'
    }

    # Расчёт даты выплаты (5 число следующего месяца)
    if month == 12:
        pay_year = year + 1
        pay_month = 1
    else:
        pay_year = year
        pay_month = month + 1
    pay_date = datetime(pay_year, pay_month, 5).date()

    # Дней до зарплаты (только если ещё не наступила)
    today = moscow_now().date()  # изменено
    if pay_date < today:
        days_until_pay = 0
    else:
        days_until_pay = (pay_date - today).days

    # Формирование ответа
    response = f"📊 <b>Статистика за {month_names[month]} {year}</b>\n\n"
    response += f"👤 <b>{employee_name}</b>\n\n"
    response += f"⏰ Всего часов в месяце: <b>{stats['total_hours']:.1f} ч</b>\n"
    response += f"✅ Уже отработано: <b>{stats['worked_hours']:.1f} ч</b>\n"
    response += f"📋 Осталось отработать: <b>{stats['remaining_hours']:.1f} ч</b>\n"
    response += f"📅 Рабочих дней: <b>{stats['worked_days']}</b>\n\n"
    response += f"💰 Ожидаемая ЗП за месяц: <b>{stats['salary']:.0f} ₽</b>\n"
    response += f"💵 Уже заработано: <b>{stats['earned_salary']:.0f} ₽</b>\n\n"
    response += f"📅 Дата выплаты: <b>{pay_date.strftime('%d.%m.%Y')}</b>\n"
    if days_until_pay > 0:
        response += f"⏳ Дней до ЗП: <b>{days_until_pay}</b>"
    else:
        response += f"✅ ЗП уже выплачена"

    await callback.message.edit_text(response, parse_mode="HTML")

    await bot_logger.log_action(
        callback.from_user.username or str(callback.from_user.id),
        f"Запросил статистику за {month_names[month]} {year}"
    )

    await state.set_state(UserStates.main_menu)

    user_id = callback.from_user.id
    is_director = await access_control.is_director(user_id)
    await callback.message.answer(
        "📋 Главное меню:",
        reply_markup=get_main_menu_keyboard(is_director)
    )

@dp.callback_query(F.data == "ignore")
async def ignore_callback(callback: types.CallbackQuery):
    """Игнорируем пустые кнопки календаря"""
    await callback.answer()

async def shift_counter_updater():
    """Каждые 5 секунд обновляет сообщение со счётчиком заработка."""
    while True:
        now = moscow_now()
        to_remove = []

        for user_id, data in list(active_shift_counters.items()):
            shift_start = data['shift_start']
            shift_end   = data['shift_end']
            message_id  = data['message_id']
            chat_id     = data['chat_id']

            try:
                if now >= shift_end:
                    # Смена закончилась — финальное сообщение
                    total_minutes = (shift_end - shift_start).total_seconds() / 60
                    total_earned  = total_minutes * (160 / 60)
                    final_text = (
                        f"✅ <b>{total_earned:.2f} руб. заработано за смену.</b>\n\n"
                        f"Владислав гордится тобой!"
                    )
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=final_text,
                        parse_mode="HTML"
                    )
                    await bot.unpin_chat_message(chat_id=chat_id, message_id=message_id)
                    to_remove.append(user_id)
                else:
                    # Смена идёт — обновляем счётчик
                    elapsed_minutes = (now - shift_start).total_seconds() / 60
                    earned          = elapsed_minutes * (160 / 60)
                    remaining_secs  = int((shift_end - now).total_seconds())
                    rem_hours       = remaining_secs // 3600
                    rem_minutes     = (remaining_secs % 3600) // 60

                    text = (
                        f"⏱ <b>Смена идёт!</b>\n\n"
                        f"💰 <b>{earned:.2f} руб.</b> уже заработано за смену.\n"
                        f"⏳ Осталось работать: <b>{rem_hours} ч. {rem_minutes:02d} мин.</b>"
                    )
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=text,
                        parse_mode="HTML"
                    )
            except Exception as e:
                logger.debug(f"shift_counter_updater: {e}")

        for user_id in to_remove:
            active_shift_counters.pop(user_id, None)

        await asyncio.sleep(5)

async def main():
    """Запуск бота"""
    # Инициализация БД
    await db.init_db()
    await access_control.init_db()

    # Запускаем фоновую задачу
    asyncio.create_task(reminder_checker())
    asyncio.create_task(shift_counter_updater())

    logger.info("Бот запущен")
    admin_info = access_control.get_admin_info()
    await bot_logger.log_action("SYSTEM", f"🚀 Бот запущен | Админ: {admin_info['mention']}")

    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка при работе бота: {e}")
        await bot_logger.log_action("SYSTEM", f"❌ Ошибка: {e}")
    finally:
        await bot.session.close()

def _format_full_day_schedule(all_employees, schedule, highlight_employee=None):
    """
    Форматирует расписание на день: показывает только сотрудников с реальными сменами,
    объединяет последовательные смены, смены выделенного сотрудника выделяет жирным.
    Формат: "время: Фамилия Имя" с ведущим нулём в часе.
    """
    if not schedule:
        return ""

    # Группируем смены по сотрудникам
    employees_shifts = {}
    for entry in schedule:
        emp = entry.get('employee')
        time_slot = entry.get('time')
        if emp not in employees_shifts:
            employees_shifts[emp] = []
        employees_shifts[emp].append(time_slot)

    # Оставляем только сотрудников, у которых есть слоты, отличные от 9:00-10:00
    employees_to_show = {}
    for emp, slots in employees_shifts.items():
        if any(s not in ('9:00-10:00', '09:00-10:00') for s in slots):
            employees_to_show[emp] = slots

    # Для каждого сотрудника объединяем слоты
    shifts_by_employee = {}

    for emp, slots in employees_to_show.items():
        parsed = []
        for slot in slots:
            try:
                start_str, end_str = slot.split('-')
                start_h, start_m = map(int, start_str.split(':'))
                end_h, end_m = map(int, end_str.split(':'))
                # Коррекция если конец на следующий день
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
            continue

        parsed.sort(key=lambda x: x['start'])
        # объединяем последовательные
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

        # Формируем строки смен с ведущим нулём
        if len(combined) == 1:
            time_str = f"{_pad_hour(combined[0][0])}-{_pad_hour(combined[0][1])}"
        else:
            intervals = [f"{_pad_hour(s)}-{_pad_hour(e)}" for s, e in combined]
            time_str = ", ".join(intervals)

        shifts_by_employee[emp] = time_str

    # Формируем итоговый вывод: время -> имя
    result_lines = []
    for emp in all_employees:
        if emp in shifts_by_employee:
            line = f"{shifts_by_employee[emp]}: {emp}"
            if emp == highlight_employee:
                result_lines.append(f"   <b>{line}</b>")
            else:
                result_lines.append(f"   {line}")

    return "\n".join(result_lines) if result_lines else "Нет данных о сменах."

async def reminder_checker():
    """Фоновая задача: раз в минуту проверяет, кому отправить напоминания."""
    while True:
        try:
            now = moscow_now()  # изменено
            current_time_str = now.strftime("%H:%M")
            current_hour = now.hour
            current_minute = now.minute

            # Получаем всех пользователей с настройками
            users = await db.get_all_users_with_settings()

            for user in users:
                user_id = user['user_id']
                employee_name = user['employee_name']
                remind_before_hour = user.get('remind_before_hour', False)
                daily_time = user.get('daily_remind_time')

                # Напоминание за час до смены
                if remind_before_hour:
                    # Получаем объединённые смены на сегодня для этого сотрудника
                    shifts_today = excel_parser.get_employee_schedule(employee_name, now)
                    if shifts_today:
                        for shift in shifts_today:
                            try:
                                s_str, e_str = shift['time'].split('-')
                                s_h, s_m = map(int, s_str.split(':'))
                                # Время начала смены (объединённой)
                                shift_start = now.replace(hour=s_h, minute=s_m, second=0, microsecond=0)
                                # Время для напоминания = начало смены минус 1 час
                                remind_time = shift_start - timedelta(hours=1)
                                # Проверяем, совпадает ли текущее время с remind_time (с точностью до минуты)
                                if (now.hour == remind_time.hour and now.minute == remind_time.minute):
                                    await bot.send_message(
                                        user_id,
                                        f"🔔 <b>Напоминание</b>\n\n"
                                        f"Через час, в {s_h:02d}:{s_m:02d}, у вас начинается смена.\n"
                                        f"⏰ {shift['time']}",
                                        parse_mode="HTML"
                                    )
                                    await bot_logger.log_action(
                                        f"user_{user_id}",
                                        f"Отправлено напоминание за час о смене {shift['time']}"
                                    )
                                    break
                            except:
                                continue

                # Запуск счётчика при начале смены
                shifts_today = excel_parser.get_employee_schedule(employee_name, now)
                if shifts_today and user_id not in active_shift_counters:
                    for shift in shifts_today:
                        try:
                            start_str, end_str = shift['time'].split('-')
                            s_h, s_m = map(int, start_str.split(':'))
                            e_h, e_m = map(int, end_str.split(':'))

                            if now.hour == s_h and now.minute == s_m:
                                shift_start = now.replace(second=0, microsecond=0)
                                shift_end = shift_start.replace(hour=e_h % 24, minute=e_m)
                                if e_h >= 24 or e_h < s_h:
                                    shift_end += timedelta(days=1)
                                    shift_end = shift_end.replace(hour=e_h % 24, minute=e_m)

                                msg = await bot.send_message(
                                    user_id,
                                    f"⏱ <b>Смена началась!</b>\n\n"
                                    f"💰 <b>0.00 руб.</b> уже заработано за смену.\n"
                                    f"⏳ Осталось работать: считаю...",
                                    parse_mode="HTML"
                                )
                                active_shift_counters[user_id] = {
                                    'message_id': msg.message_id,
                                    'chat_id': msg.chat.id,
                                    'shift_start': shift_start,
                                    'shift_end': shift_end
                                }
                                await bot.pin_chat_message(chat_id=msg.chat.id, message_id=msg.message_id,
                                                           disable_notification=True)
                                break
                        except Exception as e:
                            logger.debug(f"Ошибка запуска счётчика смены: {e}")

                # Ежедневное напоминание (о завтрашней смене)
                if daily_time and current_time_str == daily_time:
                    tomorrow = now.date() + timedelta(days=1)
                    schedule_tomorrow = excel_parser.get_schedule_for_date(datetime.combine(tomorrow, datetime.min.time()))
                    if schedule_tomorrow:
                        shifts_tomorrow = [e for e in schedule_tomorrow if e['employee'] == employee_name]
                        if shifts_tomorrow:
                            # Объединяем смены (можно использовать ту же логику, что и в расписании)
                            # Для простоты возьмём первую
                            # Лучше использовать get_employee_schedule, но он возвращает уже объединённые
                            emp_shifts = excel_parser.get_employee_schedule(employee_name, datetime.combine(tomorrow, datetime.min.time()))
                            if emp_shifts:
                                times = ", ".join([s['time'] for s in emp_shifts])
                                await bot.send_message(
                                    user_id,
                                    f"📅 <b>Напоминание о завтрашней смене</b>\n\n"
                                    f"Завтра, {tomorrow.strftime('%d.%m.%Y')}, у вас смена: {times}",
                                    parse_mode="HTML"
                                )
                                await bot_logger.log_action(
                                    f"user_{user_id}",
                                    f"Отправлено ежедневное напоминание о завтрашней смене"
                                )
        except Exception as e:
            logger.error(f"Ошибка в reminder_checker: {e}")

        # Ждём 60 секунд
        await asyncio.sleep(60)

if __name__ == '__main__':
    asyncio.run(main())