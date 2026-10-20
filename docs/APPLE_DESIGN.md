# UI 分析與設計變更

## 原 UI 的觀察

- 主功能完整，但首頁、管理入口與說明文字的視覺權重接近。
- 手機仍有日期／時間雙欄與緊密的評分控制，長文字壓縮可操作空間。
- 按壓缺少即時回饋；畫面沒有依系統動態、透明度偏好提供替代呈現。
- 日誌與 Streamlit Dashboard 使用不同顏色與卡片語彙。

## 對應 Apple Fluid Interface

1. Purpose／Simplicity：優先顯示日誌與研究兩個任務；管理與歷史入口完整保留。
2. Typography：平台系統字體，大標題收緊字距，內文增加行距，間距用 rem。
3. Flexibility：手機單欄、足夠觸控範圍，保留原生日期選擇與 24 小時文字輸入。
4. Response：pointerdown 開始縮放；原生 click／表單仍直接執行，不加入等待時間。
5. Interruptibility：Spring 從當前 scale 與 velocity 重新設定目標，快速重複按壓不跳位。
6. Behavior：解析臨界阻尼 Spring，response 0.32 秒、damping ratio 1；沒有手勢動量時不加入彈跳。
7. Materials：頁首與表單操作區使用霧面層，內容卡片用實色維持可讀性。
8. Accessibility：保留焦點、語義標籤及鍵盤行為；減少動態時禁用 Spring；減少透明度／高對比使用實色。

## 功能邊界

日誌、歷史、管理、邀請、搜尋、驗證與 cloud transport 的原始 JavaScript 檔完全沿用；Python 的資料查詢、公式、匯入與平台整合不變。新增 CSS、獨立互動回饋檔、Dashboard 樣式載入與頁面文案。沒有新增第三方前端 CDN 或追蹤。沒有替換原網站的部署或 remote。
