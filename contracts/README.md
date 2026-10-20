# HRV／PRV 檔案交換契約 v1.0.0

兩個專案各自保存同版本的契約文件；沒有根目錄 shared 資料夾，也沒有跨專案程式依賴。變更格式時須更新版本並同步兩份契約。

兩專案保持獨立；共用只有 `hrv-session.v1.schema.json` 的格式、欄位與單位，不互相 import 原始碼。VTCA2026 的 `hrv_contract.json` 符合本契約。`hrv-session.v1.example.json` 全部指標為 null，表示未量測，不能當真實研究資料。

必要欄位包含 session、裝置、訊號來源、指標類型、取樣率、分析窗、算法版本、單位、訊號品質、來源 hash、計算時間。PPG 必須標 PRV。`duration_s` 是實際選出的分析窗長度，不是依假定 fs 推算的原始錄製長度。計算時間為 UTC；`analysis_window` 是裝置相對秒，不能擅自當絕對量測時間。

| 欄位 | 單位與定義 |
|---|---|
| mean_ppi_ms、sdnn_ms、rmssd_ms、sdsd_ms | ms，PPG 峰間期統計 |
| pnn50_pct | %，abs(相鄰 PPI 差)>50 ms 的比例，分母為差分數 |
| tp_ms2 | ms²，VLF+LF+HF（0.0033–0.4 Hz） |
| vlf_ms2、lf_ms2、hf_ms2 | ms²，依版本所列頻帶；短期 VLF 可信度有限 |
| lf_hf_ratio | 無單位 |
| lfnu_pct、hfnu_pct | %，分母 LF+HF |

`UNVERIFIED_TIMING`、`INSUFFICIENT_DATA` 或合成不足時，指標為 null。`EXPLORATORY_ENCODING` 表示時間／品質窗合格但 ADC 解碼未確認；`SYNTHETIC_ONLY` 僅供軟體測試。即使 `VALID` 也不是臨床診斷、外部時鐘校準或 ECG 等價驗證。

NSYSU 的現有 canonical 生理指標 API 仍維持逐筆 `metric/value/unit/signal_type/algorithm_version/measured_at` 格式。本契約不會自動寫入正式庫；後續 adapter 須先確認絕對量測時間、受試者授權、品質與來源，再轉換資料。不可把 `calculated_at` 當 `measured_at`，不可將 null 改成 0，且不得將 synthetic 匯入真實受試者紀錄。CSV 可用 `hrv_results.csv` 的 metric/field/value/unit/quality_status/metric_type，與同目錄契約／品質報告一併保存。
