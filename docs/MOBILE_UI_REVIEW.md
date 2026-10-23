# 手機版 UI 調整與驗證

範圍為 NSYSU_apple_design；原 NSYSU 網站不變。未更動 API、驗證規則、Supabase 結構、資料查詢、HRV 或睡眠計算。開始工作時已有的 sleep_parameters_view.py 未提交修改另行保留。

## 前端架構

- 首頁、日誌、歷史與管理頁：原生 HTML/CSS/JavaScript，app.css 為共用基底，apple.css 為現有 Apple 視覺與動畫配套。
- Dashboard：Streamlit 1.66.0 原生控制項與 Sidebar，Plotly 6.3.1 圖表；apple-dashboard.css 為外觀覆蓋層。Python 的 dashboard.py、chart_style.py 與 cloud.py 同時負責組裝 UI，此次只調整呈現參數與固定前端資產載入。
- 新增 responsive.css、responsive-dashboard.css 集中手機預設和斷點；mobile-ui.js 僅控制導覽開合，不攔截表單、連線或既有動作。繼續使用原色彩、字體、apple-motion.js 的 Spring 動畫與 reduced-motion 設定。

## 檢查發現與修正位置

依指定三項 Skills 及 [Web Interface Guidelines](https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md) 檢查；以下為已處理項目。

- frontend/web/responsive.css:2 — 補文字縮放、可縮放 viewport 配套、Safe Area 與表單焦點捲動空間。
- frontend/web/responsive.css:11 — 手機單欄 Grid；48rem 以上還原桌面雙／三欄與原有間距。
- frontend/web/mobile-ui.js:4 — 手機導覽 disclosure，提供 aria-expanded、Escape 關閉與焦點返回；桌面導覽保持展開。
- frontend/web/responsive.css:31 — 評分按鈕依容器寬度排列 3／5／6 欄，避免窄手機六個按鈕擠到 44px 以下。
- frontend/web/responsive-dashboard.css:3 — Dashboard 補 Safe Area；保留原生 Sidebar 自動收合與展開／收合控制。
- frontend/web/responsive-dashboard.css:25 — 依實際內容容器寬度調整卡片：小於 38rem 單欄，38–54rem 指標卡雙欄，更寬保留原桌面欄位比例。
- frontend/web/responsive-dashboard.css:34 — 小視窗或有觸控輸入能力時，原生圖示按鈕、下拉、分頁與說明控制至少 44×44 CSS px；桌面滑鼠控制保留原外觀。
- backend/nsysu/chart_style.py:111 — 圖表保留所有量測日期；窄畫面增加日期間距與字級，只在圖表內橫向捲動，1280px 以上維持原日期尺寸。
- frontend/web/responsive.css:38 — HTML 匯出表格限定區域捲動；Streamlit DataFrame 保留原生虛擬表格與水平捲動，不把整頁撐寬。
- frontend/web/app.css:3、frontend/web/apple.css:8 — hover 樣式限制在可 hover 的精準輸入裝置；保留 touch 的按壓回饋。

導覽、表格與圖表使用原生捲動；沒有 touchmove preventDefault、全面禁止文字選取或停用縮放。一般頁面保留手機原生捲動，僅 modal、Sidebar、下拉與水平捲動區域阻止不合適的捲動串接。

## 自動化驗證方式

在已安裝 requirements-dev.txt 的 Python 環境執行：

```sh
python -m playwright install chromium webkit
npm run build
npm run lint
npm test
npm run test:responsive
python -m pytest -q
python -m ruff check backend/nsysu streamlit_app.py
python -m mypy backend/nsysu --ignore-missing-imports --check-untyped-defs
```

響應式矩陣：320、375、390、430、768、1024、1440 CSS px × Chromium／WebKit。使用合成資料及本機預覽，不連接正式帳號或寫入正式資料。腳本會檢查首頁、導覽、登入 dialog、日誌時刻、評分控制、Dashboard、Sidebar、圖表日期標籤、九項睡眠卡片、表格與嵌入日誌。另驗證縮短視窗下焦點欄位不被操作列遮擋，以及 1440px 主容器幾何、色彩、字體與四欄卡片。

結果與截圖輸出至忽略版本控制的 test-results/responsive/；result.json 包含實際引擎版本、complete_matrix、desktop_geometry_unchanged 與各案例結果。單案重跑可加 --engine webkit --width 390；單案結果不代表完整矩陣通過。

2026-10-23 已在 Windows 完成 Chromium 140.0.7339.16／WebKit 26.0 的 14 組矩陣，complete_matrix=true、desktop_geometry_unchanged=true，沒有頁面 JavaScript 錯誤或未預期的外部請求。另以兩個引擎重驗 1440px 的桌面四欄與原生 14px 說明文字；單案報告另存 result-引擎-寬度.json，不覆寫完整矩陣結果。

建置、前端語法 Lint、108 項 Python 測試、22 項前端測試、Ruff 與 Mypy 通過；既有圖表點按提示、缺值中斷、圖例切換、縮放工具、Spring 按壓回饋與 reduced-motion 的瀏覽器檢查也通過。這些是自動化及引擎模擬結果，不包含實體手機驗證。

## 仍需真實手機驗證

- iPhone Safari：直／橫向瀏海與 Home Indicator 的非零 Safe Area、網址列伸縮、軟鍵盤開關、輸入時是否自動放大、雙指縮放及 VoiceOver。
- Android Chrome：軟鍵盤 resize、實際觸控延遲與按壓手感、內外捲動串接、返回手勢及 TalkBack。
- WebKit 自動測試不等於真實 iPhone Safari。嵌入日誌與 Dashboard 的最外層 viewport 由 Streamlit／Community Cloud 管理；沒有修改託管套件或跨框架注入父頁面。自有 HTML 已加入 viewport-fit=cover，UI 使用平台提供的 env() 安全邊距。
- 沒有連接實體手機，不能將上述硬體行為列為已驗證。
