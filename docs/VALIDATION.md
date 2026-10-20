# Apple Design 驗證紀錄

2026-10-20，獨立 repository `yuntechaiot/nsysu-apple-design`，初始實作 commit `8ca6e57`。

- Python：77 passed（CI 合成公開連線設定）。
- JavaScript：22 passed；建置及語法檢查通過。
- Ruff、Mypy：通過。
- 本機 PGlite：原 migration、授權、邀請、QR、研究匯入與欄位保留測試通過，無正式資料寫入。
- Streamlit-only 瀏覽器回歸：首頁、四步驟送出、驗證、歷史編輯／刪除、受試者新增／改名／移除／還原、固定 QR、Dashboard 登入與返回導覽通過，外部資料庫寫入全部攔截。
- Apple UI：320／375／390／430／768／1365px 首頁無水平溢位；手機單欄時間、四步驟表單、評分、確認畫面、Spring 釋放回復與減少動態效果通過。
- GitHub CI：https://github.com/yuntechaiot/nsysu-apple-design/actions/runs/39396059582 ，completed / success。
- Cloud：獨立新 app `https://nsysu-apple-design.streamlit.app/`，Python 3.12；已在未登入的乾淨瀏覽器確認首頁與日誌登入視窗。未使用真實帳號送出研究資料。

本機截圖與 JSON 報告在 `test-results/apple` 與 `test-results/cloud`，均排除 Git。原 NSYSU 的所有追蹤檔未修改；新 repository 僅有自己的 remote。部署未執行 migrations；沿用相同研究資料來源及既有權限。
