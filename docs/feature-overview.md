# SmartCar 功能總覽(技術版)

> 取代人工派遣的**預約制長照接送車隊系統**。車行批次匯入預約單 → 地理編碼 →
> VROOM 自動排班(福祉車/共乘/時間窗)→ 地圖呈現 → 當天動態重排。**全套自架於 Docker**。
> 規模:18 路由模組 / 26 服務模組 / 15 資料表 / 20 前端頁 / migration 至 0023。

## 技術棧
| 層 | 選用 |
|---|---|
| 前端 | Vue 3 + Vite + Bootstrap 5 + Pinia + Vue Router + MapLibre GL |
| 後端 | FastAPI + SQLAlchemy 2 + Alembic + Pydantic v2 + psycopg3 |
| 資料庫 | PostgreSQL 16(時區統一 Asia/Taipei） |
| 派遣引擎 | VROOM(pyvroom 內嵌,PDPTW shipment) |
| 路網矩陣 | 自架 OSRM(備援 haversine) |
| 地理編碼 | Map8 門牌級(備援 Nominatim)+ 地址簿快取 |
| 認證 | JWT(HS256)+ PBKDF2(純標準庫) |
| 容器 | Docker Compose:db / backend / frontend / osrm |
| AI | Claude(文件抽取 / 調度助理 / 改善建議),httpx 直連,無金鑰時優雅降級 |

## 功能模組

### 1. 訂單與匯入
- 訂單 CRUD;批次匯入 Excel/CSV/PDF(SSE 進度 + 自動地理編碼)。
- **長照平台歷史匯入**(`history_import`):去識別化(不存身分證)、自建車/司機、灌地址簿座標。
- **AI 文件智慧匯入**(`doc_ingest`):PDF/Word/Excel/CSV → Claude 抽單 → 建單。
- 個案標籤 `case_tag`(姓名+地址補充+醫療設施名稱),供固定行程匹配。

### 2. 地理編碼與地址簿
- DB 優先(`address_alias` → `address_point`),未命中才打 Map8 → 省費 + 加速。
- 多描述歸一門牌(別名);匯入時自動回填真實座標。

### 3. 智慧派遣(核心)
- **VROOM 一鍵排班**:每張單 = shipment(上車→下車配對)、2 維容量(座位 + 共乘同意佔位)、
  車種/輪椅技能、時間窗、車輛起訖點錨定。
- **司機營運規則**:每趟前後置 40 分、8h 工時上限、06–18 服務時段、**完成緩衝**(時段內上車可延後完成)。
- **動態重排**:取消/開始/完成;**ongoing 硬鎖原車**(唯一技能,非 steps)。
- **路線地圖**:Map8 圖磚 + OSRM 路線 + 站點。

### 4. 固定行程(指定司機)
- 規則 CRUD(地點關鍵字 / 指定姓名 + 時段分流);匹配 → 以 PIN 技能硬綁指定車。
- **固定行程健檢**(`fixed_route_blocks`):把固定行程當既定骨架,偵測同司機**時間重疊/銜接不及**衝突,
  自動分類(同校同時段=可共乘 / 滿座=需備援),並量化可接單空檔。`GET /fixed-routes/blocks`。

### 5. 共乘
- 推薦 P1+P2+P3(`pool_suggest`)+ 同意捕捉留痕(`pool-consent`)+ 一鍵「標記同意並重算」。
- 常態共乘對挖掘(`recurring_pairs`,反覆同行 ≥3 日)。
- 共乘增益接進報表/對比(`pool_projection`)。

### 6. 班表 / 出勤 / 司機-車
- 週期 `shift_pattern` + 單日 `shift_exception`;即時派遣只納當日出勤車。
- **自然語言出勤解析**(`attendance_parse`):貼出勤文字 → Claude 解析 → 班表例外。
- 需求預測(`forecast`,weekday 季節基線)+ 一鍵套用建議排車數。
- 司機↔車地基(`driver_resolve`)+ 當日輪車指派(`driver_vehicle_assignment`)。

### 7. 司機端(PWA)
- 「我的路單」:當日站點、開始/完成回報(+08 時區一致)。
- **Web Push 推播**(`push`,pywebpush/VAPID):司機訂閱 → 派遣異動推通知;失效訂閱自動清。

### 8. 行控工具
- **拖放派遣看板**(`dispatch_board`):依車行→車→時間,原生拖放改派 + 時間衝突標紅。
- **車輛任務口卡**(`daily-tasks`):依日期/車行/車牌過濾,可列印給司機。
- **未派分析**(`unassigned_record`):依日歸類、推斷原因(時段外/無福祉車/無法路由/滿載)、
  行控填回饋;**AI 改善建議**(`unassigned_insights`)聚合原因×回饋 → 規則建議 + Claude 白話方案。

### 9. AI 功能
- 調度助理(`assistant`):對話 + Claude tool-use,唯讀查真實資料給建議(注入台灣當日日期)。
- AI 文件匯入、未派改善方案(見上)。
- ⚠️ 個資合規:文件原文送 Claude,正式上線前評估地端抽取。

### 10. 報表與效益分析
- 營運報表 + CSV 匯出 + 區間趨勢圖(零依賴 SVG)。
- **人工 vs 自動對比**(`comparison`):省下車日 → NT$、時間窗敏感度。
- PDF 報告產生器:技術版 / 管理版 / 營運分析(含尖峰壅塞情報)。

### 11. 系統管理
- 多角色(admin / dispatcher / driver)+ 使用者管理。
- 系統參數設定(`app_settings`,即時派遣讀取;前端「參數設定」頁,未儲存提示)。

## 資料表(15)
vehicles / drivers / orders / users / address_point / address_alias / route_stop /
dispatch_history / dispatch_comparison / pool_projection / app_settings /
shift_pattern · shift_exception / unassigned_record / fixed_route /
driver_vehicle_assignment / push_subscription

## 實證效益(220 營運日、13,534 真實趟,納入司機實務約束)
- 集團用車 **↓18.6%**(7,328 → 5,967 車日);推共乘合計 **↓25.5%**。
- 年化省約 **NT$ 585 萬**(@NT$3,800/車日);共乘後合計約 NT$ 805 萬。

## 工程品質
- GitHub Actions CI:pytest(postgres) + 前端 build + Docker 映像,**綠燈**。
- 56 passed;`alembic check` 乾淨(防漂移閘門)。
- 全鏈時區一致 +08;機密只放 `.env`(gitignored)。

## 護城河 / 不做什麼
- **護城河**:台灣在地化(Map8 門牌、車種/福祉、長照平台格式)+ GCal 低摩擦採用。
- **刻意不做**:不自研派遣引擎(VROOM,需強度時換 Timefold,**非** PyVRP/PDPTW 不支援);
  不上重模型(TimesFM/類神經網路,實測基線更準);不導入過重依賴(MarkItDown/Docling)。

## 部署
- `docker compose up --build`;OSRM 一次性下載台灣 OSM。
- 正式上線待辦:多租戶隔離、個資合規(AI 文件地端抽取)、HTTPS/反向代理、各環境獨立 `.env`。
