# DrFish 派遣 Demo

用 **VROOM** 求解一批預約訂單,展示三大約束:
- **福祉車 vs 一般車**(skills 單向相容路由)
- **共乘 / 包車**(capacity 座位容量)
- **預約時間窗**(time_windows)

## 檔案
| 檔案 | 說明 |
|------|------|
| `matrix-mode.json` | 情境資料:自帶行駛時間矩陣(秒),不需 OSRM/網路即可跑 |
| `solve.py` | **推薦**。用 pyvroom 直接求解並印出派遣結果 |
| `run.sh` | 用 Docker 跑 VROOM 官方 binary(需先啟動 Docker daemon) |

## 跑法 A:pyvroom(已驗證可跑,免 Docker)
```bash
python3 -m pip install pyvroom numpy pandas
python3 solve.py
```

## 跑法 B:Docker
```bash
# 需先啟動 Docker Desktop
./run.sh        # 結果寫入 solution.json
```

## 預期輸出
```
福祉車-001: depot → 訂單A上車(輪椅,1人) → 訂單A下車 → depot
一般車-001: depot → 訂單B上車(2人) → 訂單C上車(共乘,車上4人) → C下車 → B下車 → depot
未派遣訂單數: 0
```
重點:福祉車訂單 A **只**落在福祉車;一般單 B、C 在一般車上**共乘**(車上一度 4 人,吃滿 capacity);所有上車都壓在 09:00 預約時間窗內。

## 改成真實地址(接 OSRM)
`matrix-mode.json` 的 `matrices` 是手寫的。實務上拿掉它,改:
1. 自架 OSRM(載台灣 OSM 圖資)。
2. 把每個 pickup/dropoff 用經緯度 `location: [lng, lat]` 表示。
3. VROOM 會自動向 OSRM 查行車時間矩陣。
詳見 `../docs/architecture.md`。
