# SmartCar — 預約制車隊自動派遣系統

[![CI](https://github.com/regchung/SmartCar/actions/workflows/ci.yml/badge.svg)](https://github.com/regchung/SmartCar/actions/workflows/ci.yml)

取代人工派遣的車隊調度系統。訂單來自車行**批次匯入的預約單**,車種分**福祉車**與**一般車**,
支援**包車與共乘**,可**每日批次排班**並在當天**動態插單/取消重排**,並以地圖呈現每車路線。

全套自架於 Docker:地址用 **Map8(台灣門牌級)**、行車時間矩陣用**自架 OSRM(免費)**、
派遣最佳化用 **VROOM**,前端 **Vue3 + Bootstrap5** 自適應後台,登入採 **JWT**。

---

## 功能總覽

| 功能 | 說明 |
|------|------|
| 登入認證 | JWT + **多角色**(admin / dispatcher / driver);資料 API 全程保護。預設 `admin` / `admin123` |
| 主資料管理 | 訂單 / 車輛 / 司機 CRUD,RWD 後台 |
| 批次匯入 | 車行 `.xlsx` / `.csv` 匯入(SSE 進度),中文表頭辨識,逐列驗證,**匯入後自動地理編碼** |
| 地理編碼 | Map8 門牌級(可切 Nominatim)+ **地址正規化**;**地址簿快取**:先查 DB、未命中才打 Map8 |
| 地址簿 | 一個門牌(校正後地址+座標)對應多種原始描述;查無也快取 |
| 自動排班 | VROOM:福祉車(skills)、共乘(capacity)、預約(time window)、班別 |
| 行車時間矩陣 | 自架 OSRM `/table`(台灣 OSM 圖資,$0) |
| 動態重排 | 取消 / 開始 / 完成;重排時鎖定進行中與已完成訂單 |
| **區域親和建議** | 同區新單優先推薦今天已在該區的司機(達 N 觸發),護欄=車種/座位/上限;建議→採用(人在迴路) |
| 路線地圖 | Map8 圖磚 + OSRM 實際道路路線,每車一色 + 上下車站點 |
| 司機 App | 司機登入看「我的路單」(綁定車輛,讀 route_stop) |
| AI 派遣 | Claude 排班分析 / 插單建議(需 `ANTHROPIC_API_KEY`) |
| 使用者管理 | 新增 / 刪除帳號、重設密碼、指定角色與綁車(防刪最後一人) |
| 報表 | 區間營運彙總 + **CSV 匯出**:狀態/車種分佈、每日量、派遣率、各車派遣量 |
| 歷史匯入 | 長照平台匯出檔 → 訂單 + **人工派遣結果**(`dispatch_history`)+ 自建車/司機 + 灌地址簿(去識別化) |
| 車行標記 | 集團統一派遣:`fleet` 標記每筆訂單;車輛共用車池 + `home_fleet` |
| 人工 vs 自動對比 | 逐(車行×日)以 OSRM+VROOM 重排,比人工用車/里程/可行性;前端對比頁 + PDF 報告 |
| CI | GitHub Actions:後端 pytest(postgres)、前端 build、Docker 映像建置 |

---

## 系統架構

```
                          ┌─────────────────────────────┐
   瀏覽器 (Vue3+BS5) ──────│  frontend (nginx :8080)     │
   登入 / 後台 / 地圖       │  靜態檔 + /api 反向代理       │
                          └──────────────┬──────────────┘
                                         │ /api
                          ┌──────────────▼──────────────┐
                          │  backend (FastAPI :8000)    │
                          │  JWT 認證・CRUD・匯入        │
                          │  地理編碼・排班・路線         │
                          └──┬───────────┬───────────┬──┘
                ┌────────────┘           │           └────────────┐
        ┌───────▼────────┐     ┌─────────▼────────┐     ┌──────────▼─────────┐
        │ PostgreSQL :5432│     │ OSRM :5001       │     │ Map8 API (雲端)     │
        │ 訂單/車輛/司機   │     │ 行車時間矩陣      │     │ 地址→門牌座標        │
        │ 地址簿/路線/使用者│     │ + 實際路線幾何    │     │ (地址簿快取後少呼叫) │
        └────────────────┘     └──────────────────┘     └────────────────────┘
                                         ▲
                                  VROOM (pyvroom, 內嵌於 backend)
```

四個 Docker 服務:`db` / `backend` / `frontend` / `osrm`(OSRM 以 profile 控制,前處理後啟動)。

---

## 技術棧

| 層 | 選用 |
|----|------|
| 前端 | Vue 3 (Vite) + Bootstrap 5 + Vue Router + Pinia + Axios + MapLibre GL |
| 後端 | FastAPI + SQLAlchemy 2 + Alembic + Pydantic v2 + psycopg3 |
| 派遣引擎 | VROOM(pyvroom,內嵌) |
| 路網 | 自架 OSRM(台灣 OSM) |
| 地理編碼 | Map8(台灣圖霸)/ Nominatim 備援 |
| 資料庫 | PostgreSQL 16 |
| 認證 | JWT(HS256)+ PBKDF2,純標準庫實作 |
| 容器 | Docker Compose |

---

## 快速開始

### 1) 啟動主系統
```bash
cp .env.example .env        # 視需要填入 MAP8_API_KEY、改密碼/SECRET_KEY
docker compose up --build -d # 或 make up
```
- 前端:http://localhost:8080 （登入 `admin` / `admin123`)
- 後端 API:http://localhost:8000 ・Swagger:http://localhost:8000/docs
- PostgreSQL:localhost:5432

### 2) 準備路由引擎(排班/地圖前必要,一次性)
```bash
make osrm-prepare   # 下載 taiwan-latest.osm.pbf(~310MB)+ 建索引(數分鐘)
make osrm-up        # 啟動 osrm-routed,對外 5001
```

### 3) 啟用 Map8 門牌級地理編碼(可選,需金鑰)
於 `.env` 設定後重啟 backend:
```
GEOCODER_PROVIDER=map8
MAP8_API_KEY=<你的 Map8 JWT>
```
未設定時自動使用 Nominatim(路段級)。

---

## 操作流程(每日營運)

1. **登入** → 進入後台。
2. **車輛 / 司機** 建檔(車種、座位、班別、出車點)。
3. **訂單管理 → 批次匯入** 車行 Excel/CSV(自動地理編碼);或手動新增。
4. **🚀 一鍵排班**(選日期)→ VROOM 產生每車派遣順序與 ETA,寫回訂單。
5. **🗺️ 路線地圖** 檢視每車實際路線。
6. 當天有變動:訂單**取消**或標記**開始/完成**,再按一次排班即重排(鎖定進行中)。

---

## 環境變數(`.env`)

| 變數 | 預設 | 說明 |
|------|------|------|
| `DATABASE_URL` | postgresql+psycopg://… | DB 連線 |
| `BACKEND_CORS_ORIGINS` | localhost:8080,5173 | 允許來源 |
| `GEOCODER_PROVIDER` | `nominatim` | `nominatim` / `map8` |
| `MAP8_API_KEY` | (空) | Map8 金鑰;設定後可切 map8 |
| `MATRIX_PROVIDER` | `osrm` | `osrm` / `map8` / `haversine` |
| `OSRM_URL` | http://osrm:5000 | OSRM 位址(容器內) |
| `SECRET_KEY` | change-me… | JWT 簽章金鑰,**正式請改** |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 720 | Token 有效期 |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | admin / admin123 | 啟動時種子管理員 |
| 埠號 | 8000/8080/5432/5001 | `BACKEND_/FRONTEND_/DB_/OSRM_PORT` |

---

## 專案結構

```
SmartCar/
├── docker-compose.yml        # db / backend / frontend / osrm(profile)
├── Makefile                  # up/down/logs/migrate/psql/osrm-*
├── .env.example
├── backend/                  # FastAPI
│   ├── app/
│   │   ├── main.py           # 路由掛載 + JWT 保護 + 種子管理員
│   │   ├── core/             # config、security(JWT/PBKDF2)
│   │   ├── db/               # engine / session
│   │   ├── models/           # vehicle/driver/order/address/route/user
│   │   ├── schemas/          # Pydantic
│   │   ├── crud/             # 泛型 CRUD
│   │   ├── api/routes/       # auth/orders/vehicles/drivers/dispatch/addresses/config/health
│   │   └── services/         # geocode / map8 / osrm / matrix / dispatcher / importer
│   ├── alembic/versions/     # 0001…0006 migration
│   └── sample_orders.csv     # 匯入範例
├── frontend/                 # Vue3 + Vite + Bootstrap5
│   └── src/{views,stores,components,router,api}
├── osrm/prepare.sh           # 下載台灣 OSM + 建索引
└── demo/                     # 獨立 VROOM 試跑範例(pyvroom)
```

---

## 資料模型(主要表)

- `vehicles`：車牌、車種(welfare/normal)、座位、班別、出車點、是否啟用
- `drivers`：姓名、電話、駕照、指派車輛
- `orders`：服務日、上車時間+彈性、上/下車地址與座標、人數、車種、輪椅、共乘、
  狀態(imported→scheduled→ongoing→done/canceled)、`assigned_vehicle_id`、`dispatch_seq`、`eta`
- `address_point`：校正後地址(唯一)+ 座標 + 精度 + 行政區 + 來源
- `address_alias`：原始描述 → 門牌(NULL = 查無快取)
- `route_stop`：排班產生的每車停靠序列(供地圖/路單)
- `users`：帳號 + PBKDF2 雜湊密碼

---

## API 一覽（前綴 `/api`)

公開:`GET /health`、`GET /config`、`POST /auth/login`
需 JWT:其餘全部

| 方法 路徑 | 說明 |
|----------|------|
| `POST /auth/login` · `GET /auth/me` | 登入 / 取得自己 |
| `… /orders`(CRUD) | 訂單;`?service_date=&status=&vehicle_type=` 篩選 |
| `GET /orders/import/template` · `POST /orders/import` | 範本 / 批次匯入(自動編碼) |
| `POST /orders/{id}/geocode` · `POST /orders/geocode-pending` | 地理編碼 |
| `POST /orders/{id}/cancel` · `POST /orders/{id}/status?value=` | 取消 / 改狀態 |
| `POST /orders/{id}/assign?vehicle_id=` | 手動指派車輛(採用建議) |
| `… /vehicles`、`… /drivers`(CRUD) | 車輛 / 司機 |
| `POST /dispatch/run?service_date=&ai=` | 一鍵排班(ai=true 附 Claude 摘要) |
| `POST /dispatch/zone-suggest?order_id=&service_date=` | **區域親和建議**(dry-run) |
| `POST /dispatch/ai-analyze` · `POST /dispatch/ai-insert` | AI 排班分析 / 插單建議 |
| `GET /dispatch/routes-geojson?service_date=` | 路線 GeoJSON |
| `GET /dispatch/matrix?service_date=` · `GET /dispatch/osrm-health` | 矩陣預覽 / OSRM 探活 |
| `GET /addresses` | 地址簿 |
| `… /users`(列表/新增/刪除)· `PUT /users/{id}/password` | 使用者管理(角色/綁車) |
| `GET /reports/overview` · `GET /reports/export-csv` | 營運報表 / CSV 匯出 |
| `POST /history/import` · `GET /history/stats` | 長照派遣歷史匯入 / 統計 |
| `GET /dispatch/comparison/summary` · `GET /dispatch/comparison?fleet=` | 人工 vs 自動對比(總覽 / 逐日) |

> 對比批次與 PDF 報告:`comparison.run_batch()` 跑全車行×日;`python3 scripts/make_report.py` 產生 `SmartCar_對比報告.pdf`。

## 測試

後端測試(pytest):
```bash
# 本機(容器內,使用執行中的 DB)
docker compose exec backend python -m pytest -q
# CI 會以全新 postgres service 跑:alembic upgrade head → pytest
```
測試位於 `backend/tests/`(匯入解析器單元測試 + API 整合測試)。
CI 設定見 [`.github/workflows/ci.yml`](.github/workflows/ci.yml)。

---

## 常用指令(Makefile)

| 指令 | 作用 |
|------|------|
| `make up` / `make down` | 起 / 停 |
| `make logs` | 跟蹤日誌 |
| `make migrate` | 套用 migration |
| `make psql` | 進 DB |
| `make osrm-prepare` / `make osrm-up` | 準備 / 啟動 OSRM |

---

## 疑難排解

- **排班回 502 / OSRM not ready**:先 `make osrm-prepare` 再 `make osrm-up`;`GET /api/dispatch/osrm-health` 應為 `ready:true`。
- **訂單未派(unassigned)**:多為超出車輛班別、座位不足、時間窗不可行,或尚未地理編碼(📍 顯示 ⚠️)。
- **登入後仍 401**:Token 過期重登;或確認 `SECRET_KEY` 未變更(變更會使既有 token 失效)。
- **改密碼不生效**:種子只在「無任何使用者」時執行;改 `.env` 後需清空 `users` 表再重啟。
- **下載/檔案類功能失敗(401)**:API 受 JWT 保護,純 `<a href>` 或開新分頁**不會帶 token**。
  下載一律走 axios 取 blob 再觸發(見「下載範本」`downloadTemplate`)。
- **改了前端卻沒變化**:前端為建置後的靜態檔,改動需 `docker compose up -d --build frontend`,
  瀏覽器再**強制重新整理**(`Cmd/Ctrl+Shift+R`)。

## 前端開發注意

- **JWT 與下載**:任何需要授權的下載/匯出,務必用 axios(`responseType: 'blob'`)帶 token,
  不要用 `<a href>` 直連 API。
- **Bootstrap 與 Vue Router**:不要在 `<RouterLink>`(會渲染成 `<a>`)上加 `data-bs-dismiss`,
  Bootstrap 會對該 `<a>` 呼叫 `preventDefault()`,導致**點選單無法換頁**。
  需關閉手機側欄請監看路由變化後呼叫 `Offcanvas.getInstance(el).hide()`(見 `AppLayout.vue`)。

---

## 部署與版本控制

### 從 GitHub 取得並啟動
```bash
git clone https://github.com/regchung/SmartCar.git
cd SmartCar
cp .env.example .env          # 填入 MAP8_API_KEY、改 SECRET_KEY 與管理員密碼
docker compose up --build -d  # 起 db / backend / frontend
make osrm-prepare && make osrm-up   # 準備並啟動路由引擎(排班/地圖需要)
```

### 機密管理(重要)
- **`.env` 不進版控**(已列入 `.gitignore`)。`MAP8_API_KEY`、`SECRET_KEY`、管理員密碼只放這裡。
- 切勿把 API 金鑰 / Token 貼進程式或 commit;範本一律用 `.env.example`(空值)。
- 正式環境務必更換 `SECRET_KEY` 與 `ADMIN_PASSWORD`。

### 推送變更
```bash
git add -A
git commit -m "說明"
git push                       # 需先完成 GitHub 認證
```
建議用 `gh auth login`(web 流程)設定認證,避免在指令或設定檔中放入 Personal Access Token。
若用 Token,完成後請至 GitHub 撤銷,避免外流。

## 開源參考 / 進一步

可參考的開源專案:[VROOM](https://github.com/VROOM-Project/vroom)、
[OSRM](https://github.com/Project-OSRM/osrm-backend)、
[Fleetbase](https://github.com/fleetbase/fleetbase)、
[Traccar](https://github.com/traccar/traccar)。

設計文件:[`docs/architecture.md`](docs/architecture.md)、[`docs/batch-import.md`](docs/batch-import.md)。
獨立派遣試跑:[`demo/`](demo/)。

### Roadmap(未做)
區域親和接進批次排班(VROOM 軟性偏好 + 人工vs自動對比)、文件智慧匯入(MarkItDown→Claude)、
調度員 AI 助理(Claude tool-use)、司機狀態回報→重排、報表趨勢圖、多租戶與個資合規。
完整規劃見 [`docs/self-build-roadmap.md`](docs/self-build-roadmap.md)。
