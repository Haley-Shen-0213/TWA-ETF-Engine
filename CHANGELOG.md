# Changelog

## [0.1.0] - 2025-10-31
### 新增
- 專案初始化
  - 參考文件：docs/PROJECT_TREE_20251031_200554.md（完整專案檔案樹）
- 系統工具與共用功能
  - src/storage/terminal.py
    - 提供清除終端畫面功能，支援 Windows/macOS/Linux
  - src/common/env_loader.py
    - 載入並解析 .env 中所有參數，統一環境變數入口
- 健康檢查與測試
  - tests/run_health_check.py
    - 檢查資料庫連線可用性
    - 檢查 Google API 連線可用性
- 專案文件化工具
  - src/storage/tree.py
    - 產生專案結構樹文件，便於追蹤專案檔案現況
- 資料抓取與主流程
  - src/jobs/run_etf_scan.py
    - 主流程：載入環境 → 健康檢查 → 呼叫 TWSE → 解析單筆 → 寫入資料庫（UPSERT）
- 外部資料來源
  - src/datasource/twse.py
    - TWSE RWD ETF 兩階段抓取流程：
      1) 先取得 ETF 列表與代碼
      2) 逐一抓取商品內容細節
- 業務服務層
  - src/services/etf_loader.py
    - 解析 TWSE ETF 資料、推導屬性、執行 UPSERT 入庫
- 儲存層與資料庫
  - src/storage/db.py
    - 連線池管理與取得連線
    - 簡易 DAO 封裝
    - 健康檢查介面

### 變更
- 無

### 修正
- 無

### 相容性與備註
- 首版公開釋出，尚未包含 Migration 腳本（若有需要，請於後續版本加入）
- 請先建立與配置 .env 才能正常運作
- 依賴需求建議以 pipreqs 或 pip-compile 產出 requirements.txt 後安裝
