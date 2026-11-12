# 台灣製造業詢報價與訂單核對 AI Agent Skill

**tw-manufacturing-rfq · v1.1.0 · Python 3.10+ · 繁體中文**

把客戶詢價整理成可審核的報價草稿，並核對採購單差異。適合零組件、加工、設備供應商，以及需要開發詢報價自動化的團隊。

本專案包含 Agent Skill、Python 工具、GitHub Actions、資料契約與整合規格。**目前提供離線與批次功能；常駐後端、OCR、模型 API、信箱及 ERP 連接器仍需另行開發。** 所有範例資料均為虛構。

## 公開下載

**[直接下載完整專案 ZIP](https://github.com/uiuy520520/tw-manufacturing-rfq/archive/refs/heads/main.zip)** · [瀏覽原始碼](https://github.com/uiuy520520/tw-manufacturing-rfq) · [查看測試與執行紀錄](https://github.com/uiuy520520/tw-manufacturing-rfq/actions)

在本 GitHub 儲存庫頁面選 **Code → Download ZIP**，即可下載完整專案。公開原始碼下載不需登入。這是 GitHub 原始碼下載方式，不代表已有 Release 附件。

安裝 Skill 時，將解壓後資料夾命名為 `tw-manufacturing-rfq`，保留 scripts、references、assets 等附檔。執行程式時，請在解壓後的專案根目錄操作。

## 功能與項目

| 項目 | 已提供內容 |
|---|---|
| 詢價建案 | 依客戶、郵件及來源雜湊去重，保留事件衝突 |
| 文件擷取 | Agent 操作規範及來源格式；實際 PDF/Excel/OCR 由宿主工具提供 |
| 完整性檢查 | 品項、數量、單位、版本、來源與阻擋問題 |
| 料號匹配 | 客戶專屬對照與精確匹配，歧義交人工確認 |
| 報價計算 | Decimal 計價、毛利檢查、費用及單一稅率 |
| 草稿產生 | JSON 與 Markdown，客戶輸出隔離成本欄位 |
| 審核輔助 | 報價雜湊、角色與期限檢查；身分由可信宿主驗證 |
| 訂單核對 | 料號、版本、數量、單價、費用與商務條件差異 |
| GitHub 運行 | 自動測試及手動 demo/batch |
| 企業整合 | 信箱、主檔、審核、ERP 與 outbox 設計契約 |

## 三分鐘試跑

需要 Python 3.10+，無第三方套件依賴。在專案根目錄執行：

```bash
python3 scripts/run_batch.py --mode demo --output-dir ./demo-output
```

Windows 可將 `python3` 改為 `py -3`；執行環境需有 Asia/Taipei 時區資料，缺少時可使用 WSL/Linux/Actions。

會產生：

```text
demo-output/
├── quote.json
├── customer-draft.md
├── reconciliation.json
└── demo-summary.json
```

示範使用固定日期 2026-11-12。成本 80、數量 500、目標毛利 20%、治具費 2,000、示範稅率 5%，總額 **54,600**。PO 支援欄位一致；尚未核准、寄信或建立正式訂單。

## GitHub 上執行

1. Fork 專案到自己的帳號，啟用 Actions。
2. 開啟 **Actions → Run RFQ batch → Run workflow**。
3. 選擇 `demo`，完成後下載 `rfq-output` artifact。
4. 批次測試選 `batch`，提供含 quote-request.json 與可選 po.json 的 repository 相對目錄。

batch 以執行當日檢查效期，固定範例過期後被阻擋是正常現象。demo 維持固定日期。公開 repository 及 artifact 只能放非敏感測試資料；真實客戶、成本與憑證不能提交到公開 Git 歷史。下載 Actions artifact 可能需要登入與存取權，與公開原始碼 ZIP 不同。

詳細步驟：[GitHub 運行指南](GITHUB運行指南.md)。GitHub 執行的是 Python 工具；僅放入 SKILL.md 不會自動產生 AI Agent。

## 安裝到 Agent

將完整資料夾放入宿主的 skills 目錄，例如專案級 Codex：

```text
.agents/skills/tw-manufacturing-rfq/
├── SKILL.md
├── scripts/
├── references/
└── ...
```

其他支援 Agent Skills 的宿主可使用相同結構；探索、重載與工具權限依宿主版本確認。宿主需要檔案及 Python 執行能力。

建議提示：

> 使用 tw-manufacturing-rfq 整理這次詢價，檢查品項、規格、數量、單位與來源。先完成能做的部分，列出缺漏並產生可審核的報價草稿，不猜測成本、交期或公司政策。

## 工作流程

```text
收件 → 擷取 → 缺漏/衝突檢查 → 補件 → 料號匹配
→ 成本與交期確認 → 計價 → 報價草稿 → 核准
→ 授權後寄送 → 採購單差異核對 → 授權後 ERP 建單
```

目前工具不執行寄信、核准人身分驗證或 ERP 寫入。

## 個別指令

```bash
python3 scripts/rfq.py intake --input examples/case.json --db ./out/cases.sqlite
python3 scripts/rfq.py validate --input examples/case.json
python3 scripts/rfq.py match --input examples/case.json --catalog examples/catalog.json
python3 scripts/rfq.py quote --input examples/quote-request.json --output ./out/quote.json
python3 scripts/rfq.py render --input ./out/quote.json --output ./out/customer-draft.md
python3 scripts/rfq.py reconcile --quote ./out/quote.json --po examples/po.json --as-of 2026-11-12
```

以上為固定日期回放；正式 batch 強制用執行當日。原始 quote 指令可接受 as_of，正式系統須由可信宿主控制日期。

可信審核系統提供紀錄後，可執行：

```bash
python3 scripts/rfq.py approval-check --quote ./out/quote.json --approvals /path/to/verified-approvals.json
```

| Exit code | 意義 |
|---|---|
| 0 | 支援範圍內處理完成，仍可能是待核准草稿 |
| 1 | 輸入或執行錯誤 |
| 2 | 有 blocker、差異或需審查；草稿可能已產生 |

## 系統整合與商業化

建議由 GitHub 管版本、測試與部署；正式後端管理案件、登入、審核及工具呼叫；資料庫保存版本與 outbox。

| 服務 | 介面方向 | 狀態 |
|---|---|---|
| 信箱 | Microsoft Graph/Gmail 官方 API | 契約已定義，連接器待實作 |
| 文件及 AI | 宿主工具、OCR、模型 API | 規範已定義，服務待接入 |
| ERP 查詢 | 官方 API/SDK/核准的唯讀介面 | 依 ERP 版本與授權實作 |
| ERP 建單 | 官方 API/核准匯入 | 需核准、防重複及回執 |
| 排程通知 | 常駐 worker/排程服務 | 狀態規則已定義，服務待實作 |

先導入標準品、單一產品線與草稿模式，再接唯讀 ERP，最後開放核准後寫入。商業化仍需權限、監控、備份、真實資料驗收與明確授權條款。

## 限制

- 單一幣別、未稅、單一稅率；TWD/USD/EUR/JPY 不代表自動換匯。
- 不支援混合稅率、含稅反推、拆合單、替代料、階梯合約自動選價與實際產能排程。
- 過期成本、低毛利、未知計價欄位及匹配歧義會阻擋或要求審查。
- 報價雜湊是版本一致性控制，不是數位簽章或身分驗證。
- 客戶輸出採欄位白名單，自由文字仍需檢查機密；工程等效與來源真實性仍需公司確認。
- 本機 SQLite 去重不能代替跨系統 outbox 或保證 exactly-once。

## 文件索引

| 文件 | 內容 |
|---|---|
| [SKILL.md](SKILL.md) | Agent 操作入口 |
| [使用說明](使用說明.md) | 安裝、呼叫與實際導入 |
| [GitHub 運行指南](GITHUB運行指南.md) | Actions、平台分工、資料與部署 |
| [工作流程](references/workflow.md) | 角色、狀態機與跟進 |
| [資料契約](references/data-contract.md) | 欄位、格式及來源 |
| [計價規則](references/pricing.md) | 毛利、捨入、稅額與有效性 |
| [整合契約](references/integrations.md) | API、核准、重試與 outbox |
| [驗收清單](references/acceptance.md) | 測試、缺點與上線條件 |
| [版本紀錄](CHANGELOG.md) | 版本改動 |

## 測試與問題回報

```bash
python3 -m unittest discover -s tests -v
```

目前 36 項本機測試涵蓋計價、捨入、過期成本、匹配、核准、PO 差異、批次日期與路徑檢查。遠端 Actions 狀態以 GitHub 實際紀錄為準。

回報問題請提供版本、命令及去識別化的最小案例；不要在公開 Issue 上傳客戶文件、成本或憑證。

## 授權

本專案採用 [MIT License](LICENSE)，允許使用、修改、商用及再散布，須保留版權與授權聲明。軟體依現狀提供，不提供擔保；完整條款請見 LICENSE。
