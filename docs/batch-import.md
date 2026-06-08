# 車行批次訂單匯入設計

> **實作現況**:本設計大致已落地(`orders` schema、狀態流、訂單→VROOM 映射皆一致)。
> 兩點差異:① 地理編碼改由 **Map8 + 地址簿快取**(`address_point`/`address_alias`,先查 DB 再打 Map8),
> 非單表 `geocode_cache`;② 解析失敗的列不寫入(於匯入報告回報),已建立的訂單若座標為空則前端標 ⚠️、
> 可按「地理編碼待處理」補。實作見 `backend/app/services/importer.py` 與 `geocode.py`。完整說明見 [`../README.md`](../README.md)。

## 1. 流程

```
車行 Excel/CSV
   │  上傳
   ▼
[1] 解析 + 欄位對應(欄名可能各家不同 → 用對應表 mapping)
   ▼
[2] 驗證(必填、時間格式、車種代碼、座位數合理性)
   ▼
[3] 地理編碼:上/下車地址 → 經緯度(Nominatim / Google)
   ▼
[4] 正規化為標準訂單,寫入 orders 表(狀態 = imported)
   ▼
[5] 產生匯入報告(成功 N 筆 / 失敗 M 筆 + 失敗原因)
```

## 2. 車行來源欄位(範例,實際以車行檔案為準)

| 來源欄位(中文) | 範例 | 對應系統欄位 |
|------------------|------|--------------|
| 預約日期 | 2026/06/10 | `service_date` |
| 上車時間 | 09:00 | `pickup_time` |
| 彈性(分) | 30 | `pickup_window_min` |
| 乘客姓名 | 王小明 | `passenger_name` |
| 電話 | 0912-xxx | `passenger_phone` |
| 上車地址 | 台北市… | `pickup_address` |
| 下車地址 | 新北市… | `dropoff_address` |
| 人數 | 2 | `pax` |
| 車種 | 福祉車 / 一般 | `vehicle_type` |
| 輪椅 | Y/N | `need_wheelchair` |
| 備註 | … | `note` |

> 各車行欄名/順序不一,建議做一張「**欄位對應表(column mapping)**」設定檔,每家車行一份,匯入時依來源套用,避免每次改程式。

## 3. 標準訂單資料模型(PostgreSQL 建議)

```sql
CREATE TABLE orders (
  id              BIGSERIAL PRIMARY KEY,
  source_batch_id BIGINT,                 -- 哪一批匯入
  service_date    DATE        NOT NULL,
  pickup_time     TIMESTAMPTZ NOT NULL,   -- 預約上車時間
  pickup_window   INTERVAL    DEFAULT '30 min',  -- 可接受彈性
  passenger_name  TEXT,
  passenger_phone TEXT,
  pickup_address  TEXT        NOT NULL,
  pickup_lng      DOUBLE PRECISION,       -- 地理編碼後
  pickup_lat      DOUBLE PRECISION,
  dropoff_address TEXT        NOT NULL,
  dropoff_lng     DOUBLE PRECISION,
  dropoff_lat     DOUBLE PRECISION,
  pax             SMALLINT    NOT NULL DEFAULT 1,  -- 人數 → VROOM amount
  vehicle_type    TEXT        NOT NULL,   -- 'welfare' | 'normal'
  need_wheelchair BOOLEAN     DEFAULT FALSE,
  allow_pool      BOOLEAN     DEFAULT TRUE,  -- 是否可共乘(包車設 FALSE)
  note            TEXT,
  status          TEXT        DEFAULT 'imported',  -- imported→scheduled→ongoing→done→canceled
  assigned_vehicle_id BIGINT,             -- 排班後寫回
  created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE vehicles (
  id          BIGSERIAL PRIMARY KEY,
  plate       TEXT,
  type        TEXT NOT NULL,          -- 'welfare' | 'normal'
  seats       SMALLINT NOT NULL,      -- → VROOM capacity
  shift_start TIME,                   -- 班別 → VROOM time_window
  shift_end   TIME,
  depot_lng   DOUBLE PRECISION,       -- 出/收車點
  depot_lat   DOUBLE PRECISION,
  active      BOOLEAN DEFAULT TRUE
);
```

## 4. 訂單 → VROOM 欄位映射規則

| 標準訂單欄位 | → VROOM | 規則 |
|--------------|---------|------|
| `pickup_lng/lat`, `dropoff_lng/lat` | shipment 的 pickup/delivery location | 透過 OSRM 轉成矩陣索引 |
| `pickup_time` ± `pickup_window` | pickup `time_windows` | `[[pickup_time, pickup_time + window]]`(轉成當日秒數) |
| `pax` | shipment `amount: [pax]` | 共乘容量計算用 |
| `vehicle_type='welfare'` 或 `need_wheelchair` | shipment `skills: [1]` | 任一成立即需福祉車 |
| `allow_pool=false`(包車) | 見下方「包車」處理 | 不與他單共乘 |
| 車輛 `type='welfare'` | vehicle `skills: [1]` | 福祉車具 skill 1 |
| 車輛 `seats` | vehicle `capacity: [seats]` | |
| 車輛 `shift_start/end` | vehicle `time_window` | 轉當日秒數 |

### 包車(不可共乘)的兩種作法
1. **簡單法**:把該訂單 `amount` 設為等於車輛座位數 → 一上車就佔滿,自然排不進別單(近似包車)。
2. **精確法**:每張包車單獨立一段車輛任務/或加 skill 標記專屬,確保不與他單合併。初期建議用簡單法。

## 5. 匯入實作要點
- **冪等**:同一批重複上傳要能偵測(用車行訂單號或 hash),避免重複建單。
- **地理編碼快取**:相同地址快取座標,省 API 呼叫、加速。
- **失敗不擋全批**:單筆地址解析失敗 → 標記該筆 `status=geocode_failed` 進人工補正,其餘照常。
- **時區**:一律存 UTC(`TIMESTAMPTZ`),排班時換算當日 00:00 起的秒數給 VROOM。

## 6. 下一步
有了標準 `orders` / `vehicles`,排班核心就是:
讀當日 `status='imported'/'scheduled'` 的訂單 + `active` 車輛 → 套用上表映射組 VROOM 輸入(參考 `demo/solve.py`)→ 求解 → 把結果寫回 `assigned_vehicle_id` 與順序。
