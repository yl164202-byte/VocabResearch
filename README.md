# VocabResearch Supabase 測試後端

學生端透過 Supabase Data API 呼叫 `vocab_request`。保留匿名學生代碼與 PIN，PIN 以 bcrypt 保存，學生無法直接查詢資料表或答案鍵。PostgreSQL 使用臺灣日期，並以學生與課程 ID 共用每日練習資格。事件批次在一個交易內寫入，只有同次填空提交驗證全對才會鎖定當日練習。

## 測試環境設定

1. 在獨立測試專案以已登入的 Supabase CLI 按順序套用 `supabase/migrations/` 的遷移。既有專案先核對遠端歷史，已套用的基準版本無須重跑。新版私有答案判分使用 `202611250002_private_cloze.sql`。
2. 複製 `student/backend.example.json` 到 `student/backend.json`，填入測試 Project URL 和 `sb_publishable_…`。該檔已列入 Git 忽略清單。請將資料庫密碼與 Secret Key 保存在私人環境。
3. 在 SQL Editor 用一次性的匿名學生與測試 PIN 呼叫 `select vocab_private.register_student('TEST001', '<測試 PIN>');`。以教師端匯出的私人課程 JSON 呼叫 `select vocab_private.register_course($course$<私人課程 JSON>$course$::jsonb);`。課程 ID、版本與生詞 ID 須對應學生教材。替換佔位內容後，只在私人測試專案輸入。
4. 從本分支啟動本機靜態網站，例如在 `git-dev` 執行 `python -m http.server 8000 --bind 127.0.0.1`，再以支援 Web Locks 的瀏覽器開啟 `http://localhost:8000/student/`。以相同帳號測雙分頁及換版本，以另一帳號確認練習與事件相互隔離。
5. 用 SQL Editor 查閱 `vocab_private.research_events`、`vocab_private.research_sessions` 與 `vocab_private.daily`，核對後端判分、去重及完成時間。學生帳號只有 RPC 存取權。

## 本機自動測試

在 `git-dev` 執行 `npm install` 後執行 `npm test`。測試使用 PGlite 的 PostgreSQL 與 pgcrypto，並以測試版 fetch 將學生端請求送至同一遷移建立的資料庫。

## 切換前待辦

GAS 的 Google Sheets 資料及舊版瀏覽器佇列保留原處。若正式收案需要接續既有資料，先確認歷史匯入與臺灣日期切換方案，包括舊 PIN 的重新登錄。本分支的教師 GUI 支援私人答案登錄與教材發布。原始資料夾仍保留舊版教師端，請從本分支啟動新版。正式部署應由整合測試通過後另行安排。

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

## 教師端 GUI

從本開發分支啟動 `GUI_batch.bat`，或在此目錄執行 `python -m streamlit run app.py`。
預設只監聽本機。以 `pip install -r requirements.txt` 安裝教師端相依套件。
若分支副本與原有教材同一層，GUI 會讀取上一層的 `data/` 與 `drafts/`。
獨立安裝可用 `VOCAB_LOCAL_DATA_DIR` 指向包含這兩個目錄的私人資料位置。

在側欄儲存 Project URL、publishable key 與 GitHub 開發分支。可用 `SUPABASE_CLI`
或側欄的 CLI 路徑指定已登入的 CLI v3 執行檔。教師權限繼承本機的 Supabase CLI
工作階段。GitHub 認證沿用本機加密儲存或 `GITHUB_TOKEN`。PIN 欄位送出後清空，
且在發出管理查詢前以 bcrypt 雜湊。請以本機教師工作站使用。

- 「匯出與 GitHub 發布」可單獨登錄私人課程，或依序登錄 Supabase 並提交
  GitHub 開發分支。公開教材、索引、共用網頁及只含 URL 與 publishable key
  的 `student/backend.json` 由同一筆 Git commit 發布。相同版本與內容可重試，
  修改已登錄教材須提高版本號。GUI 會顯示已確認的階段。
- 已發布版本的顯示與隱藏只更新該開發分支的索引。
- 「學生與研究紀錄」可建立匿名學生與 PIN，並按課程查閱最近 200 筆每日
  工作階段、完成時間、事件數和錯誤作答數。
- 新教材的備選答案只放在 Supabase。離線填空會保留表單文字，重連後可以
  再送判分。已產生的研究事件仍可離線暫存及重送。公開練習教材包含生詞本身。

目前 GUI 發布範圍是既有 `codex/` 開發分支。公開 Pages 切換與正式教材／學生
登錄需另行核准。舊課程檔、原始教材及歷史草稿保留原樣。

## 教師試用前自動化驗收

在安裝 Python 與 Node 相依套件的開發工作目錄執行下列指令：

| 指令 | 驗證範圍 |
| --- | --- |
| `./tests/run-acceptance.ps1 -Mode Local` | 教師 AppTest 與本機 PostgreSQL，不需外部服務或瀏覽器 |
| `./tests/run-acceptance.ps1 -Mode Browser` | 自動產生合成預覽並以 Chrome 操作三階段 |
| `./tests/run-acceptance.ps1 -Mode Cloud -Cli <CLI 路徑>` | 已授權的 GitHub／Supabase 合成資料整合，含 Chrome 學生端 |
| `./tests/run-acceptance.ps1 -Mode All -Cli <CLI 路徑>` | 全部驗收 |

無參數時執行本機與 Chrome 預覽，`-Cloud` 相容於原本的全套驗收。
教師 AppTest 使用合成冊課與臨時草稿，以 Streamlit WidgetState 提交表格欄位。
雲端模式建立隔離的 `codex/vocab-accept-it-*` 分支與合成資料，Chrome 使用該分支
實際提交的教材，並唯讀核對教師畫面與雲端事件。測試會保留合成分支與資料供追查。

配對與填空依教師選入的詞彙、完整的詞義語言、題句與審核的備選答案運作。
階段次序和全對門檻依既有研究規則固定。

### 填空備選答案

在「詞義／填空題編輯」可直接編輯整課表格中的「其他可接受答案（選填）」，
也可展開逐題編輯區核對題句、預設目標生詞及目前的答案。每行輸入一個
答案或以頓號分隔，可手動填入當課或先前學過的詞。逐題修改後先按
「套用本題其他答案」，再儲存整課草稿或發布。留空時仍接受原目標生詞。

備選答案只會傳到 Supabase 私人教材。填空研究事件保留原始 `selected`，
`correct_server` 由 Supabase 驗證，`extra_json.isTargetWord` 記錄學生端
將原始輸入正規化後是否等於該題目標生詞，可區分目標生詞正答和備選正答。
歷史事件仍保留原樣。
