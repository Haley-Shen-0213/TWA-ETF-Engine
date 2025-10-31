# 檔名：etf_loader.py
# 專案路徑：src/services/etf_loader.py
# 功能：解析 TWSE ETF 資料、推導屬性、UPSERT 入庫

import json
import datetime
import re
from typing import Any, Dict, List, Optional

from src.storage.db import Dao, with_conn

# 預設交易時間（若 TWSE 未提供精確時段，使用此預設）
DEFAULT_TRADING_HOURS = {
    "regular": {"start": "09:00", "end": "13:30"},
    "after_hours": {"odd_lot": "13:40-14:30"}
}
# 預設價位區間與 tick（當文字無法解析時使用）
DEFAULT_TICK_STEPS = [
    {"min": 0, "max": 10, "tick": 0.01},
    {"min": 10, "max": 50, "tick": 0.05},
    {"min": 50, "max": 100, "tick": 0.1},
    {"min": 100, "max": 500, "tick": 0.5},
    {"min": 500, "max": 1000, "tick": 5},
    {"min": 1000, "max": None, "tick": 10}
]
DEFAULT_TAX_RATE = 0.001          # 預設交易稅率（千分之一）
DEFAULT_EXCHANGE = "TWSE"         # 預設交易所
DEFAULT_LOT_SIZE = 1000           # 預設交易單位（張/受益權單位）
FALLBACK_LISTING_DATE = "2000-01-01"  # 日期解析失敗時的保底

# MySQL 相容語法的 UPSERT（使用 ON DUPLICATE KEY UPDATE）
# 注意：表 etf_metadata 需要在 symbol 欄位建立 UNIQUE 索引以啟用此語法
UPSERT_SQL = """
INSERT INTO etf_metadata (
    symbol, short_name, category, listing_date,
    tick_unit, tick_steps, trading_hours,
    transaction_tax_rate, lot_size, exchange, distribution_policy
) VALUES (
    %(symbol)s, %(short_name)s, %(category)s, %(listing_date)s,
    %(tick_unit)s, %(tick_steps)s, %(trading_hours)s,
    %(transaction_tax_rate)s, %(lot_size)s, %(exchange)s, %(distribution_policy)s
) ON DUPLICATE KEY UPDATE
    short_name = VALUES(short_name),
    category = VALUES(category),
    listing_date = VALUES(listing_date),
    tick_unit = VALUES(tick_unit),
    tick_steps = VALUES(tick_steps),
    trading_hours = VALUES(trading_hours),
    transaction_tax_rate = VALUES(transaction_tax_rate),
    lot_size = VALUES(lot_size),
    exchange = VALUES(exchange),
    distribution_policy = VALUES(distribution_policy);
"""

def _normalize_date_to_iso(date_str: str) -> Optional[str]:
    """
    支援 2025-05-22 / 2025/05/22 / 2025.05.22 → 2025-05-22
    若無法解析回傳 None
    """
    if not date_str:
        return None
    s = date_str.strip()
    # 只取前 10 字避免混入時間
    s = s[:10]
    # 將 . 或 / 轉成 -
    s = s.replace("/", "-").replace(".", "-")
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)
    if not m:
        return None
    y, mo, d = m.groups()
    return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"

def _extract_int_from_text(text: str) -> Optional[int]:
    """
    從如 '1,000個受益權單位' 抽取 1000
    - 移除逗號後找連續數字
    """
    if not isinstance(text, str):
        return None
    digits = re.findall(r"\d+", text.replace(",", ""))
    if not digits:
        return None
    try:
        return int("".join(digits))
    except Exception:
        return None

def _parse_tax_rate(text: str) -> Optional[float]:
    """
    支援以下格式：
    - '0.1%' → 0.001
    - '千分之一' → 0.001
    - '千分之N' → N/1000（簡單中文數字映射 1~10）
    其他無法解析 → None
    """
    if not isinstance(text, str):
        return None
    s = text.strip()
    # 百分比格式
    m = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*%\s*$", s)
    if m:
        return float(m.group(1)) / 100.0
    # 千分之N（中文）
    m = re.search(r"千分之\s*([一二三四五六七八九十百千萬0-9\.]+)", s)
    if m:
        num = m.group(1)
        mapping = {"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9,"十":10}
        if num in mapping:
            return mapping[num] / 1000.0
        try:
            return float(num) / 1000.0
        except Exception:
            pass
    # 明確字樣
    if "千分之一" in s:
        return 1/1000.0
    return None

def _parse_tick_steps_from_text(text: str) -> Optional[List[Dict[str, Any]]]:
    """
    嘗試從自然語言描述解析價位區間與 tick。
    例如：'每受益權單位市價未滿50元者為0.01元；50元以上為0.05元'
    - 實務上描述多變，此處採寬鬆策略：抽出數字序列，推估兩段區間。
    - 若無法安全推估，回傳 None 交由預設值處理。
    """
    if not isinstance(text, str) or not text.strip():
        return None
    s = text.replace("；", ";").replace("，", ",")
    # 寬鬆解析：找出所有數字，常見會得到 [threshold, tick1, threshold2?, tick2]
    nums = re.findall(r"[0-9]+(?:\.[0-9]+)?", s)
    if len(nums) >= 3:
        try:
            threshold = float(nums[0])     # 第一個數字視為區分門檻
            tick1 = float(nums[1])         # 第二個為低於門檻 tick
            tick2 = float(nums[-1])        # 最後一個為高於門檻 tick
            steps = [
                {"min": 0, "max": threshold, "tick": tick1},
                {"min": threshold, "max": None, "tick": tick2},
            ]
            return steps
        except Exception:
            return None
    return None

def derive_tick_unit_from_steps(steps: Optional[List[Dict[str, Any]]]) -> float:
    """
    從 tick_steps 取最小 tick 值作為 tick_unit
    """
    if not steps:
        steps = DEFAULT_TICK_STEPS
    ticks = []
    for seg in steps:
        try:
            ticks.append(float(seg["tick"]))
        except Exception:
            continue
    return min(ticks) if ticks else 0.01

def normalize_date_any(s: Optional[str]) -> Optional[str]:
    # 寬鬆日期正規化，支援三種分隔
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            dt = datetime.datetime.strptime(s, fmt).date()
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None

def _as_int(s: Any) -> Optional[int]:
    # 將輸入轉為整數（移除非數字字元），失敗回 None
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return int(s)
    if isinstance(s, str):
        digits = "".join(ch for ch in s if ch.isdigit())
        return int(digits) if digits.isdigit() else None
    return None

def _guess_distribution_policy(detail: Dict[str, Any]) -> str:
    """
    嘗試從不同結構的欄位推估配息政策：
    - 先看 detail["data"]、["fundInfo"]、["description"] 的直屬鍵
    - 再嘗試 list 結構如 dataList/infoList/basicInfo 中的 [key, value]
    找不到時回傳 '未提供'
    """
    candidates = [
        ("data", "配息"), ("data", "收益分配"), ("data", "配息頻率"),
        ("fundInfo", "dividendPolicy"), ("fundInfo", "distribution"),
        ("description", "配息"), ("description", "收益分配")
    ]
    for parent, key in candidates:
        parent_obj = detail.get(parent)
        if isinstance(parent_obj, dict):
            v = parent_obj.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
    # list 結構的回退策略
    for parent in ("dataList", "infoList", "basicInfo"):
        arr = detail.get(parent)
        if isinstance(arr, list):
            for row in arr:
                if isinstance(row, list) and len(row) >= 2:
                    k, v = str(row[0]), str(row[1])
                    if any(kw in k for kw in ("配息", "收益分配", "配息頻率")) and v.strip():
                        return v.strip()
    return "未提供"

def parse_product_content_to_row(detail: Dict[str, Any]) -> Dict[str, Any]:
    """
    將 TWSE 商品內容 JSON 解析為 etf_metadata 表的一筆資料列（dict）。
    - 使用 tables[0].fields 與 tables[0].data[0] 一一對應抽取欄位
    - category 優先取 tables[0] 的「ETF類別」，其次使用最外層 type
    - 對交易單位/稅率/日期/升降單位做必要正規化與推導
    """
    # 基本狀態檢查
    stat = str(detail.get("stat", "")).lower()
    if stat != "ok":
        raise ValueError(f"productContent stat 非 ok: {detail.get('stat')}")

    tables = detail.get("tables")
    if not isinstance(tables, list) or not tables:
        raise ValueError("tables 結構缺失或為空")

    main = tables[0]
    fields = main.get("fields") or []
    data = main.get("data") or []
    if not isinstance(fields, list) or not fields:
        raise ValueError("tables[0].fields 缺失")
    if not isinstance(data, list) or not data or not isinstance(data[0], list):
        raise ValueError("tables[0].data 缺失或格式不正確")

    row = data[0]
    # 建立欄位名稱到索引的對照表，方便以名稱取值
    idx = {name: i for i, name in enumerate(fields)}

    def get_field(name: str) -> Optional[str]:
        # 依欄位名取值，並盡量轉成字串回傳
        if name not in idx:
            return None
        i = idx[name]
        if i >= len(row):
            return None
        v = row[i]
        return v if isinstance(v, str) else (str(v) if v is not None else None)

    # 關鍵欄位：證券代號（symbol）
    symbol = (get_field("證券代號") or "").strip()
    if not symbol:
        raise ValueError("缺少必要欄位：證券代號")

    # 簡稱：優先取「ETF簡稱」，次之「名稱」或 main.title，再不行用 symbol 兜底
    short_name = (get_field("ETF簡稱") or "").strip()
    if not short_name:
        short_name = (get_field("名稱") or main.get("title") or symbol).strip()

    # 類別：優先取「ETF類別」，其次 detail["type"]，最後兜底 "ETF"
    category = (get_field("ETF類別") or detail.get("type") or "").strip() or "ETF"

    # 上市日期：正規化為 YYYY-MM-DD，失敗給 FALLBACK_LISTING_DATE
    raw_date = (get_field("上市日期") or "").strip()
    listing_date = _normalize_date_to_iso(raw_date) or FALLBACK_LISTING_DATE

    # 交易單位（lot_size）：從描述中抽取整數，預設 1000
    lot_size_text = get_field("交易單位") or ""
    lot_size = _extract_int_from_text(lot_size_text) or 1000

    # 交易稅率：支援多格式解析，失敗用 DEFAULT_TAX_RATE
    tax_text = get_field("證券交易稅") or ""
    tax_rate = _parse_tax_rate(tax_text)
    transaction_tax_rate = tax_rate if tax_rate is not None else DEFAULT_TAX_RATE

    # 升降單位：嘗試解析 tick_steps；失敗使用預設；tick_unit 取最小 tick
    tick_text = get_field("升降單位") or ""
    parsed_steps = _parse_tick_steps_from_text(tick_text)
    tick_steps = parsed_steps if parsed_steps else DEFAULT_TICK_STEPS
    tick_unit = derive_tick_unit_from_steps(tick_steps)

    # 收益分配：若欄位不存在以「未提供」表示
    distribution_policy = (get_field("收益分配") or "").strip() or "未提供"

    # 交易時間：若未解析出實際時段，採用預設
    trading_hours = DEFAULT_TRADING_HOURS

    # 注意：tick_steps 與 trading_hours 存成 JSON 字串，以便直接存入 TEXT/JSON 欄位
    return {
        "symbol": symbol,
        "short_name": short_name,
        "category": category,
        "listing_date": listing_date,
        "tick_unit": tick_unit,
        "tick_steps": json.dumps(tick_steps, ensure_ascii=False),
        "trading_hours": json.dumps(trading_hours, ensure_ascii=False),
        "transaction_tax_rate": transaction_tax_rate,
        "lot_size": lot_size,
        "exchange": DEFAULT_EXCHANGE,
        "distribution_policy": distribution_policy,
    }

def upsert_etf_metadata(rows: List[Dict[str, Any]]) -> int:
    """
    將解析好的多筆 rows 以 UPSERT_SQL 一次性寫入/更新。
    - 使用 Dao.executemany 逐筆執行（以確保每筆 mapping 與命名參數 %(key)s 對齊）
    - 成功則 commit，失敗則 rollback 並拋出例外
    回傳：受影響列數（rowcount 累計）
    """
    def _op(conn):
        try:
            # 關鍵：此 SQL 使用命名參數 %(key)s，因此 rows 需為 dict 的 iterable（mapping）
            affected = Dao.executemany(conn, UPSERT_SQL, rows)
            Dao.commit(conn)
            return affected
        except Exception as e:
            # 發生任何錯誤都要回滾，避免部分寫入
            Dao.rollback(conn)
            raise e
    # 使用 with_conn 管理連線生命週期（取得、釋放）
    return with_conn(_op)
