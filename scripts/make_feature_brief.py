#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""產生「SmartCar 功能簡介」PDF(給車隊客戶/主管,商業白話、賣點導向)。

內容為對外簡介(靜態),效益數字取自實證對比結果(220 營運日、13,534 真實趟)。
"""
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
OUT = "/Users/ycchfx/AI實作/SmartCar/SmartCar_功能簡介.pdf"

styles = getSampleStyleSheet()


def S(name, **kw):
    return ParagraphStyle(name, parent=styles["Normal"], fontName=FONT, **kw)


title = S("t", fontSize=22, leading=28, alignment=TA_CENTER, spaceAfter=2)
sub = S("sub", fontSize=12, leading=16, alignment=TA_CENTER, textColor=colors.grey, spaceAfter=14)
h2 = S("h2", fontSize=14.5, leading=19, spaceBefore=12, spaceAfter=7, textColor=colors.HexColor("#0b5394"))
body = S("b", fontSize=11, leading=17, alignment=TA_LEFT, spaceAfter=3)
note = S("n", fontSize=9, leading=13, textColor=colors.grey)
big = S("big", fontSize=22, leading=25, alignment=TA_CENTER, textColor=colors.white)
biglbl = S("bl", fontSize=10.5, leading=13, alignment=TA_CENTER, textColor=colors.white)
feat = S("ft", fontSize=11.5, leading=15, textColor=colors.HexColor("#0b5394"))

doc = SimpleDocTemplate(OUT, pagesize=A4, topMargin=16 * mm, bottomMargin=15 * mm,
                        leftMargin=18 * mm, rightMargin=18 * mm)
story = []


def P(t, st=body):
    story.append(Paragraph(t, st))


def gap(h=7):
    story.append(Spacer(1, h))


def card(num, label, color):
    inner = Table([[Paragraph(num, big)], [Paragraph(label, biglbl)]],
                  colWidths=[54 * mm], rowHeights=[15 * mm, 9 * mm])
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), color), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    return inner


# ---------- 封面 ----------
P("SmartCar 智慧派遣系統", title)
P("預約制長照接送車隊 — 功能簡介", sub)
story.append(HRFlowable(width="100%", color=colors.HexColor("#0b5394"), thickness=1.5))
gap(10)

P("一句話", h2)
P("把「靠調度員經驗逐筆手排」的派車工作,交給系統在幾秒內通盤最佳化:"
  "<b>同樣的訂單量,用更少的車、更順的路線完成</b>;調度員從手排轉為審核與處理例外。"
  "全套自架,資料留在自己機房。")
gap(10)

cards = Table([[card("↓18.6%", "用車量減少", colors.HexColor("#0d6efd")),
                card("約 585 萬", "每年可省成本", colors.HexColor("#198754")),
                card("100% 自架", "資料自主可控", colors.HexColor("#6f42c1"))]],
              colWidths=[58 * mm, 58 * mm, 58 * mm])
cards.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2)]))
story.append(cards)
P("以 220 個營運日、13,534 趟真實接送回算,並納入司機實務約束(工時、服務時段、車種、共乘同意)。", note)
gap(10)

# ---------- 系統能為車隊做什麼 ----------
P("系統能為車隊做什麼", h2)

FEATURES = [
    ("一鍵智慧派車",
     "匯入當天預約單,系統自動排出每台車最順的接送順序與路線(顧及輪椅/福祉車、座位、"
     "預約時間窗、司機工時)。用更少的車消化同樣訂單量。"),
    ("批次匯入 + 自動定位",
     "Excel/CSV/PDF 一次匯入;地址自動轉成門牌級座標(台灣 Map8),常用地址記憶免重查。"),
    ("固定行程 + 健檢",
     "「某些個案一定由某位司機接」可設成固定行程,系統自動綁定;並會『健檢』標出"
     "同一司機被排到撞車的衝突,提示該共乘或加備援車。"),
    ("順路共乘",
     "系統挑出最值得併乘的訂單請您徵詢同意,進一步把用車量再往下壓(實證合計可達 ↓25%)。"),
    ("班表 / 出勤 / 動態重排",
     "誰今天出勤、臨時請假、加班,貼一段文字就能更新;當天有取消或臨時加單,一鍵重排不影響進行中的趟。"),
    ("司機手機 App + 推播",
     "司機用手機看自己的路單、回報開始/完成;派遣有異動即時推播通知,免電話一一通知。"),
    ("行控工具",
     "拖放式派遣看板(撞車標紅)、可列印的車輛任務口卡、未派訂單分析(原因歸類 + 改善建議)。"),
    ("AI 調度助理",
     "用問的就能查當天營運狀況、需求預測、待排訂單,並給調度建議(以真實資料為依據)。"),
    ("效益報表",
     "人工 vs 自動對比、省下車日換算金額、營運趨勢圖;一鍵產出管理報告 PDF。"),
]
rows = []
for name, desc in FEATURES:
    rows.append([Paragraph(name, feat), Paragraph(desc, body)])
t = Table(rows, colWidths=[42 * mm, 120 * mm])
t.setStyle(TableStyle([
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.HexColor("#e3e8ef")),
    ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]))
story.append(t)
gap(10)

# ---------- 為什麼選 SmartCar ----------
story.append(KeepTogether([
    Paragraph("為什麼選 SmartCar", h2),
    Paragraph("• <b>台灣在地化</b>:門牌級地理編碼、福祉/輪椅車種、長照平台匯入格式,開箱即用。", body),
    Paragraph("• <b>資料自主</b>:全套自架於自己的機房/雲,訂單與個資不外流第三方平台。", body),
    Paragraph("• <b>實證效益</b>:以真實營運紀錄回算,非模擬假設;省多少車、多少錢,數字看得到。", body),
    Paragraph("• <b>服務品質不打折</b>:節省是在準時、車種需求、預約時間都滿足下達成。", body),
]))
gap(8)

# ---------- 導入方式 ----------
story.append(KeepTogether([
    Paragraph("導入方式", h2),
    Paragraph("建議 ① 先選 1–2 個車隊小規模試行,用實際結果驗證效益;② 同步建立「共乘同意」蒐集流程;"
              "③ 試行穩定後再全面導入。系統以 Docker 一鍵部署,可上雲或自架。", body),
]))
gap(10)
story.append(HRFlowable(width="100%", color=colors.HexColor("#cfd8e3"), thickness=0.8))
P("SmartCar 智慧派遣系統 · 功能簡介。效益數字取自真實營運回算,供評估參考。", note)

doc.build(story)
print("功能簡介已產生:", OUT)
