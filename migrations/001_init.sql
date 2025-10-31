-- 路徑：migrations/001_init.sql
-- 建議在部署前設定時區與編碼（視環境手動執行）
-- SET time_zone = '+08:00';
-- SET NAMES utf8mb4;

-- minute_bars：分鐘級行情K線資料，用於回測與即時策略計算
-- 欄位說明：
-- - symbol：ETF代碼
-- - ts_start：該分鐘K線的起始時間
-- - open/high/low/close：OHLC
-- - volume：成交量（股數或張數，依來源定義）
-- - turnover：成交金額
-- - source：資料來源標記（如 TWSE_OFFICIAL）
-- 索引：
-- - uq_symbol_ts：避免重複K線
-- - idx_symbol、idx_ts：常見查詢條件
CREATE TABLE IF NOT EXISTS minute_bars (
  id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '流水號主鍵',
  symbol VARCHAR(16) NOT NULL COMMENT 'ETF 代碼',
  ts_start DATETIME NOT NULL COMMENT '該分鐘K線起始時間',
  open DECIMAL(16,4) NOT NULL COMMENT '開盤價',
  high DECIMAL(16,4) NOT NULL COMMENT '最高價',
  low  DECIMAL(16,4) NOT NULL COMMENT '最低價',
  close DECIMAL(16,4) NOT NULL COMMENT '收盤價',
  volume BIGINT NOT NULL COMMENT '成交量（股數/張數，依來源）',
  turnover DECIMAL(20,4) NOT NULL COMMENT '成交金額',
  source VARCHAR(32) NOT NULL DEFAULT 'TWSE_OFFICIAL' COMMENT '資料來源標記',
  UNIQUE KEY uq_symbol_ts (symbol, ts_start) COMMENT '同商品同時間唯一K線',
  KEY idx_symbol (symbol) COMMENT '依商品查詢索引',
  KEY idx_ts (ts_start) COMMENT '依時間查詢索引'
) COMMENT='分鐘級行情K線資料，用於回測與即時策略計算';

-- etf_metadata：ETF 基本資料與交易屬性主檔
-- 用途：
-- - 供風控、撮合規則、交易計費與前端顯示使用
-- - 作為各模組引用的權威來源（單一真相來源，SSOT）
--
-- 欄位說明：
-- - symbol：ETF 代碼（唯一鍵），如 0050、00878
-- - short_name：顯示用短名（供前端與報表）
-- - category：ETF 類型，如「高股息」「市值型」「債券型」等
-- - listing_date：上市日期（YYYY-MM-DD）
-- - tick_unit：一般最小跳動單位（依當前或常見價位區間對應）
-- - tick_steps：分段最小跳動設定（JSON），依價格區間定義 tick；建議格式：
--     [
--       {"min":0, "max":10, "tick":0.01},
--       {"min":10, "max":50, "tick":0.05},
--       ...
--     ]
--   - 可為 NULL（代表僅用 tick_unit）
-- - trading_hours：交易時段設定（JSON），含常態與盤後；建議格式：
--     {
--       "regular": {"start":"09:00","end":"13:30"},
--       "after_hours": {"odd_lot":"13:40-14:30"}
--     }
-- - transaction_tax_rate：證券交易稅率（十進位表示），例如 0.001 代表 0.1%
-- - lot_size：基本交易單位（股數），如 1000；零股交易不受此限制
-- - is_active：是否活躍交易（1：仍在交易；0：下市/暫停等）
-- - exchange：交易所代碼，預設 TWSE（亦可擴充至 TPEx 等）
-- - updated_at：最後更新時間戳（自動維護；插入與更新時刷新）
--
-- 資料一致性：
-- - CHECK(JSON_VALID(...))：確保 JSON 欄位合法
-- - symbol 唯一鍵：UPSERT 時以 symbol 為識別
CREATE TABLE `etf_metadata` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '流水號主鍵',
  `symbol` varchar(16) NOT NULL COMMENT 'ETF 代碼（唯一）',
  `short_name` varchar(64) NOT NULL COMMENT '顯示用短名',
  `category` varchar(64) NOT NULL COMMENT 'ETF 類型（如高股息、加權、債券等）',
  `listing_date` date NOT NULL COMMENT '上市日期',
  `tick_unit` decimal(16,4) NOT NULL COMMENT '一般最小跳動單位',
  `tick_steps` json DEFAULT NULL COMMENT '分段 tick 設定（依價位分段）',
  `trading_hours` json NOT NULL COMMENT '交易時段設定（常態/盤後等）',
  `transaction_tax_rate` decimal(8,6) NOT NULL COMMENT '證交稅率（例如 0.001 表示 0.1%）',
  `lot_size` bigint DEFAULT NULL COMMENT '基本交易單位（股數），如 1000',
  `distribution_policy` varchar(64) DEFAULT NULL COMMENT '收益分配（季配、月配、無配等）',
  `exchange` varchar(16) NOT NULL DEFAULT 'TWSE' COMMENT '交易所（預設 TWSE）',
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最後更新時間',
  PRIMARY KEY (`id`),
  UNIQUE KEY `symbol` (`symbol`),
  CONSTRAINT `etf_metadata_chk_1` CHECK (((`tick_steps` is null) or json_valid(`tick_steps`))),
  CONSTRAINT `etf_metadata_chk_2` CHECK (json_valid(`trading_hours`))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='ETF 基本資料與交易屬性，用於風控、交易規則與顯示';

-- etf_dividends：ETF官方配息事件資料（產品層級），供策略與報表參考
-- 欄位說明：
-- - distribution_mode：配息方式（如現金、股利）
-- - ex_dividend_date：除息日
-- - record_date：停資過戶日
-- - payment_date：發放日
-- - dividend_amount：單位配息金額
-- - source：資料來源標記
-- - created_at：記錄建立時間
-- 索引：
-- - idx_symbol：依標的查詢
-- - idx_ex_date：依除息日查詢
CREATE TABLE IF NOT EXISTS etf_dividends (
  id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '流水號主鍵',
  symbol VARCHAR(16) NOT NULL COMMENT 'ETF 代碼',
  distribution_mode VARCHAR(32) NOT NULL COMMENT '配息方式（現金/股利等）',
  ex_dividend_date DATE NOT NULL COMMENT '除息日',
  record_date DATE NOT NULL COMMENT '停資過戶日',
  payment_date DATE NOT NULL COMMENT '發放日',
  dividend_amount DECIMAL(16,4) NOT NULL COMMENT '單位配息金額',
  source VARCHAR(32) NOT NULL DEFAULT 'TWSE_OFFICIAL' COMMENT '資料來源標記',
  created_at DATETIME NOT NULL COMMENT '記錄建立時間',
  KEY idx_symbol (symbol) COMMENT '依商品查詢索引',
  KEY idx_ex_date (ex_dividend_date) COMMENT '依除息日查詢索引'
) COMMENT='ETF 官方配息事件資料（產品層級），供策略與報表參考';

-- accounts：交易帳戶主檔，管理資金與配置
-- 欄位說明：
-- - name：帳戶名稱（唯一）
-- - base_currency：基準幣別（預設 TWD）
-- - cash_balance：當前現金餘額
-- - max_usable_ratio：下單最大可用比例（風控）
-- - allocation：資產配置（JSON）
-- - created_at/updated_at：建立與更新時間
CREATE TABLE IF NOT EXISTS accounts (
  id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '流水號主鍵',
  name VARCHAR(64) NOT NULL UNIQUE COMMENT '帳戶名稱（唯一）',
  base_currency VARCHAR(8) NOT NULL DEFAULT 'TWD' COMMENT '基準幣別',
  cash_balance DECIMAL(20,4) NOT NULL COMMENT '當前現金餘額',
  max_usable_ratio DECIMAL(8,6) NOT NULL COMMENT '下單最大可用比例（風控）',
  allocation JSON NULL COMMENT '資產配置（JSON）',
  created_at DATETIME NOT NULL COMMENT '建立時間',
  updated_at DATETIME NOT NULL COMMENT '更新時間'
) COMMENT='交易帳戶主檔，管理資金與配置';

-- fees_config：手續費/稅率設定（隨時間生效），供交易計費
-- 欄位說明：
-- - account_id：對應帳戶
-- - commission_rate：手續費比率
-- - min_commission：最低手續費
-- - tax_rate：交易稅率
-- - effective_date：生效日期
-- 關聯：
-- - account_id -> accounts(id)
CREATE TABLE IF NOT EXISTS fees_config (
  id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '流水號主鍵',
  account_id BIGINT NOT NULL COMMENT '對應帳戶 ID',
  commission_rate DECIMAL(8,6) NOT NULL COMMENT '手續費比率',
  min_commission DECIMAL(16,4) NOT NULL COMMENT '最低手續費',
  tax_rate DECIMAL(8,6) NOT NULL COMMENT '交易稅率',
  effective_date DATE NOT NULL COMMENT '生效日期',
  FOREIGN KEY (account_id) REFERENCES accounts(id)
) COMMENT='手續費與稅率設定（可隨時間變化），供交易計費';

-- orders：委託單資料，用於下單與狀態追蹤
-- 欄位說明：
-- - account_id：對應帳戶
-- - symbol：ETF代碼
-- - side：買賣別
-- - order_type：市價/限價
-- - price：限價單價格（市價為 NULL）
-- - quantity：委託數量
-- - status：委託狀態（NEW/PARTIAL/FILLED/CANCELLED/REJECTED）
-- - created_at/updated_at：建立與更新時間
-- 關聯：
-- - account_id -> accounts(id)
-- 索引：
-- - idx_account_symbol：常用查詢鍵
CREATE TABLE IF NOT EXISTS orders (
  id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '流水號主鍵',
  account_id BIGINT NOT NULL COMMENT '對應帳戶 ID',
  symbol VARCHAR(16) NOT NULL COMMENT 'ETF 代碼',
  side ENUM('BUY','SELL') NOT NULL COMMENT '買賣別',
  order_type ENUM('MARKET','LIMIT') NOT NULL COMMENT '市價或限價',
  price DECIMAL(16,4) NULL COMMENT '限價單價格（市價為 NULL）',
  quantity BIGINT NOT NULL COMMENT '委託數量',
  status ENUM('NEW','PARTIAL','FILLED','CANCELLED','REJECTED') NOT NULL COMMENT '委託狀態',
  created_at DATETIME NOT NULL COMMENT '建立時間',
  updated_at DATETIME NOT NULL COMMENT '更新時間',
  FOREIGN KEY (account_id) REFERENCES accounts(id),
  KEY idx_account_symbol (account_id, symbol) COMMENT '依帳戶+商品查詢索引'
) COMMENT='委託單資料，用於下單與狀態追蹤';

-- trades：成交回報，用於計算實際成本、手續費與稅
-- 欄位說明：
-- - order_id：對應委託單
-- - trade_time：成交時間
-- - trade_price/trade_quantity：成交價格與數量
-- - amount：成交金額（price * quantity）
-- - commission/tax：手續費與稅
-- 關聯：
-- - order_id -> orders(id)
-- 索引：
-- - idx_order：依委託查成交
-- - idx_trade_time：依時間查成交
CREATE TABLE IF NOT EXISTS trades (
  id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '流水號主鍵',
  order_id BIGINT NOT NULL COMMENT '對應委託單 ID',
  trade_time DATETIME NOT NULL COMMENT '成交時間',
  trade_price DECIMAL(16,4) NOT NULL COMMENT '成交價格',
  trade_quantity BIGINT NOT NULL COMMENT '成交數量',
  amount DECIMAL(20,4) NOT NULL COMMENT '成交金額（price*quantity）',
  commission DECIMAL(16,4) NOT NULL COMMENT '手續費',
  tax DECIMAL(16,4) NOT NULL COMMENT '交易稅',
  FOREIGN KEY (order_id) REFERENCES orders(id),
  KEY idx_order (order_id) COMMENT '依委託查成交',
  KEY idx_trade_time (trade_time) COMMENT '依時間查成交'
) COMMENT='成交回報，用於計算實際成本、手續費與稅';

-- positions：持倉資料，用於庫存與損益計算
-- 欄位說明：
-- - account_id/symbol：帳戶與標的唯一鍵
-- - quantity：持有數量
-- - avg_cost：加權平均成本
-- - realized_pnl：已實現損益（平倉累計）
-- - updated_at：最後更新時間
-- 關聯：
-- - account_id -> accounts(id)
-- 索引：
-- - uq_account_symbol：同帳戶同商品唯一
CREATE TABLE IF NOT EXISTS positions (
  id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '流水號主鍵',
  account_id BIGINT NOT NULL COMMENT '帳戶 ID',
  symbol VARCHAR(16) NOT NULL COMMENT 'ETF 代碼',
  quantity BIGINT NOT NULL COMMENT '持有數量',
  avg_cost DECIMAL(16,4) NOT NULL COMMENT '加權平均成本',
  realized_pnl DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '已實現損益（平倉累計）',
  updated_at DATETIME NOT NULL COMMENT '最後更新時間',
  UNIQUE KEY uq_account_symbol (account_id, symbol) COMMENT '同帳戶同商品唯一',
  FOREIGN KEY (account_id) REFERENCES accounts(id)
) COMMENT='持倉資料，用於庫存與損益計算';

-- cash_ledger：現金流水帳，紀錄資金變動來源與結果
-- 欄位說明：
-- - account_id：對應帳戶
-- - ts：事件時間
-- - type：資金事件類型（存入、提出、交易、股息、費用、稅）
-- - amount：本次金額變動
-- - balance_after：事件後現金餘額
-- - note：備註
-- 關聯：
-- - account_id -> accounts(id)
-- 索引：
-- - idx_account_ts：依帳戶+時間查詢
CREATE TABLE IF NOT EXISTS cash_ledger (
  id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '流水號主鍵',
  account_id BIGINT NOT NULL COMMENT '帳戶 ID',
  ts DATETIME NOT NULL COMMENT '事件時間',
  type ENUM('DEPOSIT','WITHDRAW','TRADE','DIVIDEND','FEE','TAX') NOT NULL COMMENT '資金事件類型',
  amount DECIMAL(20,4) NOT NULL COMMENT '本次金額變動',
  balance_after DECIMAL(20,4) NOT NULL COMMENT '事件後現金餘額',
  note VARCHAR(256) NULL COMMENT '備註',
  FOREIGN KEY (account_id) REFERENCES accounts(id),
  KEY idx_account_ts (account_id, ts) COMMENT '依帳戶+時間查詢索引'
) COMMENT='現金流水帳，紀錄資金變動來源與結果';

-- dividends_events：帳戶層級的配息入帳事件（與產品官方事件不同）
-- 欄位說明：
-- - account_id/symbol：入帳帳戶與商品
-- - ex_dividend_date/payment_date：除息與入帳日
-- - amount_per_share/shares/total_amount：單位配息、持股數、總金額
-- - booked_at：帳務登帳時間
-- 關聯：
-- - account_id -> accounts(id)
-- 索引：
-- - idx_account_symbol：依帳戶+商品查詢
CREATE TABLE IF NOT EXISTS dividends_events (
  id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '流水號主鍵',
  account_id BIGINT NOT NULL COMMENT '帳戶 ID',
  symbol VARCHAR(16) NOT NULL COMMENT 'ETF 代碼',
  ex_dividend_date DATE NOT NULL COMMENT '除息日',
  payment_date DATE NOT NULL COMMENT '入帳日',
  amount_per_share DECIMAL(16,4) NOT NULL COMMENT '每股配息金額',
  shares BIGINT NOT NULL COMMENT '持有股數',
  total_amount DECIMAL(20,4) NOT NULL COMMENT '入帳總金額',
  booked_at DATETIME NOT NULL COMMENT '帳務登帳時間',
  FOREIGN KEY (account_id) REFERENCES accounts(id),
  KEY idx_account_symbol (account_id, symbol) COMMENT '依帳戶+商品查詢索引'
) COMMENT='帳戶層級的配息入帳事件（與產品官方事件不同）';

-- strategies：策略主檔，存放策略名與參數
-- 欄位說明：
-- - name：策略名稱（唯一）
-- - params：策略參數（JSON）
-- - enabled：是否啟用
-- - created_at/updated_at：建立與更新時間
CREATE TABLE IF NOT EXISTS strategies (
  id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '流水號主鍵',
  name VARCHAR(64) NOT NULL UNIQUE COMMENT '策略名稱（唯一）',
  params JSON NOT NULL COMMENT '策略參數（JSON）',
  enabled TINYINT NOT NULL DEFAULT 1 COMMENT '是否啟用',
  created_at DATETIME NOT NULL COMMENT '建立時間',
  updated_at DATETIME NOT NULL COMMENT '更新時間'
) COMMENT='策略主檔，存放策略名與參數';

-- strategy_signals：策略輸出的交易訊號，用於下單或回測
-- 欄位說明：
-- - strategy_id：對應策略
-- - symbol：標的
-- - ts：訊號時間
-- - signal：買/賣/觀望
-- - confidence：信心分數（可選）
-- - note：備註（可選）
-- 關聯：
-- - strategy_id -> strategies(id)
-- 索引：
-- - idx_strategy_symbol_ts：依策略+商品+時間查詢
CREATE TABLE IF NOT EXISTS strategy_signals (
  id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '流水號主鍵',
  strategy_id BIGINT NOT NULL COMMENT '策略 ID',
  symbol VARCHAR(16) NOT NULL COMMENT 'ETF 代碼',
  ts DATETIME NOT NULL COMMENT '訊號時間',
  signal_type ENUM('BUY','SELL','HOLD') NOT NULL COMMENT '訊號類型',
  confidence DECIMAL(8,6) NULL COMMENT '信心分數（可選）',
  note VARCHAR(128) NULL COMMENT '備註（可選）',
  FOREIGN KEY (strategy_id) REFERENCES strategies(id),
  KEY idx_strategy_symbol_ts (strategy_id, symbol, ts) COMMENT '依策略+商品+時間查詢索引'
) COMMENT='策略輸出的交易訊號，用於下單或回測';

-- backtest_runs：回測執行紀錄與結果摘要
-- 欄位說明：
-- - strategy_id：使用的策略
-- - symbol_list：回測標的列表（JSON）
-- - start_ts/end_ts：回測時間範圍
-- - metrics：指標結果（JSON，如收益率、最大回撤等）
-- - created_at：建立時間
-- 關聯：
-- - strategy_id -> strategies(id)
CREATE TABLE IF NOT EXISTS backtest_runs (
  id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '流水號主鍵',
  strategy_id BIGINT NOT NULL COMMENT '策略 ID',
  symbol_list JSON NOT NULL COMMENT '回測標的列表（JSON）',
  start_ts DATETIME NOT NULL COMMENT '回測開始時間',
  end_ts DATETIME NOT NULL COMMENT '回測結束時間',
  metrics JSON NOT NULL COMMENT '回測指標結果（JSON）',
  created_at DATETIME NOT NULL COMMENT '建立時間',
  FOREIGN KEY (strategy_id) REFERENCES strategies(id)
) COMMENT='回測執行紀錄與結果摘要';
