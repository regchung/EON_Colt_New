#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""產生「營運分析管理報告」PDF（給客戶主管討論用，全白話）。

內容：服務時間與區域分析 + 未能成功派遣案例（按原因）+ 對應解決方式 + 待決策事項。
資料來源：/tmp/ops_report_data.json（由容器端 collector 產出）+ 對比效益 API（可選）。
"""
import json
import urllib.request

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

FONT = "CJK"
pdfmetrics.registerFont(TTFont(FONT, "/Library/Fonts/Arial Unicode.ttf"))
OUT = "/Users/ycchfx/AI實作/EON_COLT/EON_COLT_營運分析報告.pdf"

D = json.load(open("/tmp/ops_report_data.json", encoding="utf-8"))


def api(path, tok=None, data=None):
    headers = {"Content-Type": "application/json"}
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request("http://localhost:8000/api" + path, data=body,
                                 headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read())


# 對比效益（可選，失敗則略過）
HEAD = None
try:
    tok = api("/auth/login", data={"username": "admin", "password": "admin123"})["access_token"]
    s = api("/dispatch/comparison/summary", tok)
    sv = api("/dispatch/comparison/savings", tok)
    HEAD = {"saved_pct": s["group"]["saved_pct"],
            "human": s["group"]["human_vehicle_days"],
            "vroom": s["group"]["vroom_vehicle_days"],
            "annual": sv["group"]["annual_saving_ntd"]}
except Exception:
    HEAD = None

# ---------- 樣式 ----------
styles = getSampleStyleSheet()


def S(name, **kw):
    return ParagraphStyle(name, parent=styles["Normal"], fontName=FONT, **kw)


title = S("t", fontSize=21, leading=27, alignment=TA_CENTER, spaceAfter=2)
sub = S("sub", fontSize=11.5, leading=15, alignment=TA_CENTER, textColor=colors.grey, spaceAfter=14)
h2 = S("h2", fontSize=14.5, leading=19, spaceBefore=13, spaceAfter=7, textColor=colors.HexColor("#0b5394"))
h3 = S("h3", fontSize=12, leading=16, spaceBefore=7, spaceAfter=3, textColor=colors.HexColor("#b45309"))
body = S("b", fontSize=11, leading=17, alignment=TA_LEFT, spaceAfter=3)
note = S("n", fontSize=9, leading=13, textColor=colors.grey)
cellL = S("cl", fontSize=9.5, leading=13)
cellW = S("cw", fontSize=9.5, leading=13, textColor=colors.white)

doc = SimpleDocTemplate(OUT, pagesize=A4, topMargin=16 * mm, bottomMargin=15 * mm,
                        leftMargin=17 * mm, rightMargin=17 * mm)
story = []


def P(t, st=body):
    story.append(Paragraph(t, st))


def gap(h=7):
    story.append(Spacer(1, h))


def hr(c="#0b5394", th=1.4):
    story.append(HRFlowable(width="100%", color=colors.HexColor(c), thickness=th))


def mktable(rows, widths, header_bg="#0b5394", align_from=1):
    t = Table(rows, colWidths=widths)
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT), ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(header_bg)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (align_from, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f6fb")]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cfd8e3")),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


# ========== 封面 ==========
P("智慧派遣系統 — 營運分析報告", title)
rng = D["range"]
P(f"服務時間與區域分析 · 未派案例與解決方案 ｜ 資料區間 {rng['start']} ~ {rng['end']}（{rng['total']:,} 趟真實接送）", sub)
hr()
gap(8)

# ========== 一、總覽 ==========
P("一、總覽", h2)
if HEAD:
    P(f"本報告以 <b>{rng['total']:,} 趟</b>真實接送紀錄為基礎，分析「服務集中在什麼時間、什麼區域」，"
      f"以及「哪些訂單目前無法由系統自動排入、原因與解法」。系統自動派遣在服務量不變下，"
      f"已可將用車量由 {HEAD['human']:,} 降至 {HEAD['vroom']:,} 個車輛出勤日（<b>↓{HEAD['saved_pct']}%</b>，"
      f"年化省約 NT$ {round(HEAD['annual']/10000):,} 萬）；本報告聚焦「剩餘無法排入的少數案例」如何進一步收斂。")
else:
    P(f"本報告以 <b>{rng['total']:,} 趟</b>真實接送紀錄為基礎，分析服務的時間與區域分布，"
      f"以及目前無法由系統自動排入的少數案例之原因與解決方式，供主管決策討論。")
gap(6)

# ========== 二、服務時間分析 ==========
P("二、服務時間分析", h2)
# weekday 表
rows = [["星期", "樣本天數", "平均每日趟次", "平均出勤車數"]]
for w in D["weekday"]:
    rows.append([w["name"], str(w["days"]), f"{w['avg_trips']:.0f}", str(w["avg_veh"])])
story.append(mktable(rows, [30 * mm, 30 * mm, 40 * mm, 40 * mm]))
gap(5)
peak = D["peak_hour"]
P("重點觀察：", h3)
for line in [
    "平日（週一～週五）每天約 <b>140–161 趟</b>，<b>週二最繁忙</b>；週六約腰斬至 73 趟，週日幾乎不營運。",
    f"一天的尖峰落在 <b>{peak} 點前後</b>（就醫／復健時段），上午 09–13 時約占全日六成需求。",
    f"<b>{100 - D['out_of_hours_pct']:.1f}%</b> 的接送落在現行服務時段（06:00–18:00）之內，時段設定與實際需求高度吻合。",
]:
    P("• " + line)
gap(6)

# ---- 尖峰壅塞情報 ----
cg = D.get("congestion")
if cg and cg.get("slow_hours"):
    P("尖峰壅塞情報（實測車速）", h3)
    P(f"全日平均行車時速約 <b>{cg['day_median_kmh']:.0f} 公里</b>。但在<b>早上 8 點、下午 5 點</b>兩個通勤尖峰，"
      f"相同距離下的實際車速比平時<b>慢約 4 成</b>（下表），這兩段約占全部接送的 <b>{cg['slow_share_pct']:.0f}%</b>。"
      "（已控制行駛距離，確為時段壅塞，非短程造成。）")
    rows = [["時段", "實測車速", "比平時慢", "佔接送量"]]
    for r in cg["slow_hours"]:
        rows.append([f"{r['h']:02d}:00 前後", f"{r['kmh']:.0f} km/h",
                     f"↓{r['slower_pct']}%", f"{r['share_pct']:.1f}%"])
    story.append(mktable(rows, [34 * mm, 30 * mm, 26 * mm, 28 * mm]))
    gap(3)
    P("<b>對排班的意義</b>：這兩個時段的趟次實際路程時間會明顯拉長。建議為 08:00、17:00 前後的"
      "車輛銜接保留較寬裕的緩衝，避免一台車連環誤點。目前系統以充足的作業緩衝（上車彈性 ±30 分、"
      "每趟前後置 40 分）吸收此差異，故仍能準時；此為持續優化的觀察點。", note)
    gap(6)

# ========== 三、服務區域分析 ==========
P("三、服務區域分析", h2)
rows = [["縣市", "趟次", "佔比"]]
for c in D["city"]:
    rows.append([c["name"], f"{c['n']:,}", f"{c['pct']:.1f}%"])
ct = mktable(rows, [34 * mm, 30 * mm, 24 * mm])
rows2 = [["主要行政區（前 6）", "佔比"]]
for t in D["town_top"][:6]:
    rows2.append([t["name"], f"{t['pct']:.1f}%"])
tt = mktable(rows2, [44 * mm, 22 * mm])
side = Table([[ct, tt]], colWidths=[92 * mm, 70 * mm])
side.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                          ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]))
story.append(side)
gap(5)
zs = D["zone_signal"]
P("重點觀察：", h3)
for line in [
    f"服務高度集中雙北：<b>台北市 {D['city'][0]['pct']:.0f}%、新北市 {D['city'][1]['pct']:.0f}%</b>（合計約 98%）。",
    "需求分散在約 30 個行政區，最大的大安區也僅 8.5%，<b>沒有單一壓倒性區域</b>。",
    f"司機並不固定跑某一區（每位司機主力區占比中位僅 <b>{zs['median_pct']}%</b>，{zs['vehicles']} 台中達 50% 者 {zs['ge50']} 台），"
    "代表「彈性調度、哪裡有單跑哪裡」是現況常態 —— 不宜把區域當硬性綁定。",
]:
    P("• " + line)
gap(6)

# ========== 四、未能成功派遣的案例（按原因）==========
P("四、未能成功派遣的案例 — 按原因分類與解決方式", h2)
P("以下歸納目前「無法由系統自動排入」的少數案例。整體占全部接送極小比例，"
  "但每一類都對應一個可由貴方決定的處理方向：", body)
gap(3)

uh = D["unassigned_hist"]["by_reason"]
ul = D["unassigned_live"]
n_out = next((v for k, v in uh.items() if "時段外" in k), 0)
n_inf = next((v for k, v in uh.items() if "滿載" in k or "時間窗" in k), 0)

cats = [
    ("類別一：預約時間落在服務時段之外",
     f"{n_out} 趟（歷史回測）",
     "乘客預約的上車時間在 06:00 前或 18:00 後，系統依現行規則不予排入。占全部接送約 0.1%，量很小。",
     ["延後收班時間（例如至 18:30 / 19:00）以吸收傍晚需求；或",
      "安排 1 台早／晚班車，專責清晨與夜間的零星接送。"],
     "是否願意調整服務時段，或設置早／晚班車？"),
    ("類別二：尖峰運能不足 / 預約時間太剛性",
     f"{n_inf} 趟（歷史回測）",
     "集中在中午尖峰（09–13 時），當下所有合適車輛皆已滿載，或乘客可上車的時間彈性太小，排不進現有班次。",
     ["與乘客約定上車時間可彈性 ±30～45 分（系統實測：放寬上車時間窗能大幅提高排入率）；或",
      "於尖峰時段增派車輛。"],
     "乘客能否接受上車時間 ±X 分的彈性？尖峰是否增派車輛？"),
    ("類別三：指定司機之固定路線「單一司機超載」",
     f"{ul['total']} 趟（{ul['date']} 實際派遣，共 {ul['pax']} 人）",
     "部分個案要求「一定由某位司機接送」。當同一位司機同一天被指定的趟次過多、時間又彼此重疊"
     "（如同校多名學生上下學、同一診所多次往返），單一司機與車輛無法分身，超出的趟次即無法排入。",
     ["同校、同時段、同方向的學生改為「共乘併車」（一台 4 座車載 2 名學生即可消化，約可解 6 趟）；",
      "高需求路線（如特定診所團體）加派第二位指定司機 / 備援車；",
      "福祉（輪椅）且地點偏遠者，安排專屬福祉備援車。"],
     "① 同校學生家長是否同意共乘？② 高量路線是否配第二台車？③ 是否保留「非某司機不可」的硬性指定（放寬可提高排入率，但失去指定保證）？"),
]
for name, cnt, desc, sols, decision in cats:
    P(f"{name}　<font color='#b45309'>（{cnt}）</font>", h3)
    P("• <b>情況</b>：" + desc)
    P("• <b>解決方式</b>：")
    for i, sv in enumerate(sols, 1):
        P(f"　　{chr(0x2460 + i - 1)} {sv}")
    P(f"• <b>需與主管討論決定</b>：{decision}")
    gap(4)

# 類別三 6/22 明細小表（整桌保持同頁）
rows = [["上車", "個案", "人數", "車種"]]
for it in ul["items"]:
    rows.append([it["t"], it["name"], f"{it['pax']}人", "福祉" if it["welfare"] else "一般"])
story.append(KeepTogether([
    Paragraph("（類別三 2026/6/22 未排入明細）", h3),
    mktable(rows, [22 * mm, 50 * mm, 22 * mm, 24 * mm]),
]))
gap(8)

# ========== 五、參數檢視與待決策(上車窗效益) ==========
P("五、參數檢視與待決策（上車時間窗效益）", h2)
P("我們以全部真實營運紀錄,檢視了系統的關鍵營運參數,大多校準良好、無需調整;"
  "唯一值得主管拍板的是「上車時間窗」—— 它直接決定「能省多少車」與「乘客要等多久」的取捨。", body)
gap(3)
P("參數檢視小結（維持現狀）", h3)
for line in [
    "<b>服務時段 06:00–18:00</b>:99.9% 的接送落在內,設定與需求高度吻合。",
    "<b>每趟前後置作業 40 分</b>:經歷史反推驗證合理、甚至偏保守(沒有高估司機作業時間),故效益數字可信。",
    "<b>司機每日工時上限 8 小時</b>:實測放寬到 9–10 小時對省車「零影響」(瓶頸不在工時),維持以守住勞權。",
]:
    P("• " + line)
gap(4)

P("上車時間窗效益（全年實測,@每車日 NT$3,800）", h3)
P("上車窗 = 系統實際到場相對預約時間的容許彈性(預約時間起、最晚往後 N 分)。"
  "放寬 → 同一台車能串更多趟 → 更省車、更少未派;代價是乘客最晚到場時間往後。", body)
rows = [["上車窗", "用車量減少", "全年未派", "每年可省", "乘客最晚到場"]]
for w, pct, un, wan, late in [
    ("30 分（現行）", "↓18.6%", "12 趟", "約 585 萬", "預約 +30 分"),
    ("45 分", "↓23.4%", "2 趟", "約 736 萬", "預約 +45 分"),
    ("60 分", "↓27.6%", "2 趟", "約 870 萬", "預約 +60 分"),
]:
    rows.append([w, pct, un, wan, late])
story.append(KeepTogether([mktable(rows, [30 * mm, 26 * mm, 22 * mm, 28 * mm, 30 * mm])]))
gap(3)
P("• <b>30 → 45 分</b>:每年多省約 <b>NT$151 萬</b>,未派從 12 趟降到 2 趟,乘客最多多等 15 分。", body)
P("• <b>45 → 60 分</b>:每年再多省約 NT$134 萬,乘客最多再多等 15 分。", body)
P("• <b>需與主管討論決定</b>:車隊願意讓乘客「最晚到場 = 預約 +45（或 +60）分」嗎?"
  "(可再評估「尖峰放寬、離峰維持準點」的差異化做法。)", body)
gap(8)

# ========== 六、建議討論順序 ==========
P("六、建議與主管討論的決策順序", h2)
for i, line in enumerate([
    "<b>服務時段</b>：是否延後收班或設早晚班 —— 影響類別一（最易處理、量小）。",
    "<b>上車時間彈性</b>：能否與乘客約定 ±30～45 分彈性 —— 對排入率幫助最大、零成本。",
    "<b>共乘同意</b>：同校學生、同診所團體是否願意併車 —— 直接收斂類別三約一半案例。",
    "<b>備援車安排</b>：高需求路線 / 福祉偏遠案，是否配第二台車或福祉備援。",
    "<b>指定司機政策</b>：硬性「指定某司機」是否可在必要時放寬為「優先指派」。",
], 1):
    P(f"{i}. " + line)
gap(8)
hr("#cfd8e3", 0.8)
P("備註：本報告數字皆取自真實營運紀錄（非模擬）；所有時間以台灣時間（UTC+8）統一計算與顯示。"
  "未派案例之「歷史回測」為系統以固定方法學回算之結果，「實際派遣」為當日真實排班結果。", note)

doc.build(story)
print("營運分析報告已產生：", OUT)
