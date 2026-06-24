import requests
import json
import time
import sys
import ssl
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager

# Специальный адаптер, решающий проблему SSLEOFError
class CustomHttpAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        # Понижаем уровень безопасности шифров (Google иногда обрывает соединение при высоком уровне)
        context.set_ciphers('DEFAULT@SECLEVEL=1')
        # Явно разрешаем TLS 1.2 (Google требует минимум 1.2)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        kwargs['ssl_context'] = context
        return super().init_poolmanager(*args, **kwargs)

# ⚠️ ВАЖНО: Вставьте актуальный URL вашего веб-приложения
GAS_URL = "https://script.google.com/macros/s/AKfycbwg3hTZ1mt0C7-O0l8q2hYI2o9ICRsbXKx1jpRfydA7DibDU3R5zol_CqznCzUADkuI/exec"
OUTPUT_FILE = "data.json"
INTERVAL = 15  # секунд между успешными запросами
MAX_RETRIES = 3

def fetch_and_save():
    # Создаём сессию с нашим адаптером
    session = requests.Session()
    adapter = CustomHttpAdapter()
    session.mount('https://', adapter)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    })

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(GAS_URL, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            break
        except requests.exceptions.SSLError as e:
            print(f"SSL ошибка (попытка {attempt}): {e}")
            if attempt == MAX_RETRIES:
                return False
            time.sleep(5)
        except requests.exceptions.RequestException as e:
            print(f"Ошибка при запросе (попытка {attempt}): {e}")
            if attempt == MAX_RETRIES:
                return False
            time.sleep(5)
        except json.JSONDecodeError as e:
            print(f"Ошибка разбора JSON: {e}")
            return False

    if isinstance(data, dict) and "error" in data:
        print(f"Ошибка Apps Script: {data['error']}")
        return False

    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Сохранено {len(data)} записей в {OUTPUT_FILE}")
        return True
    except IOError as e:
        print(f"Ошибка записи файла: {e}")
        return False

def main():
    print("Запуск непрерывного обновления. Нажмите Ctrl+C для остановки.")
    while True:
        success = fetch_and_save()
        if not success:
            time.sleep(INTERVAL * 2)
        else:
            time.sleep(INTERVAL)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nСкрипт остановлен пользователем.")
        sys.exit(0)