import requests
import json
import time
import sys

GAS_URL = "https://script.google.com/macros/s/AKfycbyCvyQ4olHYLela7UIWwwlb2TmhpW0pGTUe21JsRnIgmTti3DT4v-sRTb2ouVBxSqiH/exec"
OUTPUT_FILE = "data.json"
INTERVAL = 15  # секунд между запросами

def fetch_and_save():
    try:
        resp = requests.get(GAS_URL, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException as e:
        print(f"Ошибка при запросе: {e}")
        return False
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
            # При ошибке ждём подольше, чтобы не нагружать сервер
            time.sleep(INTERVAL * 2)
        else:
            time.sleep(INTERVAL)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nСкрипт остановлен пользователем.")
        sys.exit(0)