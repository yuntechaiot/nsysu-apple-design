# nsysu-eye-mask-sleep-monitor 獨立部署

此目錄是獨立 repository；只推送到 `yuntechaiot/nsysu-eye-mask-sleep-monitor`。不要設定原本的 `eye-mask-sleep-monitor` 為 remote，也不要修改原 Streamlit app。

在 Streamlit Community Cloud 建立 **新的 app**：

- Repository: `yuntechaiot/nsysu-eye-mask-sleep-monitor`
- Branch: `main`
- Main file: `streamlit_app.py`
- Python: `3.12`
- Subdomain: `nsysu-eye-mask-sleep-monitor`

Advanced settings 設定 `.streamlit/secrets.toml.example` 中的欄位。使用原研究資料來源與 publishable key，不使用 service_role。`PUBLIC_APP_URL` 設為 `https://nsysu-eye-mask-sleep-monitor.streamlit.app/`，新產生的 QR 才會指向新網站。DocterCloud 帳密仍由使用者於登入時輸入。

不得將原 `.env` 原封不動提交或複製為公開檔案。此專案不需要重新執行 migrations，不會更改資料庫結構。原網站與新網站有各自的程式部署，但沿用研究資料來源，實際資料管理會反映在共用資料中。

日誌、歷史、受試者管理與研究入口都在同一新網址；研究入口為 `/?view=dashboard`。發布後確認首頁、登入視窗與 Dashboard，私密帳號驗收由授權使用者完成。
