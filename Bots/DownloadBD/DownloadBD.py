import telegram
from telegram.ext import Application, CommandHandler
import logging
import os

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# Токен вашего бота от BotFather
TOKEN = '7780386252:AAHqzrXWK0QhA3GdS1MBTaSVqQcPoNrcmdA'

# Путь к файлу на сервере
FILE_PATH = '/root/Bots/Bots/BD/join_requests.db'  # Укажите путь к вашему файлу

# ID доверенного лица (замените на реальный ID пользователя)
TRUSTED_USER_ID = 7935760590  # Укажите ID пользователя, которому разрешено получать файл


# Функция для команды /start
async def start(update, context):
    await update.message.reply_text('Привет! Используй /getfile чтобы получить файл, если у тебя есть доступ.')


# Функция для отправки файла
async def get_file(update, context):
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id  # Получаем ID пользователя

    # Проверяем, является ли пользователь доверенным
    if user_id != TRUSTED_USER_ID:
        await update.message.reply_text('У тебя нет доступа к этому файлу!')
        logger.info(f'Пользователь {user_id} попытался получить файл, но доступ запрещен.')
        return

    try:
        # Проверяем, существует ли файл
        if not os.path.exists(FILE_PATH):
            await update.message.reply_text('Извините, файл не найден на сервере.')
            return

        # Открываем и отправляем файл
        with open(FILE_PATH, 'rb') as file:
            await context.bot.send_document(chat_id=chat_id,
                                            document=file,
                                            filename=os.path.basename(FILE_PATH))

        await update.message.reply_text('Файл успешно отправлен!')
        logger.info(f'Файл отправлен пользователю {user_id}')

    except Exception as e:
        logger.error(f'Ошибка при отправке файла: {e}')
        await update.message.reply_text('Произошла ошибка при отправке файла.')


def main():
    # Создаем приложение
    application = Application.builder().token(TOKEN).build()

    # Регистрируем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("getfile", get_file))

    # Запускаем бота
    print('Бот запущен!')
    application.run_polling()


if __name__ == '__main__':
    main()
