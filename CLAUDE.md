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
**共乘增益接進報表/對比頁**:`/dispatch/pool-gain` + `pool_projection` 表,實測共乘後 vs 人工總節省 ↓26%)**。

migration 已到 `0014`;表:vehicles / drivers / orders / address_point / address_alias / route_stop / users
／**dispatch_history**（人工派遣結果）／**dispatch_comparison**（逐日對比結果）／**pool_projection**（共乘增益投影）。
vehicles 新增 `start_lng/lat`(出車起點)、`end_lng/lat`(收車終點);
orders 新增 `pool_consent_at`/`pool_consent_by`(共乘同意留痕)。
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

依優先序:

1. **🔴 安全(優先)**:撤銷曾在對話外露的 GitHub PAT,改用 `gh auth login`;
   視需要重新產生 Map8 金鑰並更新 `.env`。
2. **✅ 共乘增益接進報表/前端(已完成)**:`/dispatch/pool-gain` + `pool_projection` 表,
   對比頁新增「共乘增益」卡、PDF 報告新增「六、共乘增益」一節(18.4%→26%、134 組/57 常態對)。
3. **🔔 徵詢成功率學習(下次啟動主動告知)**:依路線/時段預測共乘徵詢成功率以排序撥打;
   **需先累積真實徵詢結果**(`pool-consent` 已留痕同意/撤回),資料夠了再做。
4. **✅ 常客固定駕駛規則(已完成,保守版)**:`driver_affinity.py` + `/dispatch/driver-suggest?passenger=`
   + `/dispatch/driver-loyalty`。**實測全域訊號偏弱**(688 常客最常司機占比中位 ~27%,僅 7%/46 位 ≥50%),
   故僅作高信心建議供人工指派參考,**未接進批次硬排**(同 zone-affinity 弱訊號處理)。
5. **🟠 區域親和接進批次排班**:把區域親和當 **VROOM 軟性偏好**接進 `dispatcher.py`,搭對比量測再開大。
   護欄不變:時間窗/車種/座位/每區上限為硬約束。(實測駕駛熟區訊號偏弱 11–21%,權重要保守)
6. **🟠 對比進階**:時間窗敏感度分析、把省下車日換算成 NT$(對車隊報價用)。
7. **🟠 roadmap 其他自建項**(見 `docs/self-build-roadmap.md`):
   - **文件智慧匯入**:`MarkItDown` 轉文字 → Claude 抽取結構化訂單 → 接現有匯入(PDF/Word/怪 Excel)。新增 `doc_ingest.py` + `POST /orders/import-doc`。
   - **調度員 AI 助理**:擴充 `ai_dispatch.py` 為對話 + Claude tool-use(查單/試算/排班),建議→確認→寫入。
8. **排班進階**:重排時對 `ongoing` 訂單用 VROOM `steps` 強制鎖定在原車序列(目前是「排除不動」簡化版)。
9. **報表趨勢圖**:CSV 匯出已完成;再加區間趨勢圖。
10. **測試**:補 `zone_affinity` / `pool_suggest` / assign 的 pytest,讓 CI 守得更穩。
11. **時區收尾**:派遣/對比已修(+08);尚待前端顯示與報表全鏈盤點(確保各處一致)。
12. **正式部署**:改 `SECRET_KEY` 與管理員密碼、HTTPS/反向代理、各環境獨立 `.env`、多租戶隔離、個資合規。

> 近期已完成:對比調參再跑(↓18.4% 實務值)、上車時間 +08 時區修正、共乘推薦 P1+P2+P3。

> 接續方式:挑上方一項 → 用 TaskCreate 建子任務 → 後端先做並用 pytest/驗證 →
> 前端做完 `--build frontend` 驗證 → commit + push(CI 需綠)。
