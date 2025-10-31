# 路徑：src/common/env_loader.py
# 用途：讀取 .env 內所有參數；提供 get_env/require_env 等工具。
# 約定：.env 放在專案根目錄（例如：TWA-ETF-Engine/.env）
#
# 設計說明：
# - 主要目的是讓程式在任何執行位置（例如從 src/jobs、tests、notebooks 或 systemd、Docker）都能穩定找到專案根目錄的 .env。
# - 透過 _resolve_project_root() 由檔案位置往上回推到專案根目錄，避免依賴「目前工作目錄」。
# - 仍保留相對/工作目錄的搜尋作為備援，方便臨時測試或單檔執行。
# - 若安裝了 python-dotenv，優先用 dotenv_values + load_dotenv（可與其他套件共用）；否則採用簡易 parser。
# - override=False（預設）以尊重既有系統環境變數，適合 CI/生產；本機若想覆蓋可傳 override=True。

import os
from typing import Any, Dict, Optional

try:
    # python-dotenv 是常見的 .env 讀取套件
    # - dotenv_values(path) 會回傳字典，不直接動 os.environ，方便我們自行決定覆蓋策略
    # - load_dotenv 會將變數載入 os.environ，且可讓其他依賴 dotenv 的套件/子行程感知
    from dotenv import load_dotenv, dotenv_values
    DOTENV_AVAILABLE = True
except ImportError:
    # 若專案未安裝 python-dotenv，程式仍可工作，只是使用簡易的 .env 解析
    DOTENV_AVAILABLE = False

def _resolve_project_root() -> str:
    """
    推導專案根目錄的路徑。
    依據目前檔案 __file__ 的相對位置來回推：
    - 本檔位於：.../TWA-ETF-Engine/src/common/env_loader.py
    - 先取得本檔絕對路徑 -> 往上兩層取得 src 目錄 -> 再往上一層取得 TWA-ETF-Engine 根目錄。

    優點：
    - 不依賴「目前工作目錄」（os.getcwd），因此從不同目錄啟動程式也能穩定找到 .env。
    - 避免因 IDE/測試框架/系統服務不同啟動位置造成找不到 .env。

    回傳：
    - 字串，指向專案根目錄的絕對路徑。
    """
    here = os.path.abspath(__file__)                 # 當前檔案的絕對路徑
    src_dir = os.path.dirname(os.path.dirname(here)) # 往上兩層：.../src
    project_root = os.path.dirname(src_dir)          # 再往上一層：.../TWA-ETF-Engine
    return project_root

# 在 import 時即計算出專案根目錄，提供後續使用
PROJECT_ROOT = _resolve_project_root()

# 預設的 .env 搜尋清單（由高到低優先序）
# 1) 專案根目錄的 .env（最穩定、最明確）
# 2) 執行者所在路徑的 .env（相對路徑 ".env" 與 os.getcwd() 基本等價，兩者保留作為備援）
DEFAULT_ENV_PATHS = [
    os.path.join(PROJECT_ROOT, ".env"),  # 專案根目錄 .env（明確）
    ".env",                              # 相對當前工作目錄（備援，快速測試友善）
    os.path.join(os.getcwd(), ".env"),   # 目前工作目錄（備援，與上一行功能相近）
]

def load_env(env_path: Optional[str] = None, override: bool = False) -> Dict[str, str]:
    """
    載入 .env 中的變數進入 os.environ，並回傳「實際載入（新增或覆蓋）」的鍵值字典。

    參數：
    - env_path:
        指定 .env 的完整路徑。若為 None，則會依序嘗試 DEFAULT_ENV_PATHS。
        建議在特殊部署（例如非標準目錄結構、打包）才傳入此參數。
    - override:
        True  -> 若 os.environ 已有同名變數，仍以 .env 的值覆蓋（適合本機強制覆蓋測試）
        False -> 若 os.environ 已有同名變數，保留既有值（適合 CI/生產，尊重外部設定）

    回傳：
    - Dict[str, str]：這次「實際」寫入 os.environ 的鍵值（無論是新增或覆蓋）。

    行為說明：
    - 先以本模組的 PROJECT_ROOT 尋址專案根目錄的 .env，確保在不同工作目錄下也能找到。
    - 有安裝 python-dotenv 時：
        - 先用 dotenv_values 讀出字典，依 override 策略手動寫入 os.environ，同時蒐集 loaded。
        - 再呼叫 load_dotenv 以便子行程與其他套件感知（注意 load_dotenv 的 override 參數也會影響行為）。
    - 未安裝 python-dotenv 時：
        - 使用簡易解析器：忽略空行、註解（# 開頭）、以及無 '=' 的行；支援去除簡單引號/雙引號。
    - 若無法找到 .env（path 最終為 None 或檔案不存在），回傳空字典，不拋例外，方便上層自行決策。
    """
    loaded: Dict[str, str] = {}
    path = env_path

    # 自動探測 .env（優先用專案根目錄）
    if path is None:
        for p in DEFAULT_ENV_PATHS:
            if os.path.isfile(p):
                path = p
                break

    # 找不到 .env：不視為錯誤，回傳空字典（呼叫端可據此顯示「未載入」訊息）
    if not path or not os.path.isfile(path):
        return loaded

    if DOTENV_AVAILABLE:
        # 使用 dotenv_values 先取出鍵值，不直接修改環境，方便我們細緻控制覆蓋邏輯
        values = dotenv_values(path)
        for k, v in values.items():
            if v is None:
                # python-dotenv 可能會對某些格式回傳 None，此處跳過
                continue
            if override or (k not in os.environ):
                # 依策略將值寫入環境變數
                os.environ[k] = v
                loaded[k] = v
        # 再呼叫 load_dotenv：
        # - 讓依賴 dotenv 的其他程式碼/子行程也能看到這些變數
        # - 注意：此步驟仍會依 override 參數影響既有值是否被覆蓋
        load_dotenv(dotenv_path=path, override=override)
    else:
        # 未安裝 python-dotenv 時，使用簡單解析（僅支援最常見的 key=value）
        # 注意：不處理複雜情形（例如多行值、引用其他變數、export 前綴）
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                # 跳過空行與註解
                if not line or line.startswith("#") or "=" not in line:
                    continue
                # 只分割第一個 '='，避免 value 中的 '=' 被誤切
                k, v = line.split("=", 1)
                k = k.strip()
                # 去除首尾引號；不處理跳脫字元等進階情況
                v = v.strip().strip('"').strip("'")
                if override or (k not in os.environ):
                    os.environ[k] = v
                    loaded[k] = v

    return loaded

def get_env(key: str, default: Optional[str] = None, required: bool = False) -> str:
    """
    讀取單一環境變數。

    參數：
    - key: 變數名稱
    - default: 若環境無該變數，回傳此預設值（預設為 None）
    - required: 若為 True 且最終取不到值，會拋出 KeyError

    回傳：
    - str：最終取得的值（包含 default）；為了方便一般使用，型別固定為字串。
           若需數值或布林，請在呼叫端自行轉換並處理例外。

    範例：
    - get_env("DB_HOST", "localhost")
    - get_env("GOOGLE_CREDENTIAL", required=True)
    """
    val = os.getenv(key, default)
    if required and val is None:
        # 明確告知缺少必要變數，有助於在啟動初期快速發現配置問題
        raise KeyError(f"缺少必要環境變數: {key}")
    return val  # type: ignore

def require_env(keys: list[str]) -> Dict[str, str]:
    """
    一次性檢查多個必要環境變數，若缺少任何一個即拋出 KeyError。

    參數：
    - keys: 需要被保證存在的環境變數名稱列表

    回傳：
    - Dict[str, str]：包含所有指定 keys 對應之值的字典（若有缺失，此函式不會回傳而是拋錯）

    用途：
    - 在程式啟動階段快速 fail-fast，例如資料庫連線、API 金鑰等必要設定。
    """
    missing = [k for k in keys if os.getenv(k) is None]
    if missing:
        raise KeyError(f"缺少必要環境變數: {', '.join(missing)}")
    # 直接從 os.environ 取值，確保均為字串
    return {k: os.environ[k] for k in keys}
