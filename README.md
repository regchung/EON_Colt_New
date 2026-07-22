# DrFish — 預約制車隊自動派遣系統

[![CI](https://github.com/regchung/DR_FISH/actions/workflows/ci.yml/badge.svg)](https://github.com/regchung/DR_FISH/actions/workflows/ci.yml)

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
| 動態重排 | 取消 / 開始 / 完成;**進行中(ongoing)訂單以唯一技能硬鎖原車**(delivery-only Job,不重排上車) |
| **區域親和建議** | 同區新單優先推薦今天已在該區的司機(達 N 觸發),護欄=車種/座位/上限;建議→採用(人在迴路) |
| 路線地圖 | Map8 圖磚 + OSRM 實際道路路線,每車一色 + 上下車站點 |
| 司機 App | 司機登入看「我的路單」(綁定車輛,讀 route_stop) |
| AI 派遣 | Claude 排班分析 / 插單建議(需 `ANTHROPIC_API_KEY`) |
| **AI 文件智慧匯入** | 上傳 PDF/Word/Excel/CSV → Claude 抽取結構化訂單 → 建單 + 自動地理編碼(`/orders/import-doc`;⚠️文件原文送 Claude,合規見 Roadmap) |
| **調度員 AI 助理** | 對話式 + Claude tool-use(查單/出勤/統計/需求預測 4 唯讀工具),以真實資料為依據給建議(`/dispatch/assistant`,前端「💬 AI 助理」) |
| 使用者管理 | 新增 / 刪除帳號、重設密碼、指定角色與綁車(防刪最後一人) |
| 報表 | 區間營運彙總 + **CSV 匯出** + **區間趨勢圖**(零依賴 SVG 折線:總數/已派/未派、派遣率):狀態/車種分佈、每日量、派遣率、各車派遣量 |
| 歷史匯入 | 長照平台匯出檔 → 訂單 + **人工派遣結果**(`dispatch_history`)+ 自建車/司機 + 灌地址簿(去識別化) |
| 車行標記 | 集團統一派遣:`fleet` 標記每筆訂單;車輛共用車池 + `home_fleet` |
| 車隊名冊匯入 | 司機/車輛主檔 → 回填真實可載客數、福祉能力、**出車起點/收車終點**(`fleet_import`) |
| 起訖點錨定 | 車輛 `start`/`end` 座標;VROOM 令每車首站自起點出發、末站返回終點 |
| 司機營運規則 | 前後 40 分/趟、8h 工時上限、06:00–18:00 服務時段、共乘需同意;上車時間 +08 時區換算 |
| 系統參數設定 | `app_settings` key-value;管理者於「參數設定」頁 CRUD 派遣/共乘營運參數,即時派遣即時採用 |
| 班表(出勤) | 週期班表 + **每車班別時段(起/迄)** + 單日例外(請假/維修/加班);即時派遣只用當日出勤車並以班別時段為 time_window;可從歷史回推 |
| 需求預測 | weekday 季節基線 → 各日趟次/建議排車數;班表頁可**一鍵套用建議排車數**(挑該車行歷史最常出勤前 N 台覆寫週期班表) |
| 人工 vs 自動對比 | 逐(車行×日)以 OSRM+VROOM 重排,比人工用車/里程/可行性;前端對比頁 + PDF 報告(實務約束下集團 **↓18.4%** 車日,服務逾 95% 趟次) |
| **對比進階** | **成本效益**(省下車日→NT$:實測 ↘536 車日≈134萬、年化≈298萬)+ **時間窗敏感度**(15/30/45/60 分省車率權衡) |
| 時區一致 | 全鏈台灣 +08:寫入統一標 +08;DB 連線 `timezone=Asia/Taipei` → 讀回帶 +08,API/報表/路單/前端顯示一致 |
| **車輛任務口卡** | 依車行→每車→時間排序的當日任務,可依日期/車行/車牌過濾、列印給司機(`/dispatch/daily-tasks`) |
| **未派分析 + 行控回饋** | 系統無法排入的訂單依日歸類,顯示推斷原因 + 人工當時用哪台車;行控可填實際因素協助學習(`unassigned_record`) |
| **未派回饋學習建議** | 聚合未派原因×回饋 → 規則式改善建議 + Claude 白話方案(放寬時段/上車窗、增福祉車、推共乘) |
| **固定行程指定司機** | 規則(地點關鍵字/乘客姓名 + 早午晚時段)→ 派遣時以技能硬綁指定司機的車;CRUD + 某日比對預覽 |
| **司機↔車對應** | 司機車輛對應、補無車司機、**當日輪車指派**(`driver_resolve`);供休假/固定行程/口卡共用 |
| **自然語言出勤解析** | 貼「休3人:…」「某司機8-11不排」→ Claude 解析 → 自動產生班表例外(`/roster/parse-attendance`) |
| **拖放派遣看板** | 各車欄位拖放訂單卡重新指派/卸載,時間衝突即時標紅(`/dispatch/board`) |
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
DR_FISH/
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
│   ├── alembic/versions/     # 0001…0016 migration
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
| `POST /orders/import-doc?service_date=` | **AI 文件智慧匯入**:PDF/Word/Excel/CSV → Claude 抽單 → 建單+編碼 |
| `POST /orders/{id}/geocode` · `POST /orders/geocode-pending` | 地理編碼 |
| `POST /orders/{id}/cancel` · `POST /orders/{id}/status?value=` | 取消 / 改狀態 |
| `POST /orders/{id}/assign?vehicle_id=` | 手動指派車輛(採用建議) |
| `… /vehicles`、`… /drivers`(CRUD) | 車輛 / 司機 |
| `POST /dispatch/run?service_date=&ai=` | 一鍵排班(ai=true 附 Claude 摘要) |
| `POST /dispatch/zone-suggest?order_id=&service_date=` | **區域親和建議**(dry-run) |
| `POST /dispatch/ai-analyze` · `POST /dispatch/ai-insert` | AI 排班分析 / 插單建議 |
| `POST /dispatch/assistant` | **調度員 AI 助理**:對話 + Claude tool-use(唯讀查單/出勤/統計/預測)給建議 |
| `GET /dispatch/routes-geojson?service_date=` | 路線 GeoJSON |
| `GET /dispatch/matrix?service_date=` · `GET /dispatch/osrm-health` | 矩陣預覽 / OSRM 探活 |
| `GET /addresses` | 地址簿 |
| `… /users`(列表/新增/刪除)· `PUT /users/{id}/password` | 使用者管理(角色/綁車) |
| `GET /reports/overview` · `GET /reports/export-csv` | 營運報表 / CSV 匯出 |
| `POST /history/import` · `GET /history/stats` | 長照派遣歷史匯入 / 統計 |
| `POST /fleet/import` | 車隊名冊匯入(回填座位/福祉/出車起點·收車終點) |
| `GET /dispatch/comparison/summary` · `GET /dispatch/comparison?fleet=` | 人工 vs 自動對比(總覽 / 逐日) |
| `GET /dispatch/comparison/savings` · `GET /dispatch/comparison/sensitivity?windows=` | **對比進階**:省下車日→NT$(實測/年化)/ 時間窗敏感度 |
| `GET /dispatch/pool-suggest?service_date=&fleet=` | 共乘推薦:雙跑 VROOM 找值得徵詢同意的組 + 可省車數 |
| `POST /dispatch/pool-consent` | 登錄共乘同意/撤回(留痕 by/at);同意後排班自動納入共乘 |
| `GET /dispatch/pool-recurring?min_days=3` | 常態共乘對:反覆同時間/同起訖點同行的乘客對,適合徵長期同意 |
| `GET /dispatch/pool-gain` | 共乘增益總覽(讀 `pool_projection`):現況→共乘後車日 + 額外省幅,供對比頁/報表 |
| `GET /dispatch/driver-suggest?passenger=` · `GET /dispatch/driver-loyalty` | 常客固定駕駛:乘客→慣用駕駛建議 / 高忠誠乘客清單(軟性偏好) |
| `GET/POST /settings` · `PUT/DELETE /settings/{key}` | 系統參數設定 CRUD(**限系統管理者**);即時派遣讀取營運參數 |
| `GET /roster/availability?service_date=` · `GET/PUT /roster/patterns` · `/roster/exceptions` · `POST /roster/seed-from-history` · `POST /roster/apply-forecast?fleet=&dry_run=` | 班表:當日出勤查詢 / 週期班表(含班別時段)/ 例外 / 歷史回推 / **一鍵套用建議排車數** |
| `GET /dispatch/demand-forecast?fleet=&horizon_days=&lookback_weeks=` | 輕量需求預測(weekday 基線):各日趟次 + 建議排車數 |
| `GET /dispatch/daily-tasks?service_date=&fleet=&plate=` · `/daily-tasks/meta` | 車輛任務口卡(依車行→每車→時間) |
| `GET /dispatch/unassigned/dates` · `/unassigned?service_date=` · `/unassigned/{id}` · `POST /unassigned/{id}/feedback` | 未派分析:依日清單 / 某日明細 / 單筆(原因+人工車)/ 行控回饋 |
| `GET /dispatch/unassigned/insights?fleet=&ai=` | 未派回饋學習建議(規則 + Claude 白話方案) |
| `GET /dispatch/board?service_date=` · `POST /orders/{id}/assign` · `/orders/{id}/unassign` | 派遣看板(各車趟次+衝突)/ 拖放指派 / 卸載 |
| `… /fixed-routes`(CRUD)· `GET /fixed-routes/match?service_date=` | 固定行程指定司機(地點/姓名規則)/ 某日比對預覽 |
| `GET /driver-vehicle` · `POST /driver-vehicle/{id}/assign` · `/create-driver` · `/daily` | 司機↔車對應 / 指派或建車 / 補司機 / 當日輪車 |
| `POST /roster/parse-attendance` · `/roster/apply-attendance` | 自然語言出勤解析(貼文字→班表例外) |
| `POST /orders/import-doc?service_date=` · `POST /dispatch/assistant` | AI 文件智慧匯入 / 調度員 AI 助理 |

> 對比批次與 PDF 報告:`comparison.run_batch()` 跑全車行×日;`pool_suggest.project_and_store()` 跑共乘增益投影(寫 `pool_projection`);`python3 scripts/make_report.py` 產生 `DR_FISH_對比報告.pdf`(含「共乘增益」一節)。

## 測試

後端測試(pytest):
```bash
# 本機(容器內,使用執行中的 DB)
docker compose exec backend python -m pytest -q
# CI 會以全新 postgres service 跑:alembic upgrade head → pytest
```
測試位於 `backend/tests/`:`test_importer`/`test_services`(純函式:settings/roster/comparison 時區/
zone_affinity/doc_ingest/assistant/訂單時區驗證器)+ `test_api`/`test_endpoints`(授權、apply-forecast、
手動指派、AI 助理端點)。共 **50 passed**(本機已設金鑰時 no-key 降級測試自動 skip)。
> pytest 在 `requirements-dev.txt`(CI 已裝);本機執行容器需先 `pip install -r requirements-dev.txt`。
> `pool_suggest`/`comparison`/`dispatcher` 的 VROOM 求解測試待 CI 內備 OSRM 矩陣後補。
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
git clone https://github.com/regchung/DR_FISH.git
cd DrFish
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
