# EON COLT 功能總覽(技術版)

> 取代人工派遣的**預約制長照接送車隊系統**。車行批次匯入預約單 → 地理編碼 →
> VROOM 自動排班(福祉車/共乘/時間窗)→ 地圖呈現 → 當天動態重排。**全套自架於 Docker**。
> 規模:18 路由模組 / 27 服務模組 / 19 資料表 / 20 前端頁 / migration 至 0028。

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
- **班表匯入**(`schedule_import`):人工派遣結果檔(民國日期、地址簿優先地理編碼、假單略過、取代當日)
  → 建 done 訂單 + SERVED 派遣歷史,供逐車對比/成效分析。
- **AI 文件智慧匯入**(`doc_ingest`):PDF/Word/Excel/CSV → Claude 抽單 → 建單。
- 個案標籤 `case_tag`(姓名+地址補充+醫療設施名稱),供固定行程匹配。

### 2. 地理編碼與地址簿
- DB 優先(`address_alias` → `address_point`),未命中才打 Map8 → 省費 + 加速。
- 多描述歸一門牌(別名);匯入時自動回填真實座標。

### 3. 智慧派遣(核心)
- **VROOM 一鍵排班**:每張單 = shipment(上車→下車配對)、2 維容量(座位 + 共乘同意佔位)、
  車種/輪椅技能、時間窗、車輛起訖點錨定。
- **司機營運規則**:8h 工時上限、06–18 服務時段、**完成緩衝**(時段內上車可延後完成)。
- **每趟工時歷史校準**(`calibration` + `fleet_calibration`):依**車行×福祉**從歷史「背靠背連續趟」
  反推每趟真實作業(全域一般 19.4/福祉 21.5 分),取代全域固定 40 分;樣本不足退全域;速度係數 ~1.0。
- **最長乘車時間上限**:下車窗 ≤ 上車窗末 + max(40分, 直達×1.8+30分),防共乘把乘客久載。
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
- **未派分析**(`unassigned_record`):依日歸類、**可行動原因**(時段外/無福祉車/無法路由/
  座標疑誤 suspect_geocode/全車隊滿載 fleet_saturated/求解邊際 solver_margin)、
  行控填回饋;**AI 改善建議**(`unassigned_insights`)聚合原因×回饋 → 規則建議 + Claude 白話方案。

### 9. AI 功能
- 調度助理(`assistant`):對話 + Claude tool-use,唯讀查真實資料給建議(注入台灣當日日期)。
- AI 文件匯入、未派改善方案(見上)。
- ⚠️ 個資合規:文件原文送 Claude,正式上線前評估地端抽取。

### 10. 報表與效益分析
- 營運報表 + CSV 匯出 + 區間趨勢圖(零依賴 SVG)。
- **派遣表 Excel 匯出**(`dispatch_export` + `/dispatch/export`):挑日期 + 車行 + 版型
  (單檔多分頁:總覽/各子車隊/每車排班/派車明細/未派 ‧ 或 每車一張工作表);報表頁操作。
- **人工 vs 自動對比**(`comparison`):省下車日 → NT$、時間窗敏感度。
- **逐車對比**(`compare_day_by_vehicle` + `VehicleComparison.vue`):某日某車行,同一組實體車牌
  左人工/右自動**並排**,標換車/換入、顯示**真實停靠序**(交錯上/下車 + 實際到點 + 在車人數)、
  駕駛+乘客名、每車總里程/工時。`/comparison/available-days` 供日期選單(不依賴批次)。
- PDF 報告產生器:技術版 / 管理版 / 營運分析(含尖峰壅塞情報)。

### 11. 系統管理
- 多角色(admin / dispatcher / driver)+ 使用者管理。
- 系統參數設定(`app_settings`,即時派遣讀取;前端「參數設定」頁,未儲存提示)。
  含 **`service_time_factor`(省車鬆緊主旋鈕,校準×係數)** 與固定行程全域參數。

### 12. 固定趟既定區塊(committed blocks)
- 固定趟(校車/日照/洗腎等)= 已談妥委派:`orders.occupancy_min` 有值即**釘指定車、整趟佔用時間計、
  各釘各車不互併**(原則9);正常單在其空檔最佳化。修掉「固定趟被當散單亂併」。
- 固定行程逐條維護參數(`fixed_route`:起迄/車牌/起始時段/佔用/乘客數/車型/輪椅/可併),
  缺項回退參數設定(`fixed_route_blocks.resolve_params`)。

## 資料表(19,migration 0028)
vehicles / drivers / orders / users / address_point / address_alias / route_stop /
dispatch_history / dispatch_comparison / pool_projection / app_settings /
shift_pattern · shift_exception / unassigned_record / fixed_route /
driver_vehicle_assignment / push_subscription / **fleet_calibration**(車行×福祉每趟工時+速度係數)

## 實證效益(563 車行-日、36,370 真實趟,工時校準 + 乘車上限後)
- 集團用車 **↓35.9%**(人工 7,371 → 自動 4,723 車日,省 2,648);563 天中 **511 更省/52 打平/0 落敗**。
- 年化省約 **NT$ 1,135 萬**(@NT$3,800/車日);未派 15(0.04%)。
- 詳見 `findings-calibration-2026-06-23.md`(此為工時校準後的真實值;舊 ↓18.7% 因固定 40 分工時高估,屬保守下限)。

## 工程品質
- GitHub Actions CI:pytest(postgres) + 前端 build + Docker 映像,**綠燈**。
- 82 passed;`alembic check` 乾淨(防漂移閘門)。
- 全鏈時區一致 +08;機密只放 `.env`(gitignored)。

## 護城河 / 不做什麼
- **護城河**:台灣在地化(Map8 門牌、車種/福祉、長照平台格式)+ GCal 低摩擦採用。
- **刻意不做**:不自研派遣引擎(VROOM;需強度時換 **OR-Tools / Timefold Java**——
  Timefold-Python 2025-10 已封存,**非** PyVRP/PDPTW 不支援;見 `eval-docling-tenancy-timefold.md`);
  不上重模型(TimesFM/類神經網路,實測基線更準);預設不導入過重依賴(MarkItDown 全否決)。
- **可選(預設關)**:Docling 本地文件抽取——僅在 `EXTRACTOR=docling` 時啟用,
  為「PII 不出機房」的合規需求而存在,未寫入 requirements;預設仍走輕量原生抽取。

## 部署
- `docker compose up --build`;OSRM 一次性下載台灣 OSM。
- 正式上線待辦:多租戶隔離、個資合規(AI 文件地端抽取)、HTTPS/反向代理、各環境獨立 `.env`。
