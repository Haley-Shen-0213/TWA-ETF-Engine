# 檔名：twse.py
# 專案路徑：src/datasource/twse.py
# 功能：TWSE RWD ETF 兩階段抓取：先列表取代碼，再逐一商品內容

import time
import certifi
import requests
from typing import Any, Dict, List, Optional
from src.common.env_loader import get_env

# RWD 端點（可由環境變數覆寫）
DEFAULT_LIST_URL = "https://www.twse.com.tw/rwd/zh/ETF/list?response=json"
DEFAULT_PRODUCT_URL_TMPL = "https://www.twse.com.tw/rwd/zh/ETF/productContent?id={code}&response=json"

def _get_timeout(default: float = 10.0) -> float:
    # 從環境讀取 TWSE_TIMEOUT，提供請求逾時秒數
    raw = get_env("TWSE_TIMEOUT", str(default))
    try:
        return float(raw)
    except Exception:
        return default

def _get_verify_ssl(default: bool = False) -> bool:
    # 是否驗證 SSL 憑證，TWSE 常見需關閉驗證以避免阻擋
    raw = (get_env("TWSE_VERIFY_SSL", "false") or "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    return default

def _get_debug() -> bool:
    # 除錯模式，開啟後會列印重導歷史與回應摘要
    raw = (get_env("TWSE_DEBUG", "0") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")

def _get_retries(default: int = 3) -> int:
    # 請求重試次數
    raw = (get_env("TWSE_RETRIES", str(default)) or "").strip()
    try:
        v = int(raw)
        return max(1, v)
    except Exception:
        return default

def _get_retry_backoff(default: float = 1.2) -> float:
    # 重試退避係數，與嘗試次序相乘（線性倍增），並加入抖動
    raw = (get_env("TWSE_RETRY_BACKOFF", str(default)) or "").strip()
    try:
        v = float(raw)
        return v if v > 0 else default
    except Exception:
        return default

def _get_rate_limit_delay(default: float = 0.3) -> float:
    # 輕量速率控制（此檔內很少直接用，主要在 job 檔）
    raw = (get_env("TWSE_RATE_LIMIT_DELAY", str(default)) or "").strip()
    try:
        v = float(raw)
        return v if v >= 0 else default
    except Exception:
        return default

def _headers() -> Dict[str, str]:
    # 基礎標頭：User-Agent 可由環境變數覆寫
    ua = (get_env("TWSE_USER_AGENT", "TWA-ETF-Engine/1.0 (+https://example.com) Python-requests") or "").strip()
    return {
        "User-Agent": ua,
        "Accept": "application/json, text/plain, */*",
        "Connection": "close",
    }

def _verify_target() -> bool | str:
    # 回傳 verify 參數（cert 檔路徑或 False）
    verify_ssl = _get_verify_ssl()
    if verify_ssl:
        # 使用 certifi 提供的 CA
        return certifi.where()
    else:
        # 若關閉 SSL 驗證，順帶關閉噪音警告
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            pass
        return False

def _request_json(url: str, timeout: float, retries: int, backoff: float) -> Dict[str, Any]:
    """
    統一 GET 並解析 JSON：
    - 依設定可關閉 SSL 驗證（默認 False）
    - 顯示重導歷史（debug 模式）
    - 僅在 Content-Type 為 application/json 時解析 JSON
    - 若非 JSON，將前 2048 字內容存檔，方便檢視是否被 HTML/WAF 攔截
    - 重試策略：線性倍增 + 抖動
    """
    import random
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # 準備請求標頭，補齊常見欄位避免被擋
    base_headers = _headers()
    if "Accept" not in base_headers:
        base_headers["Accept"] = "application/json, text/plain, */*"
    if "Accept-Language" not in base_headers:
        base_headers["Accept-Language"] = "zh-TW,zh;q=0.9,en;q=0.8"
    if "Connection" not in base_headers:
        base_headers["Connection"] = "keep-alive"
    # RWD 端點常見需要 Referer/Origin
    base_headers.setdefault("Referer", "https://www.twse.com.tw/rwd/zh/ETF/")
    base_headers.setdefault("Origin", "https://www.twse.com.tw")

    debug = _get_debug()
    last_exc: Optional[Exception] = None

    # 使用 Session 可重用連線，並保留 cookies 與重導資訊
    with requests.Session() as sess:
        for attempt in range(1, retries + 1):
            try:
                resp = sess.get(
                    url,
                    headers=base_headers,
                    timeout=timeout,
                    verify=False,               # 依需求固定關閉驗證（可切到 _verify_target()）
                    allow_redirects=True,
                )

                # debug：列出重導歷史與最終 URL/狀態碼
                if debug and resp.history:
                    print(f"[TWSE] Redirect history ({len(resp.history)}):")
                    for i, h in enumerate(resp.history, 1):
                        print(f"  {i}. {h.status_code} -> {h.headers.get('Location')}")
                if debug:
                    print(f"[TWSE] Final URL: {resp.url} | Status: {resp.status_code}")

                # 若非 2xx 會 raise_for_status
                resp.raise_for_status()

                # 僅接受 JSON 回應
                ctype = (resp.headers.get("Content-Type") or "").lower()
                if "application/json" not in ctype:
                    # 將內容前 2048 字落盤，方便檢查是否 WAF/HTML
                    txt = resp.text or ""
                    snippet = txt[:2048]
                    dump_path = "twse_last_error_snippet.txt"
                    try:
                        with open(dump_path, "w", encoding="utf-8") as f:
                            f.write(snippet)
                    except Exception:
                        pass
                    raise ValueError(
                        f"非 JSON 回應（Content-Type={ctype}）於 {resp.url}；已落盤前2048字到 {dump_path}"
                    )

                data = resp.json()
                if not isinstance(data, dict):
                    raise ValueError(f"預期 dict，實得 {type(data)}")

                if debug:
                    preview = str(data)[:300]
                    print(f"[TWSE] GET {url} -> OK, json_len≈{len(str(data))}, preview={preview!r}")

                return data

            except (requests.RequestException, ValueError) as e:
                # 記錄最後一次錯誤，並視重試次數決定是否繼續
                last_exc = e
                if debug:
                    print(f"[TWSE] 嘗試 {attempt}/{retries} 失敗：{e}")
                if attempt == retries:
                    break
                # 線性倍增退避 + 少量抖動，降低節流/風控命中
                sleep_sec = backoff * attempt + random.uniform(0, 0.25)
                time.sleep(sleep_sec)

    # 重試用盡仍失敗，丟出 RuntimeError
    raise RuntimeError(f"請求失敗: {url}; 最後錯誤: {last_exc}")

def fetch_twse_etf_symbols() -> List[str]:
    """
    從 TWSE ETF 列表端點解析出所有可用的 ETF 證券代號。
    注意：
    - fields: ["上市日期", "證券代號", "證券簡稱", "發行人", "標的指數"]
    - 第二欄才是「證券代號」
    - 代號可能含有 <br> 分隔的多幣別（如 006205<br>00625K），以及括號附註（如 (新臺幣)）
    """
    # 使用時間戳避免 CDN 快取
    base = get_env("TWSE_LIST_URL", DEFAULT_LIST_URL)
    ts = int(time.time() * 1000)
    url = f"{base}&_={ts}"
    timeout = _get_timeout()
    retries = _get_retries()
    backoff = _get_retry_backoff()

    # 發請求並檢查狀態
    data = _request_json(url, timeout, retries, backoff)
    stat = str(data.get("stat") or "").upper()
    if stat != "OK":
        raise RuntimeError(f"列表 stat 非 OK: {stat}")

    rows = data.get("data") or []
    if not isinstance(rows, list):
        raise ValueError("列表欄位 data 非 list")

    def normalize_codes(code_field: str) -> List[str]:
        """
        將「證券代號」欄位清理為一或多個乾淨代號。
        規則：
        - 將 <br> 視為分隔成多段（含 \u003Cbr\u003E）
        - 去掉括號附註（006205(新臺幣) -> 006205）
        - 去除空白
        - 僅保留英數字元
        """
        if not code_field:
            return []
        s = str(code_field)

        # 轉換編碼型 <br>
        s = s.replace("\u003Cbr\u003E", "<br>")
        parts = [p for p in s.split("<br>") if p]

        out: List[str] = []
        for p in parts:
            # 去掉第一個 '(' 之後的文字
            if "(" in p:
                p = p.split("(", 1)[0]
            p = p.strip()
            # 僅保留英數，過濾掉空白或註記
            p = "".join(ch for ch in p if ch.isalnum())
            if p:
                out.append(p)
        return out

    symbols: List[str] = []
    seen = set()
    for row in rows:
        # 每列資料格式預期為 [上市日期, 證券代號, 證券簡稱, 發行人, 標的指數]
        if not (isinstance(row, list) and len(row) >= 2):
            continue
        code_field = row[1]
        codes = normalize_codes(code_field)
        for code in codes:
            # 去重後加入 symbols
            if code and code not in seen:
                seen.add(code)
                symbols.append(code)

    return symbols

def fetch_twse_etf_detail(code: str) -> Dict[str, Any]:
    """
    造訪商品內容端點，回傳單一 ETF 的 JSON 詳細資訊字典。
    端點：/rwd/zh/ETF/productContent?id={code}&response=json&_={ts}
    """
    # 建構帶時間戳的 URL，繞開快取
    base_tmpl = get_env("TWSE_PRODUCT_URL_TMPL", DEFAULT_PRODUCT_URL_TMPL)
    ts = int(time.time() * 1000)
    url = f"{base_tmpl.format(code=code)}&_={ts}"

    timeout = _get_timeout()
    retries = _get_retries()
    backoff = _get_retry_backoff()

    # 發請求與狀態檢查
    data = _request_json(url, timeout, retries, backoff)
    stat = str(data.get("stat") or "").upper()
    if stat != "OK":
        # 若 TWSE 回 stat 非 OK，視為該代碼暫不可用或被風控
        raise RuntimeError(f"商品內容 stat 非 OK: {stat}; code={code}")
    return data
