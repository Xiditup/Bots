import logging
import sqlite3
from telegram import Update
from telegram.ext import (
    Application, ChatJoinRequestHandler, CommandHandler, ContextTypes,
    ConversationHandler, MessageHandler, filters
)
from datetime import datetime, timedelta
import pytz
import json
import os

# Включите логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Токен бота и ваш Telegram ID
BOT_TOKEN = '7734807887:AAGP0NcyoB9asQSTTpLJLdXWG8R6tlHLomg'  # Замените на ваш токен
YOUR_USER_ID = 8095199276  # Замените на ваш ID

# Абсолютные пути
DB_PATH = '/root/Zayavka/BD/BD/join_requests.db'
JSON_FILE = '/root/Zayavka/BD/BD/BB.json'

# Глобальные переменные
total_requests = 0
last_reset_date = None  # Для дневного сброса в 21:00
weekly_counts = {}  # Словарь для недельной статистики: {дата: количество}
last_weekly_reset = None  # Для недельного сброса в 00:00
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

# Состояния для ConversationHandler
WAITING_FOR_USER_ID, WAITING_FOR_REASON, WAITING_FOR_LEAD_NAME, WAITING_FOR_CHECK_ID, WAITING_FOR_REMOVE_ID = range(5)


def load_counters():
    """Загружает данные счетчиков из JSON-файла при запуске."""
    global total_requests, last_reset_date, weekly_counts, last_weekly_reset
    if os.path.exists(JSON_FILE):
        try:
            with open(JSON_FILE, 'r') as f:
                content = f.read().strip()
                if not content:
                    logging.warning("Файл counters.json пуст. Используются значения по умолчанию.")
                    raise ValueError("Пустой JSON-файл")

                data = json.loads(content)
                total_requests = data.get('total_requests', 0)
                last_reset_date_str = data.get('last_reset_date')
                last_weekly_reset_str = data.get('last_weekly_reset')
                weekly_counts = data.get('weekly_counts', {})

                last_reset_date = (datetime.strptime(last_reset_date_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=MOSCOW_TZ)
                                   if last_reset_date_str else None)
                last_weekly_reset = (
                    datetime.strptime(last_weekly_reset_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=MOSCOW_TZ)
                    if last_weekly_reset_str else None)

                weekly_counts = {datetime.strptime(date, '%Y-%m-%d').date(): count
                                 for date, count in weekly_counts.items()}
        except (json.JSONDecodeError, ValueError) as e:
            logging.error(f"Ошибка при загрузке counters.json: {e}. Используются значения по умолчанию.")
            now_moscow = datetime.now(MOSCOW_TZ)
            total_requests = 0
            last_reset_date = now_moscow.replace(hour=21, minute=0, second=0, microsecond=0)
            if now_moscow > last_reset_date:
                last_reset_date += timedelta(days=1)
            last_weekly_reset = now_moscow.replace(hour=0, minute=0, second=0, microsecond=0)
            if now_moscow > last_weekly_reset:
                last_weekly_reset += timedelta(days=1)
            weekly_counts = {}
            save_counters()  # Перезаписываем файл корректными значениями
    else:
        logging.info("Файл counters.json не существует. Создается новый с значениями по умолчанию.")
        now_moscow = datetime.now(MOSCOW_TZ)
        total_requests = 0
        last_reset_date = now_moscow.replace(hour=21, minute=0, second=0, microsecond=0)
        if now_moscow > last_reset_date:
            last_reset_date += timedelta(days=1)
        last_weekly_reset = now_moscow.replace(hour=0, minute=0, second=0, microsecond=0)
        if now_moscow > last_weekly_reset:
            last_weekly_reset += timedelta(days=1)
        weekly_counts = {}
        save_counters()  # Создаем новый файл


def save_counters():
    """Сохраняет данные счетчиков в JSON-файл."""
    global total_requests, last_reset_date, weekly_counts, last_weekly_reset
    data = {
        'total_requests': total_requests,
        'last_reset_date': last_reset_date.strftime('%Y-%m-%d %H:%M:%S') if last_reset_date else None,
        'last_weekly_reset': last_weekly_reset.strftime('%Y-%m-%d %H:%M:%S') if last_weekly_reset else None,
        'weekly_counts': {date.strftime('%Y-%m-%d'): count for date, count in weekly_counts.items()}
    }
    try:
        with open(JSON_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logging.error(f"Ошибка при сохранении counters.json: {e}")


def init_db():
    """Создает базы данных и таблицы, если они не существуют, и обновляет структуру."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS requests (
                user_id INTEGER,
                username TEXT,
                full_name TEXT,
                chat_id INTEGER,
                chat_title TEXT,
                request_date TEXT
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS blacklist (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                lead_name TEXT,
                reason TEXT,
                added_date TEXT
            )
        ''')

        cursor.execute("PRAGMA table_info(blacklist)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'lead_name' not in columns:
            cursor.execute('ALTER TABLE blacklist ADD COLUMN lead_name TEXT')
            logging.info("Добавлен столбец lead_name в таблицу blacklist")

        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Ошибка при инициализации базы данных: {e}")
    finally:
        conn.close()

    # Загружаем счетчики из JSON
    load_counters()


# Инициализация базы данных при запуске
init_db()


def check_blacklist(user_id):
    """Проверяет, находится ли пользователь в черном списке."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT lead_name, reason, added_date FROM blacklist WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result
    except sqlite3.Error as e:
        logging.error(f"Ошибка при проверке черного списка: {e}")
        return None


async def handle_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик заявок на вступление в канал."""
    global total_requests, last_reset_date, weekly_counts, last_weekly_reset

    join_request = update.chat_join_request
    user = join_request.from_user
    chat = join_request.chat
    now_moscow = datetime.now(MOSCOW_TZ)
    current_date = now_moscow.date()

    # Дневной сброс в 21:00
    reset_time_today = now_moscow.replace(hour=21, minute=0, second=0, microsecond=0)
    if now_moscow >= reset_time_today and last_reset_date <= reset_time_today:
        prev_total = total_requests
        total_requests = 0
        last_reset_date = reset_time_today + timedelta(days=1)
        await context.bot.send_message(
            chat_id=YOUR_USER_ID,
            text=f"Счётчик заявок сброшен в 21:00 (МСК). Всего заявок за день было: {prev_total}"
        )
        logging.info(f"Счётчик сброшен в 21:00 (МСК). Предыдущее значение: {prev_total}")

    # Недельный сброс в 00:00
    midnight_today = now_moscow.replace(hour=0, minute=0, second=0, microsecond=0)
    if now_moscow >= midnight_today and last_weekly_reset <= midnight_today:
        week_ago = current_date - timedelta(days=7)
        weekly_counts = {date: count for date, count in weekly_counts.items() if date > week_ago}
        last_weekly_reset = midnight_today + timedelta(days=1)
        logging.info("Обновлена недельная статистика в 00:00 (МСК)")

    # Увеличиваем счетчики
    total_requests += 1
    weekly_counts[current_date] = weekly_counts.get(current_date, 0) + 1

    # Сохраняем в JSON
    save_counters()

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Проверка черного списка
        blacklist_info = check_blacklist(user.id)

        cursor.execute('SELECT chat_title, request_date FROM requests WHERE user_id = ?', (user.id,))
        existing_requests = cursor.fetchall()

        message = (
            f"Новая заявка на вступление!\n"
            f"Пользователь: {user.full_name} (@{user.username if user.username else 'нет username'})\n"
            f"ID: {user.id}\n"
            f"Канал: {chat.title} (@{chat.username if chat.username else 'нет username'})\n"
            f"Дата и время: {now_moscow.strftime('%Y-%m-%d %H:%M:%S')} (МСК)\n"
            f"Всего заявок за день: {total_requests}"
        )

        if blacklist_info:
            lead_name, reason, added_date = blacklist_info
            message += (
                f"\n\n⚠️ ВНИМАНИЕ: ПОЛЬЗОВАТЕЛЬ В ЧЕРНОМ СПИСКЕ ⚠️\n"
                f"Имя лида: {lead_name if lead_name else 'Не указано'}\n"
                f"Комментарии:\n{reason}\n"
                f"Впервые добавлен: {added_date}"
            )

        if existing_requests:
            message += "\n\nРанее подавал заявки в:\n"
            for req in existing_requests:
                message += f"- {req[0]} ({req[1]})\n"

        cursor.execute('''
            INSERT INTO requests (user_id, username, full_name, chat_id, chat_title, request_date)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user.id, user.username, user.full_name, chat.id, chat.title, now_moscow.strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Ошибка при работе с базой данных в handle_join_request: {e}")
    finally:
        conn.close()

    await context.bot.send_message(chat_id=YOUR_USER_ID, text=message)
    logging.info(f"Получена заявка от {user.full_name} (@{user.username}) в {chat.title}")


async def reset_requests(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда для ручного сброса счётчика заявок: /resetrequests."""
    global total_requests, last_reset_date

    if update.effective_user.id != YOUR_USER_ID:
        await update.message.reply_text("Эта команда доступна только владельцу бота.")
        return

    now_moscow = datetime.now(MOSCOW_TZ)
    total_requests = 0
    last_reset_date = now_moscow.replace(hour=21, minute=0, second=0, microsecond=0) + timedelta(days=1)
    save_counters()
    await update.message.reply_text(
        f"Счётчик заявок сброшен!\n"
        f"Текущая дата и время: {now_moscow.strftime('%Y-%m-%d %H:%M:%S')} (МСК)\n"
        f"Всего заявок за день: {total_requests}"
    )
    logging.info("Счётчик заявок сброшен вручную")


async def weekly_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда для получения статистики за неделю: /weeklystats."""
    if update.effective_user.id != YOUR_USER_ID:
        await update.message.reply_text("Эта команда доступна только владельцу бота.")
        return

    now_moscow = datetime.now(MOSCOW_TZ)
    current_date = now_moscow.date()
    week_ago = current_date - timedelta(days=6)

    stats_message = "Статистика заявок за последнюю неделю:\n"
    total_weekly = 0

    for i in range(7):
        date = week_ago + timedelta(days=i)
        count = weekly_counts.get(date, 0)
        total_weekly += count
        stats_message += f"{date.strftime('%Y-%m-%d')} ({['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'][date.weekday()]}): {count} заявок\n"

    stats_message += f"\nИтого за неделю: {total_weekly} заявок"
    await update.message.reply_text(stats_message)
    logging.info("Запрошена статистика за неделю")


async def global_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда для получения глобальной статистики: /globalstats."""
    if update.effective_user.id != YOUR_USER_ID:
        await update.message.reply_text("Эта команда доступна только владельцу бота.")
        return

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM requests')
        total_requests_db = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(DISTINCT user_id) FROM requests')
        unique_users = cursor.fetchone()[0]

        stats_message = (
            f"Глобальная статистика:\n"
            f"Всего заявок: {total_requests_db}\n"
            f"Уникальных пользователей: {unique_users}"
        )
        await update.message.reply_text(stats_message)
        logging.info("Запрошена глобальная статистика")
    except sqlite3.Error as e:
        logging.error(f"Ошибка при получении глобальной статистики: {e}")
        await update.message.reply_text("Ошибка при получении статистики.")
    finally:
        conn.close()


async def search_user_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало процесса поиска пользователя: запрос ID."""
    if update.effective_user.id != YOUR_USER_ID:
        await update.message.reply_text("Эта команда доступна только владельцу бота.")
        return ConversationHandler.END

    await update.message.reply_text("Пожалуйста, введите ID пользователя.")
    return WAITING_FOR_USER_ID


async def search_user_process(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка введённого ID пользователя, вывод всей информации из базы."""
    user_input = update.message.text

    try:
        user_id = int(user_input)
    except ValueError:
        await update.message.reply_text("ID пользователя должен быть числом. Попробуйте снова.")
        return WAITING_FOR_USER_ID

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT user_id, username, full_name, chat_id, chat_title, request_date 
            FROM requests 
            WHERE user_id = ? 
            ORDER BY request_date DESC
        ''', (user_id,))
        requests = cursor.fetchall()

        if not requests:
            await update.message.reply_text(f"Заявки от пользователя с ID {user_id} не найдены.")
        else:
            message = f"Найденные заявки от пользователя с ID {user_id}:\n\n"
            for i, (user_id, username, full_name, chat_id, chat_title, request_date) in enumerate(requests, 1):
                user_info = f"@{username}" if username else "нет username"
                message += (
                    f"Заявка #{i}:\n"
                    f"ID пользователя: {user_id}\n"
                    f"Ник: {user_info}\n"
                    f"Полное имя: {full_name}\n"
                    f"ID чата: {chat_id}\n"
                    f"Название чата: {chat_title}\n"
                    f"Дата и время: {request_date}\n"
                    f"{'-' * 20}\n"
                )
            await update.message.reply_text(message)

        logging.info(f"Запрошен поиск заявок для user_id {user_id}")
    except sqlite3.Error as e:
        logging.error(f"Ошибка при поиске пользователя: {e}")
        await update.message.reply_text("Ошибка при поиске пользователя.")
    finally:
        conn.close()

    return ConversationHandler.END


async def search_user_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена процесса поиска."""
    await update.message.reply_text("Поиск отменён.")
    return ConversationHandler.END


async def search_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда для поиска заявок по chat_id: /searchchat <chat_id>."""
    if update.effective_user.id != YOUR_USER_ID:
        await update.message.reply_text("Эта команда доступна только владельцу бота.")
        return

    if not context.args:
        await update.message.reply_text("Пожалуйста, укажите ID чата. Пример: /searchchat -100123456789")
        return

    try:
        chat_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID чата должен быть числом.")
        return

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT username, full_name, request_date 
            FROM requests 
            WHERE chat_id = ? 
            ORDER BY request_date DESC
        ''', (chat_id,))
        requests = cursor.fetchall()

        if not requests:
            await update.message.reply_text(f"Заявки для чата с ID {chat_id} не найдены.")
        else:
            message = f"Найденные заявки для чата с ID {chat_id}:\n"
            for i, (username, full_name, request_date) in enumerate(requests, 1):
                user_info = f"@{username}" if username else full_name
                message += f"{i}. Пользователь: {user_info} ({request_date})\n"
            await update.message.reply_text(message)

        logging.info(f"Запрошен поиск заявок для chat_id {chat_id}")
    except sqlite3.Error as e:
        logging.error(f"Ошибка при поиске чата: {e}")
        await update.message.reply_text("Ошибка при поиске чата.")
    finally:
        conn.close()


async def blacklist_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало процесса добавления в черный список."""
    if update.effective_user.id != YOUR_USER_ID:
        await update.message.reply_text("Эта команда доступна только владельцу бота.")
        return ConversationHandler.END

    await update.message.reply_text("Пожалуйста, введите ID пользователя для добавления в черный список.")
    return WAITING_FOR_USER_ID


async def blacklist_get_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получение ID пользователя для черного списка."""
    user_input = update.message.text

    try:
        user_id = int(user_input)
        context.user_data['blacklist_user_id'] = user_id
        await update.message.reply_text("Введите причину добавления в черный список.")
        return WAITING_FOR_REASON
    except ValueError:
        await update.message.reply_text("ID должен быть числом. Попробуйте снова.")
        return WAITING_FOR_USER_ID


async def blacklist_get_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получение причины и запрос имени лида."""
    reason = update.message.text
    context.user_data['blacklist_reason'] = reason
    await update.message.reply_text("Введите имя лида (или напишите 'нет', если не хотите указывать).")
    return WAITING_FOR_LEAD_NAME


async def blacklist_get_lead_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Добавление пользователя в черный список с учетом истории комментариев и имени лида."""
    lead_name_input = update.message.text
    user_id = context.user_data.get('blacklist_user_id')
    new_reason = context.user_data.get('blacklist_reason')
    now_moscow = datetime.now(MOSCOW_TZ)

    lead_name = None if lead_name_input.lower() == 'нет' else lead_name_input

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute('SELECT username, full_name, reason, added_date FROM blacklist WHERE user_id = ?', (user_id,))
        existing_entry = cursor.fetchone()

        if existing_entry:
            username, full_name, existing_reason, added_date = existing_entry
            updated_reason = f"{existing_reason}\n[{now_moscow.strftime('%Y-%m-%d %H:%M:%S')}] {new_reason}"
            cursor.execute('''
                UPDATE blacklist 
                SET reason = ?, lead_name = ?
                WHERE user_id = ?
            ''', (updated_reason, lead_name, user_id))
            message = (
                f"Пользователь с ID {user_id} уже был в черном списке. Добавлен новый комментарий:\n"
                f"[{now_moscow.strftime('%Y-%m-%d %H:%M:%S')}] {new_reason}"
            )
        else:
            cursor.execute(
                'SELECT username, full_name FROM requests WHERE user_id = ? ORDER BY request_date DESC LIMIT 1',
                (user_id,))
            user_info = cursor.fetchone()
            username = user_info[0] if user_info else None
            full_name = user_info[1] if user_info else "Неизвестно"

            cursor.execute('''
                INSERT INTO blacklist (user_id, username, full_name, lead_name, reason, added_date)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, username, full_name, lead_name, f"[{now_moscow.strftime('%Y-%m-%d %H:%M:%S')}] {new_reason}",
                  now_moscow.strftime('%Y-%m-%d %H:%M:%S')))
            message = (
                f"Пользователь с ID {user_id} добавлен в черный список.\n"
                f"Причина: {new_reason}\n"
                f"Имя лида: {lead_name if lead_name else 'Не указано'}"
            )

        conn.commit()
        await update.message.reply_text(message)
        logging.info(f"Пользователь {user_id} обновлен/добавлен в черный список")
    except sqlite3.Error as e:
        logging.error(f"Ошибка при добавлении в черный список: {e}")
        await update.message.reply_text("Ошибка при добавлении в черный список.")
    finally:
        conn.close()

    return ConversationHandler.END


async def blacklist_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена добавления в черный список."""
    await update.message.reply_text("Добавление в черный список отменено.")
    return ConversationHandler.END


async def check_blacklist_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало процесса проверки статуса в черном списке."""
    if update.effective_user.id != YOUR_USER_ID:
        await update.message.reply_text("Эта команда доступна только владельцу бота.")
        return ConversationHandler.END

    await update.message.reply_text("Пожалуйста, введите ID пользователя для проверки в черном списке.")
    return WAITING_FOR_CHECK_ID


async def check_blacklist_process(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка введённого ID для проверки в черном списке."""
    user_input = update.message.text

    try:
        user_id = int(user_input)
        blacklist_info = check_blacklist(user_id)

        if blacklist_info:
            lead_name, reason, added_date = blacklist_info
            await update.message.reply_text(
                f"Пользователь с ID {user_id} в черном списке.\n"
                f"Имя лида: {lead_name if lead_name else 'Не указано'}\n"
                f"Комментарии:\n{reason}\n"
                f"Впервые добавлен: {added_date}"
            )
        else:
            await update.message.reply_text(f"Пользователь с ID {user_id} не найден в черном списке.")
    except ValueError:
        await update.message.reply_text("ID должен быть числом. Попробуйте снова.")
        return WAITING_FOR_CHECK_ID

    logging.info(f"Запрошена проверка user_id {user_id} в черном списке")
    return ConversationHandler.END


async def remove_blacklist_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало процесса удаления из черного списка."""
    if update.effective_user.id != YOUR_USER_ID:
        await update.message.reply_text("Эта команда доступна только владельцу бота.")
        return ConversationHandler.END

    await update.message.reply_text("Пожалуйста, введите ID пользователя для удаления из черного списка.")
    return WAITING_FOR_REMOVE_ID


async def remove_blacklist_process(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка введённого ID для удаления из черного списка."""
    user_input = update.message.text

    try:
        user_id = int(user_input)
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute('SELECT lead_name FROM blacklist WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()

        if result:
            cursor.execute('DELETE FROM blacklist WHERE user_id = ?', (user_id,))
            conn.commit()
            await update.message.reply_text(f"Пользователь с ID {user_id} удалён из черного списка.")
            logging.info(f"Пользователь {user_id} удалён из черного списка")
        else:
            await update.message.reply_text(f"Пользователь с ID {user_id} не найден в черном списке.")

        conn.close()
    except ValueError:
        await update.message.reply_text("ID должен быть числом. Попробуйте снова.")
        return WAITING_FOR_REMOVE_ID
    except sqlite3.Error as e:
        logging.error(f"Ошибка при удалении из черного списка: {e}")
        await update.message.reply_text("Ошибка при удалении из черного списка.")
    finally:
        conn.close()

    return ConversationHandler.END


async def blacklist_operation_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена операций с черным списком."""
    await update.message.reply_text("Операция отменена.")
    return ConversationHandler.END


def main() -> None:
    """Запуск бота."""
    try:
        application = Application.builder().token(BOT_TOKEN).build()

        search_user_conv = ConversationHandler(
            entry_points=[CommandHandler("searchuser", search_user_start)],
            states={
                WAITING_FOR_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_user_process)],
            },
            fallbacks=[CommandHandler("cancel", search_user_cancel)],
        )

        blacklist_conv = ConversationHandler(
            entry_points=[
                CommandHandler("addblacklist", blacklist_start),
                CommandHandler("checkblacklist", check_blacklist_start),
                CommandHandler("removeblacklist", remove_blacklist_start),
            ],
            states={
                WAITING_FOR_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, blacklist_get_id)],
                WAITING_FOR_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, blacklist_get_reason)],
                WAITING_FOR_LEAD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, blacklist_get_lead_name)],
                WAITING_FOR_CHECK_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, check_blacklist_process)],
                WAITING_FOR_REMOVE_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, remove_blacklist_process)],
            },
            fallbacks=[CommandHandler("cancel", blacklist_operation_cancel)],
        )

        application.add_handler(ChatJoinRequestHandler(handle_join_request))
        application.add_handler(CommandHandler("resetrequests", reset_requests))
        application.add_handler(CommandHandler("weeklystats", weekly_stats_command))
        application.add_handler(CommandHandler("globalstats", global_stats_command))
        application.add_handler(search_user_conv)
        application.add_handler(CommandHandler("searchchat", search_chat))
        application.add_handler(blacklist_conv)

        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logging.error(f"Ошибка при запуске бота: {e}")


if __name__ == '__main__':
    main()