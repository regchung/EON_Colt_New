# DrFish 文件索引

專案文件總覽。**新進者建議閱讀順序**:`architecture.md` → `feature-overview.md` →
`dispatch-principles.md` → `findings-calibration-2026-06-23.md`。
專案脈絡與啟動提醒見根目錄 `../CLAUDE.md`;完整說明見 `../README.md`。

狀態圖例:🟢 現行 ·  📌 設計基準 ·  🧪 評估快照(決策參考) ·  ⚠️ 已被取代(保留歷史)

---

## 架構與設計(基礎)
| 文件 | 說明 | 狀態 |
|---|---|---|
| `architecture.md` | 系統架構與技術選型(全棧、容器、資料流) | 📌 |
| `feature-overview.md` | 功能總覽(技術版):11 模組 + 16 資料表 + 實證效益 | 🟢 現行功能清單 |
| `batch-import.md` | 車行批次訂單匯入設計 | 📌 |
| `data-overview-and-optimization.md` | 資料總覽與優化建議 | 📌 |

## 派遣原則與成效(核心)
| 文件 | 說明 | 狀態 |
|---|---|---|
| `dispatch-principles.md` | **派遣原則 1–9**(固定趟/同區/福祉/出勤緩衝/有司機才派/乘車上限/工時校準/**既定區塊**)+ 省車旋鈕 | 🟢 權威 |
| `findings-calibration-2026-06-23.md` | **發現報告**:工時校準將省車率 ↓18.7%→↓35.9%(全量 563 車行-日) | 🟢 最新效益權威 |
| `findings-fixed-route-2026-06-23.md` | **發現報告**:固定趟既定區塊模型(客戶回饋→方案→驗證:校車亂併 17→10 vs 既定區塊 17→16) | 🟢 |
| `findings-chaining-2026-07-04.md` | **發現報告**:歷史反推調度員接續規則(就近串趟2.7km/40–80分節奏/幾乎不共乘/往返占62%停留143分/回程58%換車;都會vs神同行兩模式) | 🟢 |
| `evaluation-2026-06-24.md` | **評估報告**:固定趟全做後(佔用時間/各釘各車/可接散單;6/24 即時 248/248、客戶3點達成、省車率轉盤) | 🟢 最新 |
| `effectiveness-2026-06-22.md` | 成效分析(↓18.7% 舊基準) | ⚠️ 已被上方取代 |
| `open-decisions.md` | 待決策議題(上車窗 30→45/60 等營運參數) | 🟢 |

## 功能子系統實作
| 文件 | 說明 | 狀態 |
|---|---|---|
| `fixed-route-blocks-phase1.md` | 固定行程「既定骨架 + 衝突偵測」階段一 | 🟢 |
| `dispatch-report-2026-06-24.md` | **範例**派遣報告(6/24:248 單→35 車、246 派;含每車排班/未派分析)。僅司機/代碼,無乘客 PII | 🟢 範例 |

## 評估(技術選型快照,供決策)
| 文件 | 說明 | 狀態 |
|---|---|---|
| `eval-pyvrp-vs-vroom.md` | PyVRP 是否取代/補強 VROOM | 🧪 |
| `eval-docling-tenancy-timefold.md` | 地端文件抽取 / 多租戶 / 引擎升級 | 🧪 |
| `eval-routing-valhalla-routingpy.md` | 時段相依路由是否導入 | 🧪 |
| `research-domains.md` | 可協助本專案的學術領域對應 | 🧪 |

## 規劃 / 部署 / 工程
| 文件 | 說明 | 狀態 |
|---|---|---|
| `self-build-roadmap.md` | 自建功能規劃(調度智慧化) | 🟢 |
| `deploy-railway-checklist.md` | 上線部署 + 歷史資料佈建清單 | 🟢 |
| `engineering-review.md` | 軟體工程檢視 | 🧪 |

---

## 注意:不入庫的產物
- `../reports/`(gitignore):**每日派遣報告**等含真實乘客姓名(個資),不進版控。
- 機密(`MAP8_API_KEY`/`SECRET_KEY`/密碼)只放 `../.env`(gitignore),repo 僅追蹤 `.env.example`。

## 維護慣例
- 數字有重大變動的文件(效益/原則),於頂部加「已被取代,見 X」註記而非直接刪除,保留決策軌跡。
- 新增重大功能或變更原則時:更新 `feature-overview.md` + `dispatch-principles.md` + `../CLAUDE.md` 頭條,
  必要時寫一份 `findings-*.md` 發現報告。
