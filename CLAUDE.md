# CLAUDE.md — SmartCar 專案記憶

給 Claude Code 的專案脈絡。**啟動時先讀本檔**,再看 [`README.md`](README.md) 取完整說明。

## 🔔 啟動主動告知(下次開工先向使用者報這項待辦)
1. **徵詢成功率學習**:依路線/時段預測共乘徵詢成功率以排序撥打;**需先累積真實徵詢結果**
   (`pool-consent` 已留痕同意/撤回),資料夠了再做。
> 已完成:共乘增益已接進 PDF 報告與對比頁(`/dispatch/pool-gain` + `pool_projection` 表)。
> 詳見下方「TODO」對應條目。

## 專案是什麼
取代人工派遣的**預約制車隊系統**。車行批次匯入預約單 → 地理編碼 → VROOM 自動排班
(福祉車/共乘/時間窗)→ 地圖呈現路線 → 當天動態重排。全套自架於 Docker。

## 技術棧(實際,非規劃)
- 前端:Vue 3 + Vite + Bootstrap 5 + Pinia + Vue Router + MapLibre GL(`frontend/`)
- 後端:FastAPI + SQLAlchemy 2 + Alembic + Pydantic v2 + psycopg3(`backend/`)
- 派遣:VROOM(pyvroom 內嵌);矩陣:自架 OSRM;地理編碼:Map8(備援 Nominatim)
- DB:PostgreSQL 16;認證:JWT(HS256)+ PBKDF2(純標準庫,`backend/app/core/security.py`)
- 容器:`db` / `backend` / `frontend` / `osrm`(osrm 用 compose profile)

## 啟動 / 開發
```bash
docker compose up --build -d          # 起 db/backend/frontend(make up)
make osrm-prepare && make osrm-up      # 排班/地圖前必要(一次性下載台灣 OSM)
docker compose exec backend python -m pytest -q   # 後端測試
```
- 前端 http://localhost:8080;後端 http://localhost:8000/docs;登入 `admin` / `admin123`
- 後端程式以 volume 掛載 + `--reload`,改後端**不需重建**;改 migration/requirements 需重啟/重建
- **改前端必須** `docker compose up -d --build frontend`(靜態檔),再強制重新整理瀏覽器

## 重要慣例 / 踩過的雷(務必遵守)
1. **JWT 與下載**:受保護 API 的下載/匯出要用 axios(`responseType:'blob'`)帶 token,
   **不可用 `<a href>` 直連**(不會帶 token → 401)。見 `Orders.vue` 的 `downloadTemplate`。
2. **Bootstrap × Vue Router**:勿在 `<RouterLink>` 加 `data-bs-dismiss`(Bootstrap 會對該 `<a>`
   `preventDefault`,導致**點選單不換頁**)。關閉手機側欄改用路由監看 + `Offcanvas.getInstance().hide()`。
3. **機密**:`MAP8_API_KEY`/`SECRET_KEY`/密碼只放 `.env`(已 gitignore)。勿提交、勿寫進程式。
4. **jq 中文 key**:shell 用 jq 時 key 用英文,避免 quoting 錯誤。
5. **測試種子**:`backend/tests/conftest.py` 會在乾淨 DB 種子 admin(TestClient 不觸發 lifespan)。
6. **地址簿**:地理編碼先查 `address_alias`→`address_point`,未命中才打 Map8;多描述歸一門牌。

## 推送到 GitHub
Repo:https://github.com/regchung/SmartCar(remote `origin` 已設,乾淨 https URL)。
**建議用 `gh auth login`(web)**,之後 `git add -A && git commit && git push` 即可。
切勿把 PAT 寫進指令/設定或提交。提交訊息結尾附:
`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

## 目前狀態(已完成)
登入(JWT)+ **多角色**(admin/dispatcher/driver)、訂單/車輛/司機 CRUD、
Excel/CSV/PDF 批次匯入(SSE 進度 + 自動地理編碼)、Map8 門牌級地理編碼 + **地址正規化** + 地址簿快取、
VROOM 一鍵排班、自架 OSRM 矩陣、動態重排(取消/開始/完成,鎖定進行中)、
路線地圖(Map8 圖磚 + OSRM 路線)、**司機 App(我的路單)**、使用者管理、
營運報表 + **CSV 匯出**、**AI 派遣分析/插單(Claude,需金鑰)**、
**區域親和建議(zone-suggest + 前端採用/手動指派)**、GitHub Actions CI(pytest + build + docker,**綠燈**)。
**長照派遣歷史匯入(`/history/import`,去識別化、自建車/司機、灌地址簿座標)**、
**車行標記(集團統一派遣:orders/dispatch_history.fleet + vehicles/drivers.home_fleet)**、
**人工 vs 自動對比引擎(`comparison.py` + `/dispatch/comparison` + 前端頁)**、
**PDF 對比報告產生器(`scripts/make_report.py`)**、
**車隊名冊匯入(`fleet_import.py` + `/fleet/import`,回填真實座位/福祉/出車起點·收車終點)**、
**車輛出車起點(start)/收車終點(end)欄位 + VROOM 首末站錨定**、
**司機營運規則建模(前後40分/趟、8h工時上限、06-18服務時段、共乘需同意)+ 上車時間 +08 時區修正**、
**共乘推薦 P1+P2+P3(`pool_suggest.py` + `/dispatch/pool-suggest` + 前端「共乘建議」頁;
`/dispatch/pool-consent` 同意捕捉+留痕、一鍵「標記同意並重算」;
`recurring_pairs.py` + `/dispatch/pool-recurring` 常態共乘對挖掘:57 組反覆同行 ≥3 日,適合徵長期同意;
**共乘增益接進報表/對比頁**:`/dispatch/pool-gain` + `pool_projection` 表,實測共乘後 vs 人工總節省 ↓26%)**、
**常客固定駕駛建議(`driver_affinity.py` + `/dispatch/driver-suggest` · `driver-loyalty`,弱訊號→僅高信心建議)**、
**系統參數設定(`app_settings` + `settings.py` + `/settings` CRUD 限 admin + 前端「參數設定」頁;
即時派遣讀取營運參數,回測沿用固定方法學)**、
**班表(`shift_pattern` 週期 + `shift_exception` 例外 + `roster.py` + `/roster/*` + 前端「班表」頁;
可從歷史回推 179 筆/33 車;即時派遣只納入當日出勤車,無班表資料保守視為不出勤)**、
**輕量需求預測(`forecast.py` + `/dispatch/demand-forecast`;weekday 季節基線 → 各日趟次/建議排車數,
接進班表頁「需求預測」卡;刻意不引入 TimesFM 等重模型,見待辦)**。

近期新增(本批 10 項,全數入庫綠燈、測試 50 passed):
**對比進階**:`/dispatch/comparison/savings`(省下車日→NT$:集團實測 ↘536 車日≈NT$134萬、年化≈NT$298萬)
+ `/comparison/sensitivity`(時間窗 15/45/60 分敏感度);成本參數入設定「成本」群組。
**班表一鍵套用建議排車數**(`roster.apply_forecast` + `/roster/apply-forecast`,依預測挑該車行歷史最常出勤前 N 台)、
**班別時段細緻化**(每車 `shift_start/end` 輸入,dispatcher 以此為車輛 time_window)、
**報表區間趨勢圖**(零依賴 `components/TrendChart.vue`,總數/已派/未派 + 派遣率趨勢)、
**排班 ongoing 硬鎖原車**(用唯一技能 `LOCK_SKILL_BASE+vid` 鎖定,delivery-only Job;實測 VROOM `steps` 非硬約束故改用 skills)、
**AI 文件智慧匯入**(`doc_ingest.py` + `POST /orders/import-doc`:PDF/Word/Excel/CSV → Claude 抽單 → 建單+地理編碼;不用 MarkItDown;⚠️個資外送,合規見待辦)、
**調度員 AI 助理 v1**(`assistant.py` + `POST /dispatch/assistant`:對話 + Claude tool-use,4 唯讀工具查真實資料給建議;前端「💬 AI 助理」頁)、
**時區全鏈一致 +08**(寫入統一 +08[importer/驗證器/history];`db/session.py` 設 `timezone=Asia/Taipei` → DB 讀回帶 +08,API/報表/路單/前端顯示一次全對)。

近期新增(營運導向一批,皆入庫綠燈、50 passed):
**車輛任務口卡**(`/dispatch/daily-tasks` + `/meta`,依車行→每車→時間;前端「🪪 車輛任務口卡」可列印)、
**未派分析 + 行控回饋**(`unassigned_record` 表[0017];`compare_day` 吐未派明細+推斷原因[服務時段外/無福祉車/無法路由/滿載],`run_batch` 寫入並關聯人工車;`/dispatch/unassigned/*`;前端「⚠️ 未派分析」)、
**未派回饋學習建議**(`unassigned_insights.py` + `/dispatch/unassigned/insights`:原因×回饋聚合→規則建議+Claude 白話改善方案)、
**固定行程指定司機**(`fixed_route` 表[0018]+`match_name`[0021];`fixed_route_match.py` 地點/姓名匹配+時段分流;CRUD + `/fixed-routes/match`;dispatcher 以 `PIN_SKILL_BASE+vid` 硬綁指定車;前端「📌 固定行程」)、
**司機↔車地基**(`driver_resolve.py`;`/driver-vehicle` 司機車輛對應+補無車司機;`driver_vehicle_assignment`[0019]當日輪車;前端「🚗 司機車輛」)、
**自然語言出勤解析**(`attendance_parse.py` + `/roster/parse-attendance`·`apply-attendance`:貼出勤文字→Claude 解析→班表例外;前端班表頁「🗣️ 貼上出勤異動」)、
**訂單個案標籤**(`orders.case_tag`[0020]:匯入存乘客姓名+地址補充+醫療設施名稱,供固定行程匹配)、
**拖放派遣看板**(`dispatch_board.py` + `/dispatch/board`;`/orders/{id}/unassign`;前端「🧲 派遣看板」原生拖放+時間衝突標紅)。

migration 已到 `0021`;表:vehicles / drivers / orders / address_point / address_alias / route_stop / users
／**dispatch_history**／**dispatch_comparison**／**pool_projection**／**app_settings**／**shift_pattern**·**shift_exception**
／**unassigned_record**(未派+行控回饋)／**fixed_route**(固定行程指定司機)／**driver_vehicle_assignment**(當日輪車)。
vehicles 新增 `start_lng/lat`·`end_lng/lat`;orders 新增 `pool_consent_at`/`pool_consent_by`、`case_tag`(個案/地標標籤)。
規劃文件見 `docs/self-build-roadmap.md`、`docs/data-overview-and-optimization.md`。

> 對比成果(220 營運日、13,534 趟真實單,**已納入司機實務約束**:前後40分/趟、8h工時、
> 06-18 服務時段、共乘需同意 + 真實座位 + 起訖點 + 時區修正):
> 集團用車 2,920→**2,384** 車日(**↓18.4%**,保守且貼近實務),183/220 天自動更省,
> 未排入約 652 趟(4.8%,多為 06-18 之外的清晨/深夜歷史趟次)。
> (演進:預設座位/自由共乘/無工時約束時為 ↓47–51%,屬理論上限。)
> 資料現況為**乾淨真實歷史**(4 車行、~2 萬筆;測試資料已清),可重匯(Downloads 的 4 個 .xls
> + 車隊名冊 `長照司機工作資料管理.xls`)。

---

## TODO / 下次啟動執行(待辦)

### 🟢 進行中 / 待辦(依優先序)

1. **🔴 安全(優先)**:撤銷曾在對話外露的 GitHub PAT,改用 `gh auth login`;
   視需要重新產生 Map8 金鑰並更新 `.env`。(本機帳號操作,需使用者手動)
2. **🟠 區域親和接進批次排班**:把區域親和當 **VROOM 軟性偏好**接進 `dispatcher.py`,搭對比量測再開大。
   護欄不變:時間窗/車種/座位/每區上限為硬約束。(實測駕駛熟區訊號偏弱 11–21%,權重要保守,建議緩)
3. **🟠 需求預測進階**:weekday 基線 + ①一鍵套用建議排車數 已上線(見已完成)。後續可:
   ② 待累積 1–2 年、要做細粒度多序列(區×時段×車種)時再評估基礎模型。
   **TimesFM 等基礎模型暫不導入**:預約制需求已知、資料短小、主訊號為週循環,輕量基線即足;
   條件(長歷史 + 多序列 + 基線實測不足 + 願擔推論基建)達成再評估,避免違背「精簡」策略。
4. **🟠 調度員 AI 助理 → 受控寫入**:助理 v1(唯讀建議,Claude tool-use)已上線(見里程碑)。
   後續加「建議→確認→寫入」受控工具(run_dispatch/assign),需 tool-use 多輪確認 + 前端確認 UI(待金鑰可實測再做)。
   (文件智慧匯入已完成,見里程碑。)
5. **測試**:已補 `settings`/`roster`/`zone_affinity`/`assign`/時區/`doc_ingest`/`assistant` 的 pytest(見已完成,50 passed)。
   `pool_suggest`/`comparison`/`dispatcher`(含 ongoing 鎖定)求解測試待補——需 CI 內備 OSRM 矩陣(目前 CI 無 OSRM,故僅測純函式)。
6. **正式部署**:改 `SECRET_KEY` 與管理員密碼、HTTPS/反向代理、各環境獨立 `.env`、多租戶隔離、個資合規
   (含 AI 文件匯入個資外送 → 評估地端抽取)。
7. **🟡 待決策議題(經營取捨)**:見 `docs/open-decisions.md`。
   - **D1 上車窗 30→45/60**:全年實測 45 分 +NT$151 萬/年、未派 12→2;60 分再 +134 萬。
     待車隊就「乘客最晚到場 = 預約 +45/+60 分」的政策拍板,再改 `pickup_window_min`。
     (附帶實證:工時上限 8h **非瓶頸**、前後置 40 分合理偏保守,皆維持。)

> ⏸ **徵詢成功率學習**(見上方「🔔 啟動主動告知」):等 `pool-consent` 累積真實徵詢結果後再做。

### ✅ 已完成里程碑(近→遠)
- **時區收尾(全鏈一致 +08)**:修正三個寫入路徑一律存台灣時間——`importer.py`(車行批次,原誤標 UTC→改 +08)、`OrderBase.pickup_time` 驗證器(手動建單 / AI 文件匯入的 naive datetime→補 +08)、`history_import` 本即 +08。**根因 #2**:DB(timestamptz)讀回預設 UTC,使 OrderOut 序列化 / `strftime` / 前端 `slice(11,16)` 全顯示成 UTC(差 8h);於 `db/session.py` 設連線 `timezone=Asia/Taipei`,讀回一律 +08 → API/報表/司機路單/geojson/前端顯示一次全對(計算用 `astimezone(TW)` 為瞬間保持、不受影響)。pytest +4。
- **調度員 AI 助理 v1(唯讀)**:`assistant.py` — 對話式 + Claude **tool-use** 迴圈,4 個唯讀工具(`query_orders`/`dispatch_overview`/`vehicles_on_duty`/`demand_forecast`)以真實資料為依據回答調度問題並給建議(不直接寫入,排班仍用既有按鈕);`POST /dispatch/assistant`(無金鑰優雅降級回提示);前端「💬 AI 助理」對話頁(多輪上下文 + 查了哪些資料明細 + 範例問題)。pytest +6。
- **AI 文件智慧匯入**:`doc_ingest.py`(輕量抽取 PDF=pypdf / Word=python-docx / Excel=openpyxl·xlrd / CSV·文字)→ Claude 抽結構化訂單(`ai_dispatch._call_claude` 加 `max_tokens`)→ 正規化建單 + 自動地理編碼;`POST /orders/import-doc`(無金鑰回 400);Orders 頁「🤖 AI 文件匯入」鈕 + 預覽表 + 錯誤明細。**刻意不引入 MarkItDown**(其 magika+onnxruntime 過重,違背精簡)。⚠️ 個資:文件原文會送 Claude,真實 PII 上線前應改地端抽取(列入正式部署合規)。pytest +5(extract_text/strip_json/coerce)。
- **排班進階:ongoing 鎖定原車**:重排(`dispatcher.run_dispatch`)現納入進行中(`ongoing`)訂單,以**唯一技能**(`LOCK_SKILL_BASE+vid`)硬鎖在原指派車——實測 VROOM `steps` 非硬約束(會被重排/搬走),改用 skills 才能真鎖。ongoing 模型為 **delivery-only Job**(乘客已上車、初始載重佔位到下車,不重排上車);其車輛即使班表未涵蓋也強制納入;寫回保持 `status=ongoing`、更新 ETA 與路線。實測:下車點靠近他車仍鎖原車、pending 同時正常排入。(近似:車輛起點仍用設定起點,真實當前位置待司機端 GPS 回報。)
- **報表區間趨勢圖**:零依賴 `components/TrendChart.vue`(多序列 SVG 折線 + 格線 + x 標籤抽樣 + hover tooltip + 圖例);報表頁加「區間營運趨勢」(總數/已派/未派)與「每日派遣率趨勢」,資料源用既有 `/reports/overview` 的 `by_day`(無新後端)。
- **班別時段細緻化**:`/roster/patterns` 回傳每車班別 `shift_start/end`;班表頁週期班表每車加「起/迄」時間輸入(套用所有上班日,留空=06–18 預設)。即時派遣(`dispatcher`)已將班別時段作為車輛 `time_window`(`win=max(day_start,rs)…min(day_end,re)`),設定即生效。
- **服務層測試擴充**:`tests/test_services.py`(純函式:`settings._coerce`/預設完整性、`roster._secs`、`comparison._secs_tw` 鎖定 +08 時區 bug、`zone_affinity._vehicle_feasible`、`forecast.WD_NAMES`)+ `tests/test_endpoints.py`(settings/roster 授權、`apply-forecast` dry-run、手動指派生命週期含清理)。共 **36 passed**。pytest 在 `requirements-dev.txt`(CI 已裝;本機執行容器需 `pip install -r requirements-dev.txt` 後再跑)。
- **班表一鍵套用建議排車數**:`roster.apply_forecast()` + `/roster/apply-forecast`(dry_run 預覽/寫入);依需求預測各 weekday 建議數,挑該車行歷史最常出勤前 N 台覆寫週期班表,缺口顯示提示。班表頁「需求預測」卡加「套用建議到班表」鈕 + 實派列。(發現:新北建議 17/日但歷史僅湊 ~11-12 台,缺口可手動補。)
- **對比進階(成本效益 + 時間窗敏感度)**:`comparison.sensitivity()` + `/dispatch/comparison/savings`·`/comparison/sensitivity` + 對比頁「💰 成本效益(省下車日→NT$)」「⏱️ 時間窗敏感度」卡;成本參數(`cost_per_vehicle_day`/`annual_service_days`)入參數設定「成本」群組。集團實測省 **536 車日 ≈ NT$134萬**(135 日)、**年化 ≈ NT$298萬**(@NT$2,500/車日);敏感度:上車窗 15→60 分,省車率 10%→27.5%,未派趟次不變(多為服務時段外)。
- **輕量需求預測**:`forecast.py` + `/dispatch/demand-forecast`(weekday 季節基線:各日趟次/建議排車數)+ 班表頁「需求預測」卡。刻意不用 TimesFM(評估後:本專案效益低)。
- **班表(出勤)**:週期 `shift_pattern` + 單日 `shift_exception` + `roster.py` + `/roster/*` + 前端「班表」頁;即時派遣只用當日出勤車(無資料保守視為不出勤),可從歷史回推。
- **系統參數設定**:`app_settings` + `settings.py` + `/settings` CRUD(限 admin)+ 前端「參數設定」頁;即時派遣讀營運參數,回測沿用固定方法學。
- **常客固定駕駛建議**:`driver_affinity.py` + `/dispatch/driver-suggest`·`driver-loyalty`(弱訊號→僅高信心建議,不接硬排)。
- **共乘推薦 P1+P2+P3 + 共乘增益**:`pool_suggest.py`/`recurring_pairs.py` + `/dispatch/pool-suggest`·`pool-consent`·`pool-recurring`·`pool-gain` + `pool_projection` 表 + 前端「共乘建議」頁 + 對比頁「共乘增益」卡 + PDF 一節(↓18.4%→↓26%)。
- **司機營運規則 + 時區修正**:前後40分/趟、8h工時、06-18時段、共乘需同意 + 上車時間 +08;對比降至 **↓18.4%**(實務值)。
- **車隊名冊匯入 + 出車起點/收車終點**:`fleet_import.py` + `/fleet/import` + VROOM 首末站錨定。
- **人工 vs 自動對比引擎 + PDF 報告**:`comparison.py` + `/dispatch/comparison*` + 前端對比頁 + `scripts/make_report.py`。

> 接續方式:挑上方一項 → 用 TaskCreate 建子任務 → 後端先做並用 pytest/驗證 →
> 前端做完 `--build frontend` 驗證 → commit + push(CI 需綠)。
