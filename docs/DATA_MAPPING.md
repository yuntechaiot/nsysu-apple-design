# 原始資料、指標與研究日期

版本：`vtca-sleep-2.0.0`／`vtca-import-2.0.0`，2026-10-18。

## 已確認來源

實際程式為 `frontend/source/睡眠日誌表單.html`、Streamlit `數據監控室.py`，不是 React/Next.js。相鄰 `../VTCA2026` 只有論文文件。修改以目前工作目錄中的可執行網站為準。

供應商文件為 `對外API文件(管理系統)V5-4.pdf`。原程式及管理資訊 PDF 證實 DocterCloud 網址、研究者登入及會員查詢；登入、會員及生理 API 已實際唯讀驗證。文件未出現可證實「有夠大」與 DocterCloud 為同一品牌的名稱對應，因此資料來源固定記作 `doctercloud`。若「有夠大」是另一個平台，需提供該平台文件／已授權匯出；不將未確認平台當作同步成功。

| DocterCloud 原始欄位 | 正規化 | 單位／限制 |
|---|---|---|
| 會員 `identifier`、`id` | `research_participants.member_id`、`platform_user_id` | 僅接受完整字串精確對應；已核對 50 位 |
| 睡眠 `id` | `external_session_id` | 缺 ID 時使用起訖與來源類型的 SHA-256；不使用可變睡眠數值當 ID |
| `start_time`、`emd_time`（相容 `end_time`） | `start_at`、`end_at` | 文件 UNIX 秒，明確拒絕疑似毫秒 |
| `detail_obj.type` | `sleep_stage_records.stage` | 0 awake、1 light、2 deep、3 rem、4 nap；未知保留 unclassified |
| detail `start_time`、`end_time` | `start_at`、`end_at`、`duration_minutes` | 秒差／60；開放、重疊、斷裂分期標待確認，不推估缺段 |
| `data.light`、`deep`、`REM`、`napDuration` | light/deep/rem/other_sleep_minutes | 文件明訂分鐘，保留供應商摘要；與完整時間軸不符時標記 |
| `data.awake` | `awake_minutes` | 文件只稱清醒總時間；不等同 WASO |
| 完整且連續分期 | TST、onset、final_wake、WASO、awakening_count | 只有完整時間軸可確認缺少的階段為 0；不完整時保持 NULL |
| HR `value`、`occur_time` | HR、measured_at | bpm；UNIX 秒→含時區時間 |
| HRV `fatigue` | metric=fatigue | 直接存來源值，不自行限為 0–100；允許有限的負值 |
| HRV `data.mental_stress` | metric=stress | 同上；不是抗壓能力欄位 |
| `sdnn`、`tp`、`vlf`、`lf`、`hf` | SDNN、TP、VLF、LF、HF | 原文件未標單位，unit=NULL；不套用其他演算法的單位 |
| 同筆 `lf`／非零 `hf` | LF/HF | 原程式已有 LF/HF 推算；版本 `vtca-lf-over-hf-1`、ratio、保留 raw |
| `type` | source_type／raw_payload.type | 來源類型不是唯一裝置 ID；不冒稱裝置識別或 ECG |
| BP `sys`／`dia`、SpO2／Temp `value` | SBP／DBP、SpO2、Temperature | 保留原圖表 mmHg、%、°C 標示，無額外數值換算 |

原始物件保存在 `raw_payload`，完整匯入批次保存在 `data_imports.raw_payload`；包含原始時間戳、來源與原始欄位。`units`、`metric_provenance`、`algorithm_version`、`quality_status`、`quality_issues`、`imported_at` 分開保存。唯一裝置 ID 不存在時保持 NULL；`type` 不能替代。

## 標準 JSON／CSV 匯入契約

這是本專案自行定義的匯入欄位，不聲稱供應商原生提供相同欄名。`adapter=canonical`，不同平台請設定不同且固定的 `source`，例如實際平台已核實的內部來源代碼。

睡眠：必填 `external_session_id,start_at,end_at`；時間採 ISO8601 並帶 `+08:00` 或 `Z`。可選 `tst_minutes,light_minutes,deep_minutes,rem_minutes,other_sleep_minutes,waso_minutes,awake_minutes,awakening_count,sleep_onset_at,final_wake_at,device_external_id,source_type,algorithm_version`。空欄為 NULL，數值 0 保留。JSON 可使用 `stages_complete:true` 並完整提供全部已確認睡眠階段才計算缺少的 TST。CSV 不對缺少的其他階段補零。外部 stage percentages 如在原始檔案中會保留 raw，顯示比例一律明示以 TST 計算，不混用不同分母。

生理：`kind=physiological`；必填 `external_record_id,metric,value,measured_at,signal_type,algorithm_version`；可選 `unit,device_external_id,scale_definition,quality_status`。signal_type 只能為 PPG、ECG、unknown。支援 HR、RMSSD、SDNN、TP、VLF、LF、HF、LF/HF、stress、fatigue 及原有其他生理指標。既有 B20 分析結果需帶入實際分析窗時間與 signal_type 後依此契約匯入；相對裝置 timestamp 不可直接當 UNIX 時間。

`../../VTCA2026/b20_hrv/analysis/hrv_analysis.py` 已確認：RMSSD、SDNN 為 ms，SDNN 採樣本標準差 ddof=1；HR bpm；頻域 ms²，TP 頻帶 0.0033–0.40 Hz；Welch Hann 128 秒、4 Hz tachogram、頻帶積分。保留既有演算法，不把這些單位套到 DocterCloud。PPG 路徑標示 PPG-derived PRV，ECG R-R 才標 ECG-derived HRV，未知維持未知。

## 睡眠公式

原 dashboard 已使用 TST/TIB 的 SE 定義，但也錯把整段睡眠起訖當作 TST、上床當作 SOL 起點並將 SE 封頂 100。本版修正後：

* TST 優先使用明確提供的原始值；否則完整分期中 Light+Deep+REM+已確認睡眠（nap），不含 Awake。DocterCloud 文件未列直接 TST，故摘要不完整時不自行推算。
* TIB = 實際離床－上床。使用日誌明確日期錨點。
* 客觀 SOL = 裝置首次確認入睡－日誌開始嘗試入睡。沒有關燈或客觀入睡時為 NULL；`sleep_onset_min` 始終獨立保留主觀 SOL。
* WASO = 首次入睡至最後醒來之間完整分期的 Awake 總和；相鄰 Awake 段合併計次。排除入睡前與最後醒來後清醒。
* SE = TST/TIB×100。分母零、缺值、TST>TIB 都不輸出有效 SE，不封頂掩飾衝突。
* Light/Deep/REM 比例 = 該階段分鐘/TST×100。不完整分期不重新配成 100%；Awake 不放進同一睡眠比例。
* 顯示分鐘轉為小時／分鐘，百分比兩位小數。原始值不改寫。

### DocterCloud 同步呈現（2026-10-20）

已對照現行官方 B20 睡眠頁：其 `pl(data)`／`Jn(record)` 以 `data.light + data.deep + data.REM` 呈現睡眠總時數，`data.awake` 獨立顯示清醒時間。本專案的 `sleep_display_summary` 僅在三個摘要值均已提供、為有效非負數、且總和未超過紀錄起訖時長時，採用相同的展示方式；缺欄不照官方介面的預設補零。零星睡眠另列。

展示層摘要不回寫 `sleep_sessions.tst_minutes`，也不把 `awake_minutes` 當成 `waso_minutes`。原研究指標仍依上列完整分期與日誌條件計算，置於進階研究區；首頁卡片與睡眠分析採同一個展示摘要。來源實際有各段 `end_time=null` 的紀錄；這些區段只顯示已提供的起點，未以本筆紀錄結束時間或下一筆起點猜測時長。

公式依使用者本次明確研究定義，以及原程式可確認的 SE 定義實作；不聲稱有新增臨床驗證。

## 日期與歷史相容

原表單明示：`sleep_time` 上床、`morning_wake_time` 最後醒來、`wake_time` 實際離床。舊 `date` 是填寫日期，未經確認不可當上床日。舊列保留 `date_definition=legacy_unconfirmed`，不自動與客觀 Session 配對。

新日誌 `date_definition=wake_date`，以最後醒來的台灣日曆日期為準，上床／關燈／離床各有日期。所有絕對時間存 timestamptz；前端用 `+08:00`，圖表統一轉台灣時間，不使用 `toISOString().split('T')[0]` 判斷當地日期。手錶 Session 取最後確認醒來日期；無完整分期時取來源 Session 結束日期並保留品質限制。

舊原生 time 輸入本身已為 24 小時，附加 AM/PM 可能矛盾。因此只有 AM+00–11 或 PM+12–23 轉入新 bedtime；其餘原值保留並待確認。沒有根據的關燈時間與三題 boolean 都保持 NULL。

## 眼罩／硬體

兩份 `硬體端` 的 server.py、Pico-Audio.py、templates/index.html 已以 hash 核對並不相同，requirements.txt 相同。`../../VTCA2026/pico_audio` 是功能較完整的版本，額外支援 20 筆命令佇列、Wi-Fi 掃描／連線、BLE 掃描／連線／斷線、`/health` 與非同步 AP 配網；兩份均保留，未互相覆蓋。Pico W 透過 HTTP 輪詢 `/get_command`、回報 `/update_status`，WAV 經 `/files/<filename>` 串流至 I2S。命令 PLAY/STOP/ON/OFF/PRESS/LONG、GPIO15、RSSI、IP、SSID、記憶體與播放狀態已存在；BLE 連線不等於已取得 HRV。沒有可驗證的眼罩 HRV、壓力或疲倦感測器輸出。

保留原硬體檔案與控制介面。新 `intervention_events` 可以保存帶來源、裝置、Session、開始／結束時間的狀態及介入事件，透過受授權的 Supabase Data API 接收；尚未自動上傳既有未帶身份與絕對時間的 Pico 狀態。沒有新增任何自動治療或控制策略。
