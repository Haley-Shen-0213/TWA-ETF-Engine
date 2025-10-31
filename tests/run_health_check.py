# 路徑：tests/run_health_check.py
# 功能：測試資料庫連線以及 Google API 連線是否正常

import os
import sys
from datetime import datetime
from src.storage.terminal import clear_terminal
from rich.console import Console

# 確保可以匯入 src/common
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.append(SRC_DIR)

from src.common.env_loader import load_env, get_env, require_env  # 使用你提供的環境讀取工具


def test_mysql_connection() -> bool:
    """使用 .env 的 DB_* 參數測試 MySQL 連線與簡單查詢"""
    try:
        import mysql.connector
        from mysql.connector import Error
    except ImportError:
        print("[MySQL] 缺少套件：mysql-connector-python，請先安裝：pip install mysql-connector-python")
        return False

    # 讀取必要參數
    load_env()  # 確保 .env 已載入
    require_env(["DB_HOST", "DB_USER", "DB_PASSWORD"])  # DB_PORT/DB_NAME 可有預設
    db_host = get_env("DB_HOST", "localhost")
    db_port = int(get_env("DB_PORT", "3306"))
    db_user = get_env("DB_USER")
    db_password = get_env("DB_PASSWORD")
    db_name = get_env("DB_NAME", "etf_trader")

    print("[MySQL] 連線測試開始...")
    try:
        conn = mysql.connector.connect(
            host=db_host,
            port=db_port,
            user=db_user,
            password=db_password,
            database=db_name,
            charset="utf8mb4",
            autocommit=True,
        )
        cursor = conn.cursor()
        cursor.execute("SELECT VERSION()")
        version = cursor.fetchone()[0]
        print(f"[MySQL] 已連線，版本: {version}")

        cursor.execute("SHOW TABLES")
        tables = cursor.fetchall()
        print(f"[MySQL] 當前資料庫 {db_name} 有 {len(tables)} 張表")

        cursor.close()
        conn.close()
        return True
    except Error as e:
        print(f"[MySQL] 連線失敗: {e}")
        return False


def get_sheets_service():
    """建立 Google Sheets API Service 物件"""
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        print("[Sheets] 缺少套件：google-api-python-client 或 google-auth，請先安裝：")
        print("pip install google-api-python-client google-auth google-auth-httplib2")
        raise

    load_env()
    require_env(["GOOGLE_SERVICE_ACCOUNT_JSON"])
    service_account_file = get_env("GOOGLE_SERVICE_ACCOUNT_JSON", required=True)

    if not os.path.isfile(service_account_file):
        raise FileNotFoundError("找不到 Service Account JSON，請檢查 GOOGLE_SERVICE_ACCOUNT_JSON 路徑")

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(service_account_file, scopes=scopes)
    service = build("sheets", "v4", credentials=creds)
    return service


def test_sheets_connection() -> bool:
    """測試 Google Sheets 的寫入與讀取"""
    load_env()
    require_env(["SHEET_ID", "GOOGLE_SERVICE_ACCOUNT_JSON"])
    sheet_id = get_env("SHEET_ID")

    print("[Sheets] 連線測試開始...")
    try:
        service = get_sheets_service()
        sheets = service.spreadsheets()

        # 寫入表頭
        range_name = "HealthCheck!A1:D1"
        values = [["service", "status", "timestamp", "note"]]
        body = {"values": values}
        sheets.values().update(
            spreadsheetId=sheet_id,
            range=range_name,
            valueInputOption="RAW",
            body=body,
        ).execute()

        # 追加一筆測試資料
        append_values = [["sheets_api", "ok", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "initial check"]]
        append_body = {"values": append_values}
        sheets.values().append(
            spreadsheetId=sheet_id,
            range="HealthCheck!A2",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body=append_body,
        ).execute()

        # 讀取剛寫入的資料
        resp = sheets.values().get(
            spreadsheetId=sheet_id,
            range="HealthCheck!A1:D10",
        ).execute()
        rows = resp.get("values", [])
        print(f"[Sheets] 讀取成功，共 {len(rows)} 列。第一列: {rows[0] if rows else 'N/A'}")
        return True
    except Exception as e:
        print(f"[Sheets] 連線/寫入失敗: {e}")
        print("提示：請確認試算表已分享給 Service Account 的 email，並且該分頁名稱為 'HealthCheck'")
        return False


def main():
    # 美化輸出（分隔線、標題等）
    console = Console()
    console.rule(f"run_health_check for tests/run_health_check.py")
    print("=== 連線健康檢查開始 ===")
    ok_db = test_mysql_connection()
    ok_sheet = test_sheets_connection()
    all_ok = ok_db and ok_sheet
    print(f"=== 結果: MySQL={'OK' if ok_db else 'FAIL'}, Sheets={'OK' if ok_sheet else 'FAIL'} ===")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    clear_terminal()
    main()
