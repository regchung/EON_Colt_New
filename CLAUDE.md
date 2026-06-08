# CLAUDE.md — SmartCar 專案記憶

給 Claude Code 的專案脈絡。**啟動時先讀本檔**,再看 [`README.md`](README.md) 取完整說明。

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
登入(JWT)、訂單/車輛/司機 CRUD、Excel/CSV 批次匯入(自動地理編碼)、
Map8 門牌級地理編碼 + 地址簿快取、VROOM 一鍵排班、自架 OSRM 矩陣、
動態重排(取消/開始/完成,鎖定進行中)、路線地圖(Map8 圖磚 + OSRM 路線)、
使用者管理、營運報表、GitHub Actions CI(後端 pytest + 前端 build + docker build,**綠燈**)。

migration 已到 `0006`;表:vehicles / drivers / orders / address_point / address_alias / route_stop / users。

---

## TODO / 下次啟動執行(待辦)

依優先序:

1. **🔴 安全(優先)**:撤銷曾在對話外露的 GitHub PAT,改用 `gh auth login`;
   視需要重新產生 Map8 金鑰並更新 `.env`。
2. **司機 App / 狀態回報**(下一個主功能):司機登入看當日路單(讀 `route_stop`)→
   回報到達/上車/完成 → 更新 `orders.status`(ongoing/done)→ 回饋動態重排。
   可先做精簡版(司機選自己車輛看路單 + 狀態按鈕),認證沿用 JWT。
3. **多角色權限**:目前單一管理員。加角色(admin / dispatcher / driver),
   在 `users` 加 `role`,後端依角色限制端點(司機只見自己路單)。
4. **地址正規化**:匯入流程串 Map8 `/address/standardization`(金鑰已含此 scope),
   清洗車行地址後再 geocode,提升命中率與一致性。
5. **報表強化**:加區間趨勢圖、匯出 CSV/Excel(下載走 axios blob)。
6. **排班進階**:重排時對 `ongoing` 訂單用 VROOM `steps` 強制鎖定在原車序列
   (目前是「排除不動」的簡化版)。
7. **時區**:目前上車時間以牆鐘存(顯示一致)。若要嚴格台灣 +08/UTC,統一處理匯入與顯示。
8. **正式部署**:改 `SECRET_KEY` 與管理員密碼、HTTPS/反向代理、各環境獨立 `.env`。

> 接續方式:挑上方一項 → 用 TaskCreate 建子任務 → 後端先做並用 pytest/驗證 →
> 前端做完 `--build frontend` 驗證 → commit + push(CI 需綠)。
