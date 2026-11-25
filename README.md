# VocabResearch Supabase 測試後端

學生端透過 Supabase Data API 呼叫 `vocab_request`。保留匿名學生代碼與 PIN，PIN 以 bcrypt 保存，學生無法直接查詢資料表或答案鍵。PostgreSQL 使用臺灣日期，並以學生與課程 ID 共用每日練習資格。事件批次在一個交易內寫入，只有同次填空提交驗證全對才會鎖定當日練習。

## 測試環境設定

1. 在 Supabase Dashboard 建立獨立測試專案。用該專案的 SQL Editor 執行 `supabase/migrations/202611250001_vocab.sql` 一次。此遷移會建立專用 schema 和一個公開 RPC；請先在測試專案使用。
2. 複製 `student/backend.example.json` 到 `student/backend.json`，填入測試 Project URL 和 `sb_publishable_…`。該檔已列入 Git 忽略清單。請將資料庫密碼與 Secret Key 保存在私人環境。
3. 在 SQL Editor 用一次性的匿名學生與測試 PIN 呼叫 `select vocab_private.register_student('TEST001', '<測試 PIN>');`。以教師端匯出的私人課程 JSON 呼叫 `select vocab_private.register_course($course$<私人課程 JSON>$course$::jsonb);`。課程 ID、版本與生詞 ID 須對應學生教材。替換佔位內容後，只在私人測試專案輸入。
4. 從本分支啟動本機靜態網站，例如在 `git-dev` 執行 `python -m http.server 8000 --bind 127.0.0.1`，再以支援 Web Locks 的瀏覽器開啟 `http://localhost:8000/student/`。以相同帳號測雙分頁及換版本，以另一帳號確認練習與事件相互隔離。
5. 用 SQL Editor 查閱 `vocab_private.research_events`、`vocab_private.research_sessions` 與 `vocab_private.daily`，核對後端判分、去重及完成時間。學生帳號只有 RPC 存取權。

## 本機自動測試

在 `git-dev` 執行 `npm install` 後執行 `npm test`。測試使用 PGlite 的 PostgreSQL 與 pgcrypto，並以測試版 fetch 將學生端請求送至同一遷移建立的資料庫。

## 切換前待辦

GAS 的 Google Sheets 資料及舊版瀏覽器佇列保留原處。若正式收案需要接續既有資料，先確認歷史匯入與臺灣日期切換方案，包括舊 PIN 的重新登錄。現有教師端可匯出相容的私人答案 JSON。教師端設定畫面和批次上架流程仍是原版，整合前避免用舊版 GUI 更新學生共用網頁。正式部署應由整合測試通過後另行安排。

## 實際 HTTP 與 Chrome 整合測試

`npm run test:cloud-browser` 使用已授權的測試專案、合成學生及兩個合成教材版本。
測試頁只監聽本機 loopback，教材與設定在記憶體供應。測試會模擬伺服器寫入後
回覆遺失，驗證待送事件會保留、重送沿用相同 event ID，以及完成後換分頁或
教材版本仍受同一日鎖定。

執行前在測試程序環境設定 `VOCAB_E2E_URL`、`VOCAB_E2E_KEY`（publishable key）、
`VOCAB_E2E_CODE`、`VOCAB_E2E_PIN`、`VOCAB_E2E_COURSE` 及本機 Chrome 路徑
`VOCAB_E2E_CHROME`。合成學生和教材 ID 使用 `IT_` 前綴。請勿將環境值寫入 Git。
測試使用後端既有的管理函式登錄合成資料，無須套用任何新 migration。

此分支供審查。學生正式上線前需另外確認公開站的 `backend.json` 供應方式，
並完成正式教材版本和學生代碼的授權登錄。
