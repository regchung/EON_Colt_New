# EON COLT 系統架構與技術選型

> **狀態說明**:本文件第 1 節(業務情境)仍為現況依據;**實際實作的技術選型與架構見下方「實作現況(As-Built)」**。
> 第 3 節之後為建置前的規劃選項(NestJS/Laravel/Redis 等),保留作為決策脈絡參考,**非最終實作**。
> 最完整、最新的說明請見專案根目錄 [`README.md`](../README.md)。

---

## 0. 實作現況(As-Built)

實際落地的技術與規劃略有差異,以本節為準:

| 項目 | 規劃(原第 3 節) | **實際實作** |
|------|------------------|--------------|
| 後端 | NestJS 或 Laravel | **FastAPI + SQLAlchemy 2 + Alembic** |
| 任務佇列 | Redis / BullMQ | **未使用**(排班為同步呼叫,VROOM 以 pyvroom 內嵌) |
| 地理編碼 | Nominatim / Google | **Map8(門牌級)**,Nominatim 備援;前置**地址簿快取** |
| 距離矩陣 | OSRM | **自架 OSRM `/table`**(可切 map8 / haversine) |
| 派遣引擎 | VROOM(HTTP) | **VROOM(pyvroom 內嵌於後端)** |
| 認證 | JWT + 角色 | **JWT(HS256)+ PBKDF2,單一管理員**(多角色未做) |
| 前端 | React | **Vue 3 + Bootstrap 5 + MapLibre** |

實際資料流:
```
登入(JWT)
  → 匯入車行訂單(自動地理編碼:Map8 + 地址簿快取 address_point/address_alias)
  → 一鍵排班(自架 OSRM 矩陣 → VROOM:skills 福祉車 / capacity 共乘 / time window 預約)
  → 寫回 orders(assigned_vehicle_id/dispatch_seq/eta)+ route_stop
  → 路線地圖(Map8 圖磚 + OSRM 實際路線 GeoJSON)
  → 動態重排(取消/開始/完成;重排鎖定 ongoing/done)
```

服務:Docker Compose 四服務 `db` / `backend` / `frontend` / `osrm`。
資料表:`vehicles`、`drivers`、`orders`、`address_point`、`address_alias`、`route_stop`、`users`(migration 0001–0006)。

關鍵程式:
- 排班:`backend/app/services/dispatcher.py`
- 地理編碼(DB 優先 + 別名):`backend/app/services/geocode.py`
- Map8 / OSRM / 矩陣抽象:`backend/app/services/{map8,osrm,matrix}.py`
- 認證:`backend/app/core/security.py`、`backend/app/api/deps.py`

---

## 1. 業務情境(已確認)

| 項目 | 內容 |
|------|------|
| 訂單來源 | 車行**批次匯入**的**預約**訂單(非即時叫車) |
| 共乘 | **包車(點對點)+ 共乘(同車多單)兩種都有** |
| 車種 | **福祉車**(輪椅/無障礙設備)+ **一般車** |
| 派遣時機 | **每日批次排班** + **當天動態插單/取消重排**(兩者都要) |

對應的運籌問題:**帶技能與容量限制的取送貨時間窗問題(PDPTW with skills & capacity)**。

---

## 2. 整體架構

```
┌─────────────┐   匯入(Excel/CSV)   ┌──────────────────────────┐
│  車行訂單檔  │ ───────────────────▶│  匯入服務 Import Service   │
└─────────────┘                      │  ・欄位驗證/正規化          │
                                     │  ・地址→經緯度(地理編碼)   │
                                     └────────────┬─────────────┘
                                                  │ 標準化訂單
                                                  ▼
┌──────────────┐  車輛/司機/車種     ┌──────────────────────────┐
│  主資料 DB    │◀───────────────────│  排班核心 Dispatch Core    │
│ (PostgreSQL) │                     │  ・組 VROOM 輸入            │
└──────────────┘                     │  ・呼叫 VROOM 求解          │
        ▲                            │  ・寫回派遣結果             │
        │ 距離/時間矩陣              └──────┬───────────────┬─────┘
        │                                   │               │
┌───────┴───────┐                          ▼               ▼
│  OSRM / 地圖   │                  ┌──────────────┐ ┌──────────────┐
│ (行車時間估算) │                  │  VROOM 引擎   │ │  後台 Web UI  │
└───────────────┘                  │ (路徑最佳化)  │ │ (派遣員監看)  │
                                    └──────────────┘ └──────────────┘
                                                            │
                                                            ▼
                                                    ┌──────────────┐
                                                    │  司機 App     │
                                                    │ (當日路線/導航)│
                                                    └──────────────┘
```

---

## 3. 元件與技術選型

| 層 | 角色 | 建議方案 | 理由 |
|----|------|----------|------|
| 派遣引擎 | 最佳化求解 | **VROOM** | 原生支援 shipment(取送貨)、skills(福祉車)、capacity(共乘座位)、time_window(預約)。毫秒級求解 |
| 地圖/路網 | 行車時間矩陣 | **OSRM** 自架(OSM 台灣圖資) | 免 API 費用、可離線、VROOM 官方搭配。初期可改用 Google Distance Matrix 加速開發 |
| 地理編碼 | 地址→經緯度 | **Nominatim** 自架 或 Google Geocoding | 批次匯入時把車行地址轉座標 |
| 後端 | 業務邏輯/API | **NestJS(Node/TS)** 或 **Laravel(PHP)** | TS 與 VROOM 的 TS SDK 一致;若想接 Fleetbase 當底座則選 Laravel |
| 資料庫 | 訂單/車輛/派遣 | **PostgreSQL + PostGIS** | PostGIS 處理座標/地理查詢;交易一致性佳 |
| 任務佇列 | 非同步求解/重排 | **BullMQ(Redis)** | 批次求解、動態重排都丟佇列,避免阻塞 API |
| 前端後台 | 派遣員監看/調整 | React + 地圖元件(MapLibre + Leaflet) | 顯示路線、手動微調、覆寫派遣 |
| 司機端 | 接單/導航 | React Native 或 PWA | 收當日排班、回報狀態(到達/上車/完成) |

> **要不要用 Fleetbase 當底座?** 若想省掉「車輛/司機/訂單 CRUD + 後台 + App 殼」的開發,可用 Fleetbase 當基礎,再把派遣決策換成自己呼叫 VROOM。代價是綁定其 Laravel/Ember 技術棧。若團隊熟 TS、想完全掌控,建議自建後端 + 直接整合 VROOM。

---

## 4. VROOM 資料模型對照(關鍵)

| EON COLT 概念 | VROOM 對應 | 說明 |
|---------------|-----------|------|
| 一張預約訂單 | `shipment` | pickup(上車)+ delivery(下車)綁同一台車 |
| 預約上車時間 | pickup 的 `time_windows` | 可給區間,如 09:00–09:30 |
| 福祉車需求 | `skills: [1]` | 訂單要求 skill 1;只有具 skill 1 的車能接 |
| 一般訂單 | 不設 skills | 任何車都能接(福祉車空檔也能兼接) |
| 共乘座位數 | `amount: [n]` + 車輛 `capacity: [座位]` | VROOM 保證車上人數不超過座位 |
| 包車 | 同 shipment,通常 amount 等於整車或單組客 | 與共乘共用同一模型,差別只在是否與他單同車 |
| 司機班別 | 車輛 `time_window` | 上下班時間 |
| 車行(出收車點) | 車輛 `start` / `end` | demo 用 index 0 |

> skills 設計細節:福祉車 `skills=[1]`,一般車 `skills=[]`。因 VROOM 規則是「車輛技能 ⊇ 訂單技能」,故福祉車(含 1)可接一般單(需求空集),反之一般車**不可**接福祉單 → 正是業務要的單向相容。

---

## 5. 兩種派遣時機的處理

### 5.1 每日批次排班
- 前一日/當日清晨,把當天所有預約訂單 + 可用車輛組成一份 VROOM 輸入,一次求解。
- 產出每台車的「當日任務序列 + 預計到點時間」,推給司機 App。

### 5.2 當天動態調整(新增 / 取消)
VROOM 是無狀態求解器,動態調整的標準作法是**重排(re-optimization)**:

1. **凍結已發生的部分**:已完成或司機正前往(進行中)的 step 不可更動。
   - 用 VROOM 的 `steps`(vehicle step 強制序列)把「已完成/進行中」的訂單**固定**在該車輛上,標記為已執行。
2. **取消訂單**:從輸入移除該 shipment。
3. **新增插單**:把新預約加進 shipments。
4. **以「當前時間 + 各車當前位置」為起點重新求解剩餘任務**:
   - 車輛 `start` 改為其當前位置;`time_window` 起點改為現在時刻。
5. 求解後,只有「尚未開始」的後續行程會被重排,已鎖定的不動。

> 觸發策略:取消/新增事件丟進 BullMQ,做**去抖動**(例如每 30–60 秒批次重排一次,而非每筆事件都重算),兼顧穩定與即時。

---

## 6. 建議落地順序(里程碑)

1. **M1 — 派遣核心可跑**:`/demo`(已完成)→ 接 OSRM 取代手寫矩陣 → 用真實地址跑一批。
2. **M2 — 匯入 + 資料模型**:見 `docs/batch-import.md`,把車行 Excel 變成標準訂單入庫。
3. **M3 — 批次排班 API + 後台檢視**:每日排班、地圖顯示路線。
4. **M4 — 動態重排**:取消/插單事件 → 去抖動重排。
5. **M5 — 司機 App + 狀態回報**:閉環(回報狀態餵回重排)。
