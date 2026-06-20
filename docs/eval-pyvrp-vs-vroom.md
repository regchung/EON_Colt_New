# 評估:PyVRP 是否可取代 / 補強 VROOM(派遣引擎)

> 結論先講:**NO-GO（不採用)**。PyVRP 不支援我們問題的核心結構「配對接送(PDPTW / shipment)」,
> 無法作為 VROOM 的替代。VROOM 的 shipment 模型正好貼合長照接送,維持現狀。
> 評估日期:2026-06。評估版本:PyVRP 0.13.4。

## 背景與動機
GitHub 探勘時 `PyVRP/PyVRP`（648★、純 Python、state-of-the-art HGS）看似理想:
內嵌式(同 pyvroom 不需另起服務)、品質頂尖。符合「引擎不自研、需要強度時換」策略,
故做一次評估「能不能換成更強的 PyVRP」。

## 我們的問題型態:PDPTW(配對接送)
長照每一張訂單 = **乘客在 A 上車 → 必須由同一台車送到 B 下車,且 A 在 B 之前**。
這是典型的 **Pickup-and-Delivery Problem with Time Windows (PDPTW)**。
現行 `dispatcher.py` 用 VROOM 的 **`add_shipment(pickup_step, delivery_step)`** 原生表達(一級支援):

```
backend/app/services/dispatcher.py:217  pickup   = vroom.ShipmentStep(...)
backend/app/services/dispatcher.py:221  delivery = vroom.ShipmentStep(...)
backend/app/services/dispatcher.py:227  problem.add_shipment(pickup, delivery, ...)
```

## 關鍵發現:PyVRP 0.13.4 不支援配對接送
檢視實際安裝的 PyVRP 原始碼與 API:

| 能力 | PyVRP `Model` | 結論 |
|---|---|---|
| `add_client(delivery=, pickup=)` | 只表示「在**該點**裝/卸多少貨」 | ❌ 不是 A→B 配對 |
| `add_client_group` | docstring 明載「Only **mutually exclusive** groups」 | ❌ 互斥,非配對 |
| `precedence`（Model.py 出現) | 僅指 edge 覆寫優先序(profile-specific edge) | ❌ 與上下車先後無關 |
| 原始碼搜尋 `PDPTW / pickup-and-delivery / pair precedence` | 無對應實作 | ❌ |

PyVRP 擅長 **CVRP / VRPTW / 集貨-配送(單點裝卸)/ prize-collecting / 多場站**,
但**沒有把「上車點—下車點」綁成同一趟、同一車、有先後**的一級機制。
要硬做只能降階成「點訪問」,會喪失接送的正確性(乘客可能被拆到不同車)。

## 為什麼這是 NO-GO(而非「再調一下」)
- 改用 PyVRP = 要嘛放棄配對(domain 不可接受),要嘛在底層 `ProblemData` 自建約束,
  但 PyVRP 求解核心本身不含 PD 配對/先後約束,等同自研引擎 —— 違背「引擎不自研」。
- VROOM 的 shipment 對我們是**剛好對位**的模型;換到一個要繞過其設計的引擎,
  風險與工時都遠大於可能的解品質增益。

## 建議
1. **維持 VROOM(pyvroom)** 作為派遣引擎。
2. 若未來真的撞到 VROOM 解品質/規模天花板,優先評估**同樣原生支援 PDPTW** 的引擎
   (如 Timefold/OR-Tools 的 PDPTW 範式),而非 PyVRP。
3. PyVRP 可留作「純集貨型」子問題的參考(例:多起點→單一目的地的接送,本質是 CVRP),
   但不值得為此維護第二套引擎。

## 附:本次評估如何做到「可還原」
- 於 `experiment/pyvrp-vs-vroom` 分支進行;PyVRP 僅在容器一次性 `pip install`,
  **未寫入 requirements.txt**,重建即消失,主程式零改動。
- 還原點:`git tag restore/baseline`(評估前乾淨狀態)。
