# NSYSU 操作、設定與部署說明

> 外網部署與最新版單一 Streamlit 入口請見 [GitHub＋Streamlit 手冊](../GITHUB_STREAMLIT_SETUP.md)。以下保留舊本機 Flask＋Streamlit 雙服務與獨立 API 操作方式，Cloud 不執行這個雙服務模式。

更新：2026-10-19（Asia/Taipei）。現行網站仍為 HTML／Flask／Streamlit，沒有改資料表、研究公式或使用者流程。前次工作紀錄存於 history/RUNBOOK_20261018.md，其中時間、資料筆數與正式操作是歷史描述，不是本次執行結果。

## 本機啟動

在 NSYSU 目錄：

```powershell
$py = '.\.venv\Scripts\python.exe'
& $py .\run_nsysu.py
```

首頁為 http://127.0.0.1:8000/，Dashboard 為 http://127.0.0.1:8501/。若埠被占用，回到原啟動視窗按 Ctrl+C 後再用新入口啟動；不自動終止其他服務。根目錄只保留兩個專案資料夾，舊 run_vtca.py 相容入口已移除。

本專案 .venv 與 node_modules 已獨立重新建立；根目錄的舊環境已刪除。新環境可在 NSYSU 建立 Python 3.12 .venv，安裝 requirements-lock.txt；測試另裝 requirements-dev.txt。npm ci 使用 NSYSU 唯一的 package.json／package-lock.json。

## 設定與連線

本機 .env 保留既有 Supabase 連線設定。來源碼沒有硬編碼 Publishable Key，.env.example 是欄位與佔位值。不要以 example 覆寫現有 .env。啟動器／Dashboard／Store 只讀本專案 .env；既有程序環境變數優先。

保留 SUPABASE_URL、SUPABASE_PUBLISHABLE_KEY、SUPABASE_EXPECTED_REF、DOCTERCLOUD_BASE_URL 及所有原 VTCA_* 變數名稱。URL 必須與預期 Supabase 專案一致；不接受 service role 或 secret key。平台帳密與 Token 仍由各自登入流程取得，不寫入前端或新文件。

## 使用流程與資料

- 睡眠日誌：首頁選填寫、搜尋受試者、基本資料、24 小時睡眠時間、夜間狀況、確認後送出。既有上床、關燈、醒來、離床、手錶配戴、藥物、飲酒及問項完整保留。
- 歷史日誌：先登入 Supabase Auth，再按受試者授權讀寫；匿名仍只能填寫。QR/member_id 不當成身分憑證。
- 研究 Dashboard：保留手錶平台與睡眠研究兩種登入來源、日期／受試者查詢、資料管理、HRV 歷史、圖表、Min-Max／Z-score 與雙 Y 軸。缺值不改成零，顯示換算不改原數值。
- DocterCloud：原 platform adapter、會員 mapping 與同步資料存取保留。本次沒有登入正式平台、回填或新增資料。

## API 與 Supabase

HTTP 路由維持 GET /、/web/*、/health、/api/config、/api/participants，POST /api/participants、/api/import、/api/sync。Auth、RLS、RPC、所有現有四份 migrations 與 API payload 保留。正式表格、使用者、Policy、既有資料沒有本次變更。

共用 PRV 契約是離線檔案格式，不直接改 NSYSU canonical adapter。未來需核對受試者授權、絕對量測時間、來源及單位，才能提出正式匯入；不得用計算時間代替量測時間。

supabase/migrations 僅搬移；本次不執行 supabase db push、SQL migration、provision_access、backfill 或重新部署。tools 中正式資料工具保留，但應另行審閱與授權。Supabase 技能的 changelog 已查閱，此次未更新 SDK/API，沒有需要套用的 schema／Auth 變更。

## 開發驗證

```powershell
& $py -m pytest -q
& $py -m mypy backend/nsysu --ignore-missing-imports --check-untyped-defs
& $py -m ruff check backend/nsysu tests/web_platform run_nsysu.py
npm run build
npm run lint
npm test
npm run test:db
```

PGlite 測試使用本機 PostgreSQL 與 synthetic 列。瀏覽器測試 tools/browser_check.py 可用 NSYSU_TEST_BASE_URL／NSYSU_TEST_DASHBOARD_URL 指定專用測試伺服器，所有 Supabase 寫入在瀏覽器攔截；不要將合成資料送入正式系統。可用 `python tools/browser_regression.py` 自動以專用隨機連接埠啟動兩個服務做 Edge 瀏覽器回歸，結束時只停止測試啟動的服務。

## 部署與備份

部署工作目錄改為 NSYSU，Python 入口 run_nsysu.py。Flask 提供前端與 API 同站路由；Streamlit 仍為獨立服務。dist 僅為建置檢查產物，靜態部署本身不會提供 /api/config 或其他 API。部署時保持原環境變數與網域設定，實際部署需另行授權。

private、原研究 PDF／SQL、wifi.txt、原始生理 CSV 與 .env 不發布、不納 Git。完整原始碼搬移快照、原 hash 與路徑流水帳保留於 VTCA2026/docs/reorganization/private_audit，未覆寫既有 Excel、報告或研究數據。根目錄舊路徑 junction 已移除，專案使用自己的入口與資源。
