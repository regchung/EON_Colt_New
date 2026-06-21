# 評估:本地文件抽取(Docling)/ 多租戶隔離 / 引擎升級(Timefold)

> 一次 GitHub 探勘,針對本案**實際缺口**(非熱門度)做三項裁決。評估日期:2026-06。
> 對齊戰略:P1「商業化前硬需求 = 多租戶隔離 + 個資合規」、「引擎不自研、需要強度時換」。

---

## 1) 🟢 Docling — 本地文件抽取(ADOPT 候選,解 PII 合規硬傷)

**動機**:現行「AI 文件智慧匯入」(`doc_ingest.py` + `POST /orders/import-doc`)會把**文件原文
(含乘客姓名/電話/地址等真實 PII)送往 Claude API** 抽取。這與「送 Claude 一律去識別化」原則
有張力,且是**收費前的法規硬需求**——真實 PII 上線前必須改地端抽取。

**候選**:[Docling](https://github.com/docling-project/docling)(IBM Research 起,LF AI & Data 託管)。
- 61.9k★、186 release、MIT、維護強。
- 支援 PDF / DOCX / PPTX / XLSX / HTML / EPUB;版面分析 + 表格結構辨識 + OCR。
- **可全本地 / 氣隙環境執行**(`Local execution for sensitive data and air-gapped environments`)。

**裁決:ADOPT 候選(以可開關 PoC 先行,預設關閉)**。理由與護欄:
- 與當初被否決的 MarkItDown 的差異:**MarkItDown 為「方便」而重(否決合理);Docling 為
  「PII 不出機房」而重**——這是法規硬需求,屬「值得的重」。性質不同,不違背精簡策略。
- ⚠️ 重量誠實揭露:完整管線會拉 torch / VLM,容器顯著變大、首跑下載模型。故**不寫入
  requirements.txt**,改用 `EXTRACTOR` 環境開關;預設 `native`(現行輕量原生抽取),
  只有明確設 `EXTRACTOR=docling` 並安裝 docling 時才走本地抽取。
- 落地形狀(已實作 PoC,見 `doc_ingest.extract_text`):
  Docling 本地抽文字/表格 → 後續再決定送**去識別化**文字給 Claude、或接本地 LLM(Ollama)。
  抽取層是單一函式,替換點乾淨,主流程零改動。
- **替代/搭配**:[Unstract](https://unstract.com/) + Ollama 為更完整的「全本地 ETL」管線;
  [LLMAIx](https://github.com/KatherLab/LLMAIx) 提供本地 LLM 抽取**+匿名化**(研究級、較小)。
  本案先用 Docling 做抽取,匿名化交由現有 `_coerce` 後處理或後續本地 LLM。

**下一步(待決)**:PoC 隔離可開關已就緒;是否正式納入 = 等真實 PII 上線時程拍板,
屆時把 docling 寫入 requirements 並補一條去識別化中介層(抽取後、送任何雲端前先遮蔽 PII)。

---

## 2) 🟡 多租戶隔離 — Postgres RLS(採模式,不直接相依套件)

**動機**:多租戶資料隔離是收費前硬需求。目前 schema 已有 `fleet` / `home_fleet` 可作租戶鍵,
但缺**強制隔離**(任何查詢都不會跨租戶看到資料)。

**候選**:
- [fastapi-tenancy](https://github.com/fastapi-extensions/fastapi-tenancy):schema / db / RLS / hybrid
  四策略、JWT/subdomain/header 解析,MIT。**但僅 4★、過於年輕** → 當相依風險高。
- [fastapi-rowsecurity](https://github.com/JWDobken/fastapi-rowsecurity):示範用 SQLAlchemy event +
  Postgres session variable(`SET app.current_tenant`)落實 RLS。

**裁決:抄模式、自建 RLS,不引入不成熟套件**。做法綱要(未實作,待 P1 商業化排程):
1. 各租戶資料表加 `tenant_id`(或沿用既有 `fleet` 鍵)。
2. Postgres `ENABLE ROW LEVEL SECURITY` + policy `USING (tenant_id = current_setting('app.tenant'))`。
3. FastAPI 依賴在每 request 開頭 `SET LOCAL app.tenant = :jwt_tenant`(SQLAlchemy event/middleware)。
4. JWT 夾帶 tenant 宣告;admin 角色可跨租戶(policy 加 bypass 條件)。
- 護欄:RLS 是「防呆最後一道」,應用層仍要顯式帶 tenant 過濾(縱深防禦)。

---

## 3) 🔴 引擎升級 Timefold — Python 版已封存,維持 VROOM(更新路線圖)

**背景**:CLAUDE.md / BACKLOG 原記「需要強度時換 VROOM / **Timefold**」。

**關鍵情報**:[timefold-solver-python](https://github.com/TimefoldAI/timefold-solver-python)
**已於 2025-10-06 由官方封存(read-only)**,團隊轉而專注 Java / Kotlin 版
([timefold-solver](https://github.com/TimefoldAI/timefold-solver),Apache-2.0)。
社群有 fork [SolverForge](https://github.com/BlackOpsAI/blackops-solver-legacy)(基於最後 Python release)
延續,但屬單一 fork、風險高。

**裁決:Timefold-Python 從升級路線劃掉,維持 VROOM**。
- 內嵌式 Python 解法目前 **VROOM(pyvroom)仍是正解**,且其 shipment 原生支援我們的 PDPTW
  (見 `eval-pyvrp-vs-vroom.md`,PyVRP 因不支援配對接送已 NO-GO)。
- 若未來真撞到 VROOM 解品質/規模天花板,選項退為:
  (a) OR-Tools PDPTW(Python 原生、Google 維護);
  (b) Timefold **Java 版**獨立服務(品質強但需另起 JVM 服務、跨語言整合成本高);
  (c) SolverForge(風險自負)。
- **行動**:同步更新 CLAUDE.md / BACKLOG 的「Timefold」字樣為「OR-Tools / Timefold(Java)」。

---

## 附:本次評估的可還原性
- 於 `feat/docling-eval-poc` 分支進行;Docling **未寫入 requirements.txt**,
  PoC 預設 `EXTRACTOR=native`(行為與現狀完全一致),不安裝 docling 時零影響。
- 多租戶 RLS、Timefold 兩項為純文件/決策更新,無程式風險。
