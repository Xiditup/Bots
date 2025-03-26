import asyncio
import requests
import telegram
import json
import os

# Настройки
TON_API_URL = "https://tonapi.io/v2/blockchain/accounts/testnetblockchain.ton/transactions"
TON_API_KEY = "AF3AGXB6IMQGMZYAAAAOIJTAQYIFAPHU4U6BUQAOWRHCIWP5QNPN3Q35XLSB5CTBNCTX3XA"  # Ваш ключ
TELEGRAM_TOKEN = "7656039200:AAHnL9ro9Fx9I5kO7uqnoOlqi3GNq-jhI5k"  # От @BotFather
CHAT_ID = "-1002421103941"  # Узнайте через getUpdates
LAST_TX_FILE = "last_tx_id.json"  # Файл для хранения последнего хэша

bot = telegram.Bot(token=TELEGRAM_TOKEN)


def load_last_tx_id():
    """Загружает последний обработанный хэш из файла."""
    if os.path.exists(LAST_TX_FILE):
        with open(LAST_TX_FILE, "r") as f:
            data = json.load(f)
            return data.get("last_tx_id")
    return None


def save_last_tx_id(tx_id):
    """Сохраняет последний обработанный хэш в файл."""
    with open(LAST_TX_FILE, "w") as f:
        json.dump({"last_tx_id": tx_id}, f)


def get_transactions():
    headers = {"Authorization": f"Bearer {TON_API_KEY}"}
    try:
        response = requests.get(TON_API_URL, headers=headers)
        if response.status_code == 200:
            data = response.json().get("transactions", [])
            print("Ответ API:", data)  # Отладочный вывод
            return data
        else:
            print(f"Ошибка API: {response.status_code} - {response.text}")
            return []
    except Exception as e:
        print(f"Ошибка запроса: {e}")
        return []


def format_transaction(tx):
    amount = int(tx.get("in_msg", {}).get("value", 0)) / 1e9 if tx.get("in_msg") else "N/A"
    comment = tx.get("in_msg", {}).get("decoded_body", {}).get("text", "Нет комментария")
    sender = tx.get("in_msg", {}).get("source", "N/A")
    tx_hash = tx.get("hash", "unknown")[:10] + "..."  # Укорачиваем хэш для красоты

    return (f"💸 Новая транзакция\n"
            f"💰 Сумма: {amount} TON\n"
            f"📝 Комментарий: {comment}\n"
            f"👤 Отправитель: {sender}\n"
            f"🔗 Хэш: {tx_hash}")


async def send_message(chat_id, text):
    await bot.send_message(chat_id=chat_id, text=text)


async def main():
    # Загружаем последний обработанный хэш из файла
    last_tx_id = load_last_tx_id()

    # Если last_tx_id не задан (первый запуск), берем хэш последней транзакции
    if last_tx_id is None:
        transactions = get_transactions()
        if transactions:
            last_tx_id = transactions[0].get("hash", "unknown")  # Самая новая транзакция
            save_last_tx_id(last_tx_id)
            print(f"Установлен начальный last_tx_id: {last_tx_id}")
        else:
            print("Не удалось получить транзакции для инициализации last_tx_id")
            last_tx_id = "unknown"

    while True:
        transactions = get_transactions()
        if transactions:
            # Берем только самую новую транзакцию (первая в списке)
            latest_tx = transactions[0]
            tx_id = latest_tx.get("hash", "unknown")

            # Если транзакция новая (отличается от last_tx_id), отправляем только ее
            if tx_id != last_tx_id:
                try:
                    message = format_transaction(latest_tx)
                    await send_message(CHAT_ID, message)  # Отправляем только новую транзакцию
                    last_tx_id = tx_id
                    save_last_tx_id(last_tx_id)  # Обновляем last_tx_id
                    print(f"Отправлена новая транзакция: {tx_id}")
                except Exception as e:
                    print(f"Ошибка отправки: {e}")
            else:
                print(f"Нет новых транзакций, последняя обработанная: {last_tx_id}")
        else:
            print("Транзакций не найдено или ошибка API")
        await asyncio.sleep(10)  # Проверка каждые 10 секунд


if __name__ == "__main__":
    asyncio.run(main())