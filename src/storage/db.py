# 檔名：db.py
# 專案路徑：src/storage/db.py
# 功能：連線池管理、取得連線、簡易 DAO 封裝、健康檢查。

import os
import pymysql
import threading
from typing import Any, Dict, Optional, Callable, Iterable, List

from src.common.env_loader import load_env, get_env

# 初始化環境變數（若 .env 存在會載入，讓下方用 get_env 取得設定）
load_env()

def _get_pool_size(default: int = 5) -> int:
    # 連線池大小可由環境變數 DB_POOL_SIZE 控制，預設 5
    raw = get_env("DB_POOL_SIZE", str(default))
    try:
        return int(raw)
    except Exception:
        return default

class MySQLPool:
    """
    非阻塞、簡易版的連線池：
    - 使用 list 當作池，配合 Lock 確保執行緒安全
    - acquire：若池內有連線就取出，否則新建
    - release：若池未滿放回，否則關閉
    - closeall：關閉池內所有連線
    """
    def __init__(self, maxsize: int = 5):
        self._maxsize = maxsize
        self._pool: List[pymysql.connections.Connection] = []
        self._lock = threading.Lock()
        self._config = {
            "host": get_env("DB_HOST", "localhost"),
            "port": int(get_env("DB_PORT", "3306")),
            "user": get_env("DB_USER", "root"),
            "password": get_env("DB_PASSWORD", ""),
            "database": get_env("DB_NAME", "twa_etf_engine"),
            "charset": "utf8mb4",
            "cursorclass": pymysql.cursors.DictCursor,  # 讓 fetch 回來是 dict，便於後續處理
            "autocommit": False,                        # 由 Dao 控制交易
        }

    def _create_conn(self) -> pymysql.connections.Connection:
        # 以目前設定建立新連線
        return pymysql.connect(**self._config)

    def acquire(self) -> pymysql.connections.Connection:
        # 取得連線：優先用池內現有連線，否則建立新連線
        with self._lock:
            if self._pool:
                return self._pool.pop()
            return self._create_conn()

    def release(self, conn: pymysql.connections.Connection) -> None:
        # 釋放連線：若池未滿則放回，否則關閉（避免池無限制增長）
        with self._lock:
            try:
                if len(self._pool) < self._maxsize:
                    self._pool.append(conn)
                else:
                    conn.close()
            except Exception:
                # 發生例外時保守起見嘗試關閉連線
                try:
                    conn.close()
                except Exception:
                    pass

    def closeall(self) -> None:
        # 關閉池內所有連線（通常在進程結束或重啟時）
        with self._lock:
            for c in self._pool:
                try:
                    c.close()
                except Exception:
                    pass
            self._pool.clear()

# 建立單例連線池（整個程序共用）
_pool = MySQLPool(maxsize=_get_pool_size())

def get_conn() -> pymysql.connections.Connection:
    # 封裝取得連線，統一由 _pool 供應
    return _pool.acquire()

def release_conn(conn: pymysql.connections.Connection) -> None:
    # 釋放連線回池
    _pool.release(conn)

def with_conn(func: Callable[[pymysql.connections.Connection], Any]) -> Any:
    """
    常用連線管理工具：
    - 從池取得連線
    - 執行函式 func(conn)
    - 無論成功與否都釋放連線（finally）
    """
    conn = get_conn()
    try:
        result = func(conn)
        return result
    finally:
        release_conn(conn)

class Dao:
    """
    最小可用的 DAO 封裝：
    - execute：單次 SQL 執行，回傳受影響列數
    - executemany：迭代 rows 並逐筆執行（此版本非真正的批次協議，但簡單穩定）
    - query：執行查詢並回傳 list[dict]
    - commit/rollback：交易控制（autocommit=False）
    """
    @staticmethod
    def execute(conn: pymysql.connections.Connection, sql: str, params: Optional[Dict[str, Any]] = None) -> int:
        # 注意：若 SQL 使用 %(key)s 命名參數，params 必須是 dict（mapping）
        with conn.cursor() as cur:
            cur.execute(sql, params or {})
            return cur.rowcount

    @staticmethod
    def executemany(conn: pymysql.connections.Connection, sql: str, rows: Iterable[Dict[str, Any]]) -> int:
        # 逐筆執行，每筆回傳 rowcount 相加，適用命名參數的 dict rows
        affected = 0
        with conn.cursor() as cur:
            for r in rows:
                cur.execute(sql, r)  # 若 r 不是 dict，且 SQL 用 %(key)s，將觸發「format requires a mapping」
                affected += cur.rowcount
        return affected

    @staticmethod
    def query(conn: pymysql.connections.Connection, sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        # 查詢並回傳所有結果（list of dict）
        with conn.cursor() as cur:
            cur.execute(sql, params or {})
            return list(cur.fetchall())

    @staticmethod
    def commit(conn: pymysql.connections.Connection) -> None:
        # 提交交易
        conn.commit()

    @staticmethod
    def rollback(conn: pymysql.connections.Connection) -> None:
        # 回滾交易
        conn.rollback()

def healthcheck() -> bool:
    """
    執行最小查詢以檢查 DB 連線是否可用：
    - SELECT 1 AS ok
    - 回傳 True 表示健康
    """
    def _hc(c: pymysql.connections.Connection) -> bool:
        try:
            with c.cursor() as cur:
                cur.execute("SELECT 1 AS ok")
                row = cur.fetchone()
                # 因為使用 DictCursor，row 為 dict，取出 ok 應為 1
                return bool(row and row.get("ok") == 1)
        except Exception:
            return False
    return with_conn(_hc)
