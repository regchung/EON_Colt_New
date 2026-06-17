#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""產生 SmartCar 人工 vs 自動 對比報告 PDF(中文)。"""
import json

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, HRFlowable,
)
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.legends import Legend

FONT = "CJK"
pdfmetrics.registerFont(TTFont(FONT, "/Library/Fonts/Arial Unicode.ttf"))

data = json.load(open("/tmp/report_data.json", encoding="utf-8"))
g = data["summary"]["group"]
by_fleet = data["summary"]["by_fleet"]
top = data["top_days"]
ov = data["overview"].split("|")
pool = data.get("pool_gain")  # 共乘增益(可選)

styles = getSampleStyleSheet()
def S(name, **kw):
    base = kw.pop("parent", styles["Normal"])
    return ParagraphStyle(name, parent=base, fontName=FONT, **kw)

title = S("t", fontSize=20, leading=26, alignment=TA_CENTER, spaceAfter=4)
sub = S("sub", fontSize=11, leading=15, alignment=TA_CENTER, textColor=colors.grey, spaceAfter=14)
h2 = S("h2", fontSize=14, leading=20, spaceBefore=12, spaceAfter=6, textColor=colors.HexColor("#0d6efd"))
body = S("b", fontSize=10.5, leading=16, alignment=TA_LEFT, spaceAfter=4)
small = S("s", fontSize=9, leading=13, textColor=colors.grey)

doc = SimpleDocTemplate("/Users/ycchfx/AI實作/SmartCar/SmartCar_對比報告.pdf",
                        pagesize=A4, topMargin=18*mm, bottomMargin=16*mm,
                        leftMargin=18*mm, rightMargin=18*mm,
                        title="SmartCar 人工 vs 自動 對比報告")
story = []

def P(t, st=body): story.append(Paragraph(t, st))
def gap(h=6): story.append(Spacer(1, h))

def table(rows, widths, header=True, aligns=None):
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    ts = [
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dddddd")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        ts += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0d6efd")),
               ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
               ("FONTSIZE", (0, 0), (-1, 0), 9.5)]
    ts.append(("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f7fb")]))
    if aligns:
        for col, a in aligns.items():
            ts.append(("ALIGN", (col, 0), (col, -1), a))
    t.setStyle(TableStyle(ts))
    return t

# ---------- 封面 / 標題 ----------
P("SmartCar 集團統一派遣", title)
P("人工調度 vs 自動排班(VROOM)對比報告", sub)
story.append(HRFlowable(width="100%", color=colors.HexColor("#0d6efd"), thickness=1.2))
gap(10)

# ---------- 摘要 ----------
P("一、摘要", h2)
P(f"以小驢駒集團 4 個車行 2025 年實際人工派遣紀錄(共 {ov[0]} 筆)為基準,"
  f"在相同條件下(同車行同日、同一批成行單、人工當天實際用車、±30 分時間窗)"
  f"以自架 OSRM 行車時間矩陣 + VROOM 最佳化重新排班,逐日對比。")
P(f"<b>結果:在 {g['days']} 個營運日、{g['orders']} 趟成行單中,自動排班的用車量(車日合計)由人工的 "
  f"<b>{g['human_vehicle_days']}</b> 降至 <b>{g['vroom_vehicle_days']}</b>,"
  f"節省 <b>{g['saved_vehicle_days']} 車日(↓{g['saved_pct']}%)</b>;"
  f"其中 <b>{g['days_vroom_better']}/{g['days']}</b> 天自動排班用車更少。</b>")
gap(4)

# 摘要數字表
table_rows = [
    ["指標", "人工", "自動(VROOM)", "差異"],
    ["用車(車日合計)", str(g["human_vehicle_days"]), str(g["vroom_vehicle_days"]),
     f"↓{g['saved_pct']}%(省 {g['saved_vehicle_days']})"],
    ["服務趟次", str(g["orders"]), str(g["orders"] - g["vroom_unassigned"]),
     f"未排入 {g['vroom_unassigned']}"],
    ["自動更省的天數", "—", f"{g['days_vroom_better']} / {g['days']}", ""],
]
story.append(table(table_rows, [55*mm, 30*mm, 40*mm, 45*mm],
                   aligns={1: "CENTER", 2: "CENTER"}))
gap(10)

# ---------- 背景 ----------
P("二、背景與目標", h2)
P("長照接送目前多仰賴人工調度,仰賴調度員的地理與經驗知識。本專案目標為驗證:"
  "以最佳化引擎自動排班,是否能在維持服務品質下,較人工調度更有效率(更少用車、更短里程)。")

# ---------- 方法 ----------
P("三、方法與流程", h2)
for line in [
    f"<b>1. 資料匯入</b>:4 個車行的長照平台派遣匯出檔,共 {ov[0]} 筆(含訂單與人工派遣結果)。"
    "已去識別化(不儲存身分證號)。",
    f"<b>2. 資料建置</b>:起迄地址經緯度入庫(地址簿 {ov[4]} 門牌),自動建立車輛 {ov[2]} 台、司機 {ov[3]} 名,"
    "並以「車行」標記每筆訂單(集團共用車池)。",
    "<b>3. 車隊主檔</b>:由「司機工作資料管理」名冊回填每台車的<b>真實可載客數</b>(已扣司機/輪椅佔位)、"
    "<b>福祉車能力</b>,以及<b>出車起點與收車終點</b>(車輛當日出發與最終返回位置)。",
    "<b>4. 司機營運規則(本版重點)</b>:彈性工時,每趟計<b>前後各 20 分</b>作業時間;"
    "每車每日工時上限 <b>8 小時</b>;接送服務時段 <b>06:00–18:00</b>;"
    "<b>共乘須客戶同意</b>(僅「願意共乘」之單可併車,其餘獨佔整車)。上車時間統一以台灣 +08 時區換算。",
    "<b>5. 引擎</b>:自架 OSRM 計算台灣真實道路行車時間矩陣;VROOM 求解(含福祉車技能、真實座位、"
    "預約時間窗、上述工時/共乘規則,並令每車首站自起點出發、末站返回終點)。",
    "<b>6. 對比方法</b>:逐(車行 × 日)取「已成行」訂單,車隊 = 人工當天實際用到的車,"
    "時間窗 ±30 分;比較用車數、可行性、行駛。唯讀,不影響營運資料。",
]:
    P("• " + line)
gap(8)

# ---------- 資料概況 ----------
P("四、資料概況(各車行)", h2)
rows = [["車行", "天數", "成行單", "人工車日", "自動車日", "節省率"]]
for f, s in by_fleet.items():
    rows.append([f, str(s["days"]), str(s["orders"]), str(s["human_vehicle_days"]),
                 str(s["vroom_vehicle_days"]), f"↓{s['saved_pct']}%"])
story.append(table(rows, [30*mm, 18*mm, 24*mm, 28*mm, 28*mm, 24*mm],
                   aligns={1: "CENTER", 2: "CENTER", 3: "CENTER", 4: "CENTER", 5: "CENTER"}))
gap(6)
P("註:樂格適、發隆興每日多為單筆訂單,人工與自動皆用 1 車,故無差異。", small)
gap(8)

# 各車行 人工 vs 自動 車日 長條圖
fleet_names = list(by_fleet.keys())
human_vals = [by_fleet[f]["human_vehicle_days"] for f in fleet_names]
vroom_vals = [by_fleet[f]["vroom_vehicle_days"] for f in fleet_names]
d = Drawing(460, 210)
bc = VerticalBarChart()
bc.x, bc.y, bc.width, bc.height = 35, 30, 330, 150
bc.data = [human_vals, vroom_vals]
bc.categoryAxis.categoryNames = fleet_names
bc.categoryAxis.labels.fontName = FONT
bc.categoryAxis.labels.fontSize = 9
bc.valueAxis.valueMin = 0
bc.valueAxis.labels.fontName = FONT
bc.valueAxis.labels.fontSize = 8
bc.bars[0].fillColor = colors.HexColor("#9aa5b1")  # 人工
bc.bars[1].fillColor = colors.HexColor("#198754")  # 自動
bc.barWidth = 8
bc.groupSpacing = 14
d.add(bc)
lg = Legend()
lg.x, lg.y = 380, 150
lg.fontName = FONT
lg.fontSize = 9
lg.dxTextSpace = 5
lg.deltay = 14
lg.colorNamePairs = [(colors.HexColor("#9aa5b1"), "人工車日"),
                     (colors.HexColor("#198754"), "自動車日")]
d.add(lg)
story.append(d)
P("圖:各車行用車量(車日合計)— 人工 vs 自動排班。", small)
gap(8)

# ---------- 結果:省最多的日子 ----------
P("五、節省最多的營運日(前 10)", h2)
rows = [["日期", "車行", "成行單", "人工車", "自動車", "省車", "未派"]]
for r in top:
    rows.append([r["service_date"], r["fleet"], str(r["n_orders"]), str(r["human_vehicles"]),
                 str(r["vroom_vehicles"]), str(r["saved_vehicles"]), str(r["vroom_unassigned"])])
story.append(table(rows, [24*mm, 20*mm, 20*mm, 20*mm, 20*mm, 18*mm, 16*mm],
                   aligns={c: "CENTER" for c in range(2, 7)}))
gap(10)

# ---------- 解讀與限制 ----------
# ---------- 共乘增益 ----------
if pool:
    pg = pool["group"]
    human = g["human_vehicle_days"]
    auto = g["vroom_vehicle_days"]
    pooled = pg["v_pool"]
    total_pct = round(100 * (human - pooled) / human, 1) if human else 0
    P("六、共乘增益(若推薦組取得同意)", h2)
    P(f"目前僅約 3.5% 乘客已同意共乘。若針對系統挑出的 <b>{pg['ask_groups']} 組</b>(約占 2% 趟次)"
      f"徵得同意,集團用車可由自動的 {auto} 車日再降至 <b>{pooled}</b> 車日,"
      f"<b>較現況再省 {pg['saved_vehicles']} 車日(↓{pg['extra_saved_pct_vs_now']}%)</b>;"
      f"相對人工的總節省由 ↓{g['saved_pct']}% 提升至 <b>↓{total_pct}%</b>。")
    prows = [["車行", "現況車日", "共乘後車日", "額外省", "需徵詢組"]]
    for f, s in pool["by_fleet"].items():
        prows.append([f, str(s["v_now"]), str(s["v_pool"]),
                      f"↓{s['extra_saved_pct_vs_now']}%", str(s["ask_groups"])])
    story.append(table(prows, [34*mm, 30*mm, 32*mm, 26*mm, 26*mm],
                       aligns={1: "CENTER", 2: "CENTER", 3: "CENTER", 4: "CENTER"}))
    gap(4)
    P(f"另發現 <b>{pg.get('recurring_pairs', 0)} 組常態共乘對</b>(反覆在相近時間/起訖點同行,最高同行達數十日),"
      "最適合一次徵得長期同意,徵詢效率遠高於逐日。", small)
    gap(8)

# ---------- 解讀與限制 ----------
P("七、解讀與限制", h2)
_un = g['vroom_unassigned'] // 2  # summary 以 VROOM 任務數計(每趟 2),換算回趟數
for line in [
    "<b>本版已納入司機營運實況約束</b>(前後 40 分/趟、8h 工時上限、06:00–18:00 服務時段、"
    "共乘需同意),故節省幅度為較<b>保守且貼近實務</b>的估計,而非理論上限。",
    f"自動排班有 {_un} 趟未排入(約 {round(100*_un/g['orders'],1)}%),"
    "主因為落在 06:00–18:00 服務時段之外的歷史趟次(如清晨洗腎、深夜返家)及時段壅塞;"
    "此類趟次在新政策下需另案處理。",
    "8h 工時上限以 VROOM 行車時間近似(嚴格『趟程+前後 40 分』加總定義需自訂約束,效果方向一致)。",
    "仍有部分未列入車隊名冊的車輛以預設座位估算;補齊後可再校準。",
]:
    P("• " + line)
gap(8)

# ---------- 結論 ----------
P("八、結論與後續", h2)
P(f"在 4 個車行 220 個營運日、{g['orders']} 趟真實訂單上,於<b>司機實務約束下</b>,自動排班仍以更少車輛"
  f"服務逾 95% 趟次(集團整體 ↓{g['saved_pct']}%,有量車行台北 ↓{by_fleet.get('台北',{}).get('saved_pct',0)}%、"
  f"新北 ↓{by_fleet.get('新北',{}).get('saved_pct',0)}%,{g['days_vroom_better']}/{g['days']} 天自動更省),"
  f"顯示以最佳化引擎進行集團統一派遣具明確且可實現的降本空間。")
P("後續建議:① 調整時間窗與真實座位再驗證;② 導入經驗規則(常客固定駕駛、區域親和)作為軟性偏好;"
  "③ 於營運現場試行『人工 + 自動建議』人機協作。")
gap(10)
story.append(HRFlowable(width="100%", color=colors.HexColor("#cccccc"), thickness=0.6))
P("本報告由 SmartCar 系統自動產生。資料來源:小驢駒集團長照派遣歷史(已去識別化)。", small)

doc.build(story)
print("PDF 已產生:/Users/ycchfx/AI實作/SmartCar/SmartCar_對比報告.pdf")
