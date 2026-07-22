# 部署清單:上線到雲端 + 佈建歷史資料(第一家車隊 live)

> 目標:把現有單機 Docker 系統,安全地架到可連網址,**並把本機 143MB 真實歷史資料
> (orders/dispatch_history 各 42,910 筆、vehicles 59、drivers 52、address_point 3,379)
> 一起佈建上去**,讓第一家合作車隊一開機就看得到 220 天對比成果。
> 預設目標平台:**Railway**(亦適用任何「託管 Postgres + 兩個容器服務」的 PaaS)。
> 範圍:**單租戶**(一家車隊一套),多租戶/Docling 留到第二個付費客戶再做。

---

## 0) 上線前的關卡(GO / NO-GO)

| 關卡 | 條件 | 狀態 |
|---|---|---|
| **個資同意** | 真實 PII 上雲 = 需這家車隊的**書面/明確同意**(資料給他們自己 live 用)。確認資料處理範圍、保存期限。 | 🔲 你方確認 |
| **避免 PII 外送 Claude** | 第一階段**只用 Excel/CSV 批次匯入**(不經 Claude);停用「AI 文件匯入」按鈕或不教使用。 | 🔲 |
| **金鑰全換新** | SECRET_KEY、admin 密碼、Map8、(可選)Anthropic、VAPID 全部重產,只放雲端環境變數。 | 🔲 你方手動 |
| **區域** | Railway/DB 選**亞洲區**(降延遲、利於日後在地合規論述)。 | 🔲 |

> 任一未過 = 先別上 production。可先用**去識別化資料**佈一個 demo 環境驗證流程。

---

## 1) 程式面:production 硬化(我可代做)

現況是開發組態,上線前要調這幾項:

1. **關掉 dev 模式**:`backend/entrypoint.sh` 的 `uvicorn ... --reload` 改成由環境變數控制
   (prod 不用 reload,用 `--workers 2`)。
   ```bash
   # entrypoint.sh 結尾改為:
   if [ "$APP_ENV" = "production" ]; then
     exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
   else
     exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   fi
   ```
2. **不掛原始碼 volume**:`docker-compose.yml` 的 `./backend:/app` 是開發用;Railway 用 Dockerfile
   烘進映像,本就不吃這個 mount → 雲端 OK,僅本機開發保留。
3. **DB 不對外開埠**:prod 不要 publish 5432;只走服務內網。
4. **SQLAlchemy 連線字串**:Railway 給的是 `postgresql://...`,本專案需
   `postgresql+psycopg://...` → 部署時把 scheme 前綴補上(設 `DATABASE_URL` 時處理)。
5. **CORS**:`BACKEND_CORS_ORIGINS` 必須含前端 production 網址。
6. **前端 → 後端接線**:`frontend/nginx.conf` 目前硬寫 `http://backend:8000`(Docker 內網 DNS)。
   Railway 內網主機名不同(如 `backend.railway.internal:8000`)→ 需把 proxy 目標**參數化**
   (env 注入 nginx,或前端改用 `VITE_API_BASE` 直連後端公開網址)。**這是雲端最常卡的一步。**

## 2) OSRM 怎麼辦(影響路線品質)

OSRM 需台灣 OSM 前處理(GB 級),不適合塞進雲端建置。第一階段建議:
- **MATRIX_PROVIDER=map8**(你有 Map8 金鑰,直接用其矩陣)或 **haversine**(直線備援,先求能跑)。
- 路線品質要更準時,再把 OSRM 架到**獨立 VM + 持久磁碟**單獨服務,後端指向它。
- → 第一家上線**不必**為 OSRM 卡關。

---

## 3) 歷史資料佈建(你指定要做的重點)

本機 DB 143MB、schema 已在 **alembic 0023**。最穩做法 = **整庫 dump → 還原到雲端**
(含 schema + 資料 + `alembic_version`,還原後 prod 的 `alembic upgrade head` 自動成 no-op)。

### 3a. 本機匯出(custom format,壓縮、可平行還原)
```bash
cd /Users/ycchfx/AI實作/DrFish
docker compose exec -T db pg_dump -U dr_fish -d dr_fish \
  --no-owner --no-acl -Fc -f /tmp/dr_fish.dump
docker compose cp db:/tmp/dr_fish.dump ./dr_fish.dump   # 取到本機
# ⚠️ dr_fish.dump 含真實 PII:勿提交 git、勿放公開位置;傳輸用加密通道。
```

### 3b. 還原到雲端 DB
```bash
# PROD_URL = Railway 提供的連線字串(psql 格式,非 +psycopg)
pg_restore --no-owner --no-acl --clean --if-exists \
  -d "$PROD_URL" ./dr_fish.dump
```
- `--clean --if-exists`:還原前先丟舊物件,確保乾淨(對全新 DB 無影響)。
- 若 Railway 不給 superuser,改 `--no-comments` 並忽略擴充權限警告即可。

### 3c. 還原後驗證(數字要對得上本機)
```sql
select count(*) from orders;            -- 期望 42910
select count(*) from dispatch_history;  -- 期望 42910
select count(*) from address_point;     -- 期望 3379
select version_num from alembic_version;-- 期望 0023
```

### 3d. admin 帳號重建(重要)
本機 `users` 只有 1 筆(舊密碼)。**dump 會帶舊密碼雜湊** → 上雲後務必:
- 用新 `ADMIN_PASSWORD` 重設 admin(改 env 後跑一次重設,或 SQL 更新密碼雜湊),
  別讓 `admin/admin123` 暴露在公開網址。

---

## 4) 部署步驟(Railway)

1. 建 Railway 專案 → 加 **PostgreSQL** 外掛(取得 `DATABASE_URL`)。
2. 加 **backend 服務**(指向 repo `backend/` Dockerfile)→ 設環境變數:
   `DATABASE_URL`(補 `+psycopg`)、`SECRET_KEY`、`ADMIN_PASSWORD`、`MAP8_API_KEY`、
   `MATRIX_PROVIDER=map8`、`APP_ENV=production`、`BACKEND_CORS_ORIGINS=<前端網址>`。
3. 加 **frontend 服務**(指向 `frontend/` Dockerfile)→ 設 nginx proxy 目標為 backend 內網位址
   (見 §1.6)。
4. **先讓 backend 跑一次 migration**(entrypoint 會自動 `alembic upgrade head`,空庫建好 schema)。
5. **佈建歷史資料**:依 §3 把 dump 還原到 Railway Postgres(可在 migration 後直接覆蓋,
   `--clean` 會處理)。
6. 設定**自訂網域 + HTTPS**(Railway 自動簽憑證)。

> 金鑰輸入、帳號建立、網域綁定等 = **你在 Railway 介面手動操作**(我不經手任何密碼/金鑰)。

---

## 5) 上線後驗收(end-to-end)

1. `GET /api/health` → 200。
2. 用**新密碼**登入(確認 `admin123` 已失效)。
3. **派遣看板**選 2025 歷史日 → 看得到趟次(證明歷史資料佈建成功)。
4. **報表/對比頁** → 220 日對比、NT$ 數字顯示正常(你的銷售彈藥就緒)。
5. 用 Excel/CSV 匯入**一筆明天的測試單** → 一鍵排班 → 司機路單/口卡顯示。
6. 手機開前端 → RWD、司機 App「我的路單」可看。

---

## 6) 與夥伴車隊的 live runbook(跑通第一週)

| 日 | 動作 |
|---|---|
| D0 | 上線、驗收、給車隊管理者帳號(非 admin,用使用者管理開 dispatcher 角色) |
| D1 | 匯入他們**真實的明日單** → 一鍵排班 → 司機看口卡 → 收第一輪回饋 |
| D2-5 | 每日重複;記錄未派原因、人工微調(派遣看板拖放)、司機反映 |
| D7 | 攤開「這週自動 vs 你們原本人工」對比 → 談正式採用 / 收費 |

---

## 附:可還原 / 安全備註
- production 組態改動建議在分支進行,合併前 CI 綠。
- `dr_fish.dump`(含 PII)**永不進 git**;用後即刪本機暫存。
- 雲端環境變數只在平台後台設定,不寫進 repo;`.env.example` 只放空鍵示意。
- 第二個付費客戶出現前,不需多租戶;屆時再依 `eval-docling-tenancy-timefold.md` 上 RLS。
