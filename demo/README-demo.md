# 單機展示包 — 給車隊業主看的 Demo

把整套系統(含**真實歷史資料**)搬到另一台機器,一鍵啟動展示。
適用情境:展示機 = 另一台電腦、現場**有網路**。

---

## 一、來源機(你現在這台,有真實資料)— 做一次

```bash
bash demo/make-demo-data.sh     # 匯出整庫 → demo/smartcar.dump(含真實 PII)
bash demo/package-demo.sh       # 打包 → demo/smartcar-demo-bundle.zip(已排除大檔)
```
把 `smartcar-demo-bundle.zip` 用**加密隨身碟**拷到展示機(內含真實個資,勿走公開雲端)。

## 二、展示機 — 前置(一次)
- 安裝 **Docker Desktop**(macOS / Windows 皆可)並啟動。
- 解壓 `smartcar-demo-bundle.zip`。

## 三、展示機 — 啟動
```bash
cd <解壓後的專案資料夾>
bash demo/start-demo.sh         # 自動:套環境 → 起 db → 還原資料 → 起前後端 → 設展示密碼
```
首次建置約數分鐘。完成後開瀏覽器:
- 前端:**http://localhost:8080**
- 登入:**admin / demo2026**

關閉:`bash demo/stop-demo.sh`(保留資料);徹底重置:`bash demo/stop-demo.sh --wipe`。

---

## 四、建議展示動線(7–10 分鐘,先講結論再看細節)

1. **派遣看板**(選一個 2025 歷史日)— 一眼看到「每台車當天實際派遣」,證明用的是他自己的真實營運。
2. **營運報表 / 人工 vs 自動對比** — 主打數字:
   > 220 營運日、13,534 趟 → 集團用車 **2,920 → 2,384 車日(↓18.4%)**,
   > 省 **536 車日 ≈ NT$134 萬(135 日)**、**年化 ≈ NT$298 萬**。
   強調:已納入司機實務約束(前後 40 分、8h 工時、06–18 時段、共乘需同意、真實座位)——**保守、貼近實務**。
3. **車輛任務口卡** — 「司機拿到的就是這張」,可列印,落地感強。
4. **一鍵排班(現場 live)** — 匯入一筆明日測試單 → 按排班 → 看它自動排進某台車。
5. (有 Map8 金鑰時)**路線地圖** — 視覺化路線,加分。

## 五、現場有網路時的加值(選配)
編輯專案根目錄 `.env` 後 `bash demo/stop-demo.sh && bash demo/start-demo.sh` 重啟:
- 填 `MAP8_API_KEY=` → 啟用**路線地圖底圖** + 門牌級地理編碼;並可把 `MATRIX_PROVIDER=map8` 得真實道路矩陣。
- 填 `ANTHROPIC_API_KEY=` → 展示 **AI 助理 / 文件匯入**。
> 不填也能完整展示「看板 / 對比 / 口卡 / 排班」——這些不依賴外部金鑰。

## 六、注意事項
- `demo2026` 與 `demo-only-secret...` 僅供展示;真正上線務必換強密碼/金鑰(見 `docs/deploy-railway-checklist.md`)。
- `demo/smartcar.dump` 與 bundle zip **含真實 PII**:已 gitignore,勿提交;展示結束請從展示機刪除。
- 展示版用 haversine 直線矩陣(免金鑰、離線可跑);路線時間為近似值,對「省幾台車」的結論無影響(對比方法學固定)。
