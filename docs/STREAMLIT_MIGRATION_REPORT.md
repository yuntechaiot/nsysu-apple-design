# 最新 NSYSU 網頁的 GitHub＋Streamlit 改造

日期：2026-10-19（Asia/Taipei）。以下記錄本機改造階段的完成狀態；後續經使用者授權，以最新版取代 GitHub main 的舊檔並保留提交紀錄。正式資料庫沒有執行變更。

## 最終行為

正式入口為 repository 根目錄 `streamlit_app.py`。一個 Streamlit 服務提供最新日誌首頁、個人填寫、歷史編輯、受試者搜尋／QR／管理與研究 Dashboard。表單內的研究入口另開同一服務的 `?view=dashboard` 分頁，手機連結使用公開網址，不再依賴電腦本機 8000 埠。

最新 HTML／JavaScript 的四步驟流程、欄位、24 小時輸入、台灣日期、確認頁、歷史授權與缺值邏輯保留；Dashboard 的來源登入、查詢、圖表、指標、原子匯入與同步保留。只替換部署連接方式，沒有採用舊 software 的欄位、公式或 service_role 讀取機制。

## 修改內容

- `backend/nsysu/cloud.py`：嵌入固定最新前端資源、白名單公開設定、安全處理個人連結與單一 app 導覽。
- `frontend/web/cloud-transport.js`：只替代 `/api/config` 與 `/api/participants`；使用個人 Auth JWT、公開邀請 view、既有受試者 RPC／RLS，不傳送管理金鑰、不新增資料表。
- `backend/nsysu/config.py`、Store／Platform：支援 Cloud Secrets，維持本機環境與正確 Supabase 專案檢查；私密 key 不進入 HTML。
- `dashboard_flow.py`：Cloud 的日誌／歷史返回連結使用同一個公開 app 網址；保留原分析與研究邏輯。
- `.streamlit/secrets.toml.example`、部署手冊、GitHub CI：以 NSYSU 作 repository 根目錄，Python 3.12、Streamlit 1.50.0；舊本機雙服務入口與 API 仍供相容使用。

## Git 與舊 software

原 software 有 Git repository、4 份已修改的 tracked 檔案及多份未追蹤程式／SQL。先保存 status、binary diff、完整 Git bundle，再保存工作區與經 SHA-256 核對的 25 份非環境原始檔／私人文件。舊 .venv 是可重建環境，不是部署依賴。

將該 repository 的 `.git` 提升到 NSYSU 根目錄，HEAD 維持 `a7a03358b552674929d13c3060c7c07b14beca42`，原 `publish-readme` 分支、origin 與歷史保留。遠端 main 的唯讀查詢亦為同一 commit；未 commit、stage、push、reset、force push 或改寫歷史。NSYSU 現在是既有 GitHub repository 的工作目錄，VTCA2026 沒有併入。

舊 source、Secrets、帳號文件、SQL 與研究 PDF 保存在受忽略的 `private/backups/streamlit_migration/`，沒有放到公開部署內容。實際刪除 software 的操作被自動核准審查回覆 `blocked by policy` 拒絕，未提供更詳細原因；因此保留原資料夾，並由 `.gitignore` 排除。程式與 CI 都不再引用它。

## 驗證結果

| 檢查 | 結果 |
|---|---|
| 原 NSYSU Python 37 項 | 通過 |
| 新增 Cloud Python 7 項 | 通過；總計 44 passed |
| JavaScript | 原 9 項＋新增 transport 6 項，共 15 passed |
| 前端 build／lint | 通過，9 個前端資源 |
| PGlite PostgreSQL／RLS／RPC | 23 項通過；僅本機合成資料 |
| 單一 Streamlit Edge 瀏覽器 | 14 項流程通過；沒有 `/api/*` 或 `/web/*` 本機路由請求，無 page errors |
| 瀏覽器寫入 | 全部 Supabase 流量攔截；假資料只存在記憶體 |
| mypy／ruff／pip check | 通過 |
| Git history bundle／舊 source archive | 完整歷史驗證、25 份原始文件逐檔 SHA-256 通過 |
| 真正的 Cloud Linux 啟動／GitHub Actions | NOT_TESTED：尚未推送或部署；已加入 CI，不能將本機檢查當作遠端執行成功 |
| 正式 Auth／資料／舊 QR | NOT_TESTED：需發布後用實際帳號驗收，本次未讀寫正式資料庫 |

Cloud 瀏覽器測試實際驗證首頁／手機寬度、下拉搜尋、QR、四步驟與確認不寫入、24 小時與跨午夜台灣時間、三態問項、歷史登入／編輯、HTML 跳脫、管理員 RPC、新受試者深連結與 Dashboard／返回網址。

初次瀏覽器測試發現 iframe 無法直接導覽最上層視窗，改以明確的另開分頁研究連結後通過；沒有靠停用 sandbox、CORS 或 XSRF 檢查解決。

## 發布前的必要動作

先核對最新 NSYSU 的 Cloud Secrets，再檢視／提交目前分支並經 GitHub 合併到 main。完整流程見 [部署手冊](../GITHUB_STREAMLIT_SETUP.md)。可直接貼入 Cloud 的最新連線設定已產生於受忽略的 `private/deployment/streamlit-secrets.toml`，沒有自動變更線上設定。

原本研究者的 Supabase 授權仍然需要；DocterCloud 登入不會自動獲得睡眠日誌管理權。發布後另驗證實際資料與原 QR，不能套用舊 SQL 或用 service_role 繞過現有 RLS。
