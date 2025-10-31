# TWA-ETF-Engine

一個以台灣 ETF 為核心的資料處理與入庫引擎，具備：
- TWSE RWD 兩階段抓取（清單→商品內容）
- ETF 基本資料解析與 UPSERT 入庫
- 資料庫連線池與最小 DAO
- Google Sheets 健康檢查
- 專案樹自動輸出工具

本專案以「穩定載入 .env、在不同執行環境都能工作」為核心設計，並提供 tests 與 jobs 範例流程。

## 功能特色
- 分鐘級資料：1 分鐘 K 線聚合與清洗（OHLCV、turnover）
- 資料管理：ETF 基本資料、配息資料、交易成本
- 策略框架：均線、動能、均值回歸可擴充，回測與即時信號
- 交易執行：模擬撮合、手續費/稅費/滑點模型
- 投組管理：倉位、現金帳、風險與資金分配
- 報告同步：績效與持倉同步到 Google 試算表
- 歷史回補：逐筆/分時聚合成 1 分鐘 K，與盤中 UPSERT 整併

## 專案結構

- 最新樹請見 docs/PROJECT_TREE_YYYYMMDD_HHMMSS.md（使用 scripts/utils/tree.py 自動生成）
- 目前建置（2025-10-31）大致如下：
  - src/common/env_loader.py：載入 .env、get_env/require_env
  - src/datasource/twse.py：TWSE RWD 抓取
  - src/services/etf_loader.py：ETF 解析與入庫（UPSERT）
  - src/storage/db.py：MySQL 連線池與 DAO、healthcheck
  - src/storage/terminal.py：清除終端畫面
  - src/jobs/run_etf_scan.py：主流程（載入環境→健康檢查→抓取→解析→入庫）
  - tests/run_health_check.py：DB 與 Google Sheets 健檢
  - migrations/001_init.sql：資料表建立

完整樹請參閱你的工作日誌中附的生成結果或執行下方的樹工具。

## 快速開始
1) 安裝
- Python 3.13、MySQL 9.0
- 建立資料庫與執行 migrations/001_init.sql

2) 環境變數（.env）
DB_HOST=localhost
DB_USER=root
DB_PASS=your_pass
DB_NAME=market
GOOGLE_APPLICATION_CREDENTIALS=./secrets/sa.json
SPREADSHEET_ID=your_sheet_id

首次建置執行 migrations/001_init.sql
mysql -h <host> -P <port> -u <user> -p < db_name < migrations/001_init.sql

3) 套件
pip install -r requirements.txt

4) 啟動範例任務
- 歷史回補：python -m src.data_processing.minute_aggregator
- 盤中輪詢：python -m src.scheduler.cron_jobs

## 法遵與資料來源
- 僅用於研究與教育，資料使用請遵守 TWSE/TPEx 條款。

## 授權
MIT
