# 檔名：run_etf_scan.py
# 專案路徑：src/jobs/run_etf_scan.py
# 功能：主流程，載入環境、健康檢查、呼叫 TWSE、解析一筆、入庫。

from typing import Dict, Any, List
from rich.console import Console
import time
import os

from src.common.env_loader import load_env, get_env, require_env
from src.storage.db import healthcheck
from src.storage.terminal import clear_terminal

from src.datasource.twse import fetch_twse_etf_symbols, fetch_twse_etf_detail
from src.services.etf_loader import parse_product_content_to_row, upsert_etf_metadata

def _env_source_summary() -> str:
    """
    回傳環境來源摘要，協助判斷為何 .env 未載入仍可連線。
    """
    sources: List[str] = []
    if os.getenv("DOCKER") or os.getenv("COMPOSE_PROJECT_NAME"):
        sources.append("docker-compose")
    if os.getenv("KUBERNETES_SERVICE_HOST"):
        sources.append("kubernetes")
    if any(k.startswith("GITHUB_") for k in os.environ):
        sources.append("github-actions")
    if os.getenv("VIRTUAL_ENV") or os.getenv("CONDA_PREFIX"):
        sources.append("virtualenv/conda")
    return ", ".join(sources) or "system env"

def main() -> None:
    console = Console()
    t0 = time.time()

    # 標題線，顯示 Job 名稱
    console.rule("run_etf_scan for src/jobs/run_etf_scan.py")

    # 載入 .env：
    # - 生產/CI 建議 override=False（尊重系統環境）
    # - 本地測試如需覆蓋可改 True
    loaded_env = load_env(override=True)
    if loaded_env:
        console.print(f"[cyan]已載入 .env 參數[/cyan]: {len(loaded_env)} keys")
    else:
        console.print("[yellow]未找到 .env 或無新參數載入[/yellow]")
        console.print(f"[dim]環境來源推測[/dim]: {_env_source_summary()}")

    # 選擇性：檢查必要環境變數（若你希望在這裡卡住缺失）
    # 例如 DB 連線基本設定，能更快在啟動階段發現問題
    try:
        required = require_env(["DB_HOST", "DB_PORT", "DB_USER", "DB_NAME"])
        console.print(f"[cyan]DB 目標[/cyan]: {required['DB_USER']}@{required['DB_HOST']}:{required['DB_PORT']}/{required['DB_NAME']}")
    except KeyError as e:
        console.print(f"[red]環境變數缺失[/red]: {e}")
        return

    # 連線健康檢查：若資料庫不可用，提早結束避免後續流程報錯
    if not healthcheck():
        raise RuntimeError("資料庫連線健康檢查失敗，請確認 .env 設定與 DB 狀態")

    # 取得當前 TWSE RWD ETF 列表的所有代碼
    try:
        symbols = fetch_twse_etf_symbols()
        console.print(f"[cyan]ETF 代碼數[/cyan]: {len(symbols)}")
    except Exception as e:
        console.print(f"[red]取得 ETF 代碼失敗[/red]: {e}")
        return

    if not symbols:
        console.print("[yellow]ETF 代碼清單為空[/yellow]")
        return

    # 依環境變數設定每筆請求間隔，避免頻率過高被限流；預設 60 秒
    try:
        rate_delay = float(get_env("TWSE_RATE_LIMIT_DELAY", "60"))
    except ValueError:
        rate_delay = 60.0
        console.print("[yellow]TWSE_RATE_LIMIT_DELAY 非數值，採用預設 60 秒[/yellow]")

    rows: List[Dict[str, Any]] = []

    # 逐筆處理代碼：抓詳細、解析成 row、累積 rows、整批 upsert
    for i, code in enumerate(symbols, start=1):
        try:
            detail = fetch_twse_etf_detail(code)
            row = parse_product_content_to_row(detail)
            rows.append(row)

            # 整批 UPSERT：將目前累積的 rows 寫入
            if rows:
                try:
                    affected = upsert_etf_metadata(rows)
                    console.print(f"[green]UPSERT rows affected[/green]: {affected}")
                    # 成功寫入後立刻清空暫存，避免重複寫同批資料
                    rows.clear()
                except Exception as e:
                    console.print(f"[red]入庫失敗[/red] code={code}: {e}")
            else:
                console.print("[yellow]無有效資料可入庫[/yellow]")

            console.print(f"[green]{i}/{len(symbols)}[/green] 已解析：{code} -> {row['short_name']}")

        except Exception as e:
            console.print(f"[red]解析失敗[/red] code={code}: {e}")

        # 頻率限制間隔：避免對 TWSE RWD API 發送過於頻繁的請求
        # 注意：最後一圈 sleep 雖非必要，但保留一致行為影響不大
        time.sleep(rate_delay)

    elapsed = time.time() - t0
    console.print(f"[cyan]總耗時[/cyan]: {elapsed:.2f}s")

if __name__ == "__main__":
    clear_terminal()
    main()
