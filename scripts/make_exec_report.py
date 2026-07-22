#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""產生「管理階層摘要報告」PDF(全白話、無技術術語)。

聚焦商業語言:省多少錢、少用多少車、服務維持、下一步建議。
資料即時取自執行中的 API(對比總覽 / 成本效益 / 共乘增益)。
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
    HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

BASE = "http://localhost:8000/api"
FONT = "CJK"
pdfmetrics.registerFont(TTFont(FONT, "/Library/Fonts/Arial Unicode.ttf"))


def api(path, tok=None, data=None):
    headers = {"Content-Type": "application/json"}
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(BASE + path, data=body, headers=headers,
                                 method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


tok = api("/auth/login", data={"username": "admin", "password": "admin123"})["access_token"]
summary = api("/dispatch/comparison/summary", tok)
savings = api("/dispatch/comparison/savings", tok)
try:
    pool = api("/dispatch/pool-gain", tok)
    pool = pool if pool.get("available") else None
except Exception:
    pool = None

g = summary["group"]
sv = savings["group"]
cost = int(savings["cost_per_vehicle_day"])
annual_days = int(savings["annual_service_days"])


def wan(n):
    """金額轉『約 NT$XX 萬』。"""
    return f"約 NT$ {round(n / 10000):,} 萬"


def ntd(n):
    return f"NT$ {round(n):,}"


# 共乘:合計(vs 人工)車日與年化金額
pool_total_vd = pool_annual = pool_extra_vd = 0
if pool:
    pooled = pool["group"]["v_pool"]
    pool_total_vd = g["human_vehicle_days"] - pooled            # 共乘後 vs 人工 總省車日
    pool_extra_vd = g["vroom_vehicle_days"] - pooled            # 較自動再省
    per_day = pool_total_vd * cost / sv["observed_days"] if sv["observed_days"] else 0
    pool_annual = per_day * annual_days

# ---------- 樣式 ----------
styles = getSampleStyleSheet()


def S(name, **kw):
    return ParagraphStyle(name, parent=styles["Normal"], fontName=FONT, **kw)


title = S("t", fontSize=22, leading=28, alignment=TA_CENTER, spaceAfter=2)
sub = S("sub", fontSize=12, leading=16, alignment=TA_CENTER, textColor=colors.grey, spaceAfter=16)
h2 = S("h2", fontSize=15, leading=20, spaceBefore=14, spaceAfter=8, textColor=colors.HexColor("#0b5394"))
body = S("b", fontSize=11.5, leading=18, alignment=TA_LEFT, spaceAfter=4)
note = S("n", fontSize=9.5, leading=14, textColor=colors.grey)
big = S("big", fontSize=23, leading=26, alignment=TA_CENTER, textColor=colors.white)
biglbl = S("bl", fontSize=11, leading=14, alignment=TA_CENTER, textColor=colors.white)

doc = SimpleDocTemplate("/Users/ycchfx/AI實作/DR_FISH/DR_FISH_管理報告.pdf",
                        pagesize=A4, topMargin=18 * mm, bottomMargin=16 * mm,
                        leftMargin=18 * mm, rightMargin=18 * mm)
story = []


def P(t, st=body):
    story.append(Paragraph(t, st))


def gap(h=8):
    story.append(Spacer(1, h))


# ---------- 封面標題 ----------
P("智慧派遣系統 — 效益評估摘要", title)
P("提供管理階層決策參考 · 以真實營運紀錄回算", sub)
story.append(HRFlowable(width="100%", color=colors.HexColor("#0b5394"), thickness=1.5))
gap(10)

# ---------- 一句話結論 ----------
P("一、結論", h2)
P(f"以系統自動安排每日接送班次與路線後,在<b>服務量完全不變</b>的前提下,"
  f"可由目前的 <b>{g['human_vehicle_days']:,}</b> 個「車輛出勤日」降到 "
  f"<b>{g['vroom_vehicle_days']:,}</b> 個,<b>減少 {g['saved_pct']}%</b> 的用車。"
  f"換算每年可為車隊節省 <b>{wan(sv['annual_saving_ntd'])}</b> 的營運成本。")
gap(6)

# ---------- 三大關鍵數字卡 ----------
def card(num, label, color):
    inner = Table([[Paragraph(num, big)], [Paragraph(label, biglbl)]],
                  colWidths=[54 * mm], rowHeights=[16 * mm, 9 * mm])
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), color),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return inner


cards = Table([[card(wan(sv["annual_saving_ntd"]), "每年可省營運成本", colors.HexColor("#198754")),
                card(f"↓{g['saved_pct']}%", "用車量減少", colors.HexColor("#0d6efd")),
                card(f"{g['days_vroom_better']}/{g['days']} 天", "系統更省的天數", colors.HexColor("#6f42c1"))]],
               colWidths=[58 * mm, 58 * mm, 58 * mm])
cards.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2)]))
story.append(cards)
gap(12)

# ---------- 這代表什麼 ----------
P("二、這代表什麼?", h2)
for line in [
    f"<b>更少的車、做一樣多的事</b>:評估期間共服務 {g['orders']:,} 趟接送。"
    f"原本人工調度需要動用 {g['human_vehicle_days']:,} 個車輛出勤日,系統優化後只需 "
    f"{g['vroom_vehicle_days']:,} 個,等於騰出 <b>{sv['saved_vehicle_days']:,} 個車輛出勤日</b>的人力與車輛。",
    f"<b>省下的是真金白銀</b>:以每台車每日成本 {ntd(cost)} 估算,"
    f"評估期間已可省下 {ntd(sv['observed_saving_ntd'])},全年化約 {wan(sv['annual_saving_ntd'])}。",
    "<b>服務品質不打折</b>:上述節省是在「準時、車種需求(如輪椅車)、乘客預約時間」"
    "都滿足的前提下達成,並非犧牲服務換來的。",
]:
    P("• " + line)
gap(6)

# ---------- 為什麼能省(白話,不談技術) ----------
P("三、為什麼能省下來?", h2)
P("過去每天的派車主要靠調度人員的經驗手動安排。當訂單一多,人很難同時把"
  "「誰先誰後、哪幾趟可以順路一起接、哪台車跑哪一區最省」全部算到最好。")
P("這套系統會在幾秒內、把當天所有訂單一次通盤規劃:自動排出每台車最順的接送順序與路線,"
  "讓同一台車一天能多服務幾趟,於是<b>用更少的車就能消化同樣的訂單量</b>。"
  "調度人員則從「逐筆手排」轉為「審核與處理例外」,更省時也更穩定。")
gap(6)

# ---------- 各車行效益 ----------
P("四、各車隊效益", h2)
rows = [["車隊", "服務天數", "目前用車(車日)", "優化後用車", "減少", "每年可省"]]
for f, s in summary["by_fleet"].items():
    fv = savings["by_fleet"].get(f, {})
    rows.append([f, str(s["days"]), f"{s['human_vehicle_days']:,}",
                 f"{s['vroom_vehicle_days']:,}", f"↓{s['saved_pct']}%",
                 wan(fv.get("annual_saving_ntd", 0)) if fv.get("annual_saving_ntd") else "—"])
t = Table(rows, colWidths=[24 * mm, 22 * mm, 32 * mm, 28 * mm, 20 * mm, 30 * mm])
t.setStyle(TableStyle([
    ("FONTNAME", (0, 0), (-1, -1), FONT), ("FONTSIZE", (0, 0), (-1, -1), 10),
    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b5394")),
    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
    ("ALIGN", (1, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f6fb")]),
    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cfd8e3")),
    ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
]))
story.append(t)
P("註:單量很小的車隊(每天多為單筆訂單)本來就只用 1 台車,沒有壓縮空間,故無差異。", note)
gap(8)

# ---------- 共乘的額外機會 ----------
if pool:
    P("五、額外機會:共乘", h2)
    P(f"在上述成果之外,若進一步推動「順路共乘」(需事先取得乘客同意),"
      f"用車量可再由 {g['vroom_vehicle_days']:,} 降到 <b>{pool['group']['v_pool']:,}</b> 個車輛出勤日,"
      f"較目前人工合計減少 <b>{round(100 * pool_total_vd / g['human_vehicle_days'], 1)}%</b>"
      f"(全年化合計可省 <b>{wan(pool_annual)}</b>)。")
    P(f"做法上只需針對系統挑出的 <b>{pool['group']['ask_groups']} 組</b>最值得併乘的訂單"
      "徵詢同意即可,不必全面開放,對乘客衝擊小。", note)
    gap(6)

# ---------- 限制與下一步 ----------
P("六、限制與建議下一步", h2)
for line in [
    "<b>數字來源</b>:以上為實際歷史訂單回算的結果,非模擬假設;但會因季節與訂單分布而浮動。",
    "<b>成本參數可調</b>:節省金額以每車日 " + ntd(cost) + "、年營運 " + str(annual_days) +
    " 天估算,可依車隊實際成本在系統內調整。",
    "<b>建議</b>:① 先選 1–2 個車隊小規模試行,以實際結果驗證效益;"
    "② 同步建立「共乘同意」蒐集流程,逐步釋放上述額外效益;"
    "③ 試行穩定後再全面導入。",
]:
    P("• " + line)
gap(10)
story.append(HRFlowable(width="100%", color=colors.HexColor("#cfd8e3"), thickness=0.8))
P("本報告由智慧派遣系統依真實營運資料自動產生,供管理決策參考。", note)

doc.build(story)
print("管理報告已產生:/Users/ycchfx/AI實作/DR_FISH/DR_FISH_管理報告.pdf")
print(f"  年省 {wan(sv['annual_saving_ntd'])} | 用車 ↓{g['saved_pct']}% | 共乘後合計年省 {wan(pool_annual)}")
