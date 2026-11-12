# GitHub 運行指南 v1.1.0

## 能做什麼

此版本新增 GitHub Actions：推送／PR 自動測試，以及手動觸發示範或批次報價核對。GitHub 執行的是 Python 程式；不會僅因放入 SKILL.md 就自動出現能理解郵件的 AI Agent。AI 擷取需要另外接模型及文件服務。

工作流程預期專案內容位於 repository 根目錄（根目錄直接有 .github、scripts、tests、examples），不可再包一層資料夾後直接推送。遠端執行狀態以 Actions 頁面為準。

## 廠商試用步驟

1. 公開範例可 Fork 到自己的帳號；正式公司環境建議另建 private repository。上傳完整內容，包含隱藏的 `.github` 與 `.gitignore`，確認 repository 能看到 `.github/workflows/`。
2. 啟用 Actions，確認公司的 Actions 與 artifact 使用政策允許。費用與配額依帳戶方案，不假設免費或無限執行。
3. 開啟 Actions → Run RFQ batch → Run workflow，mode 選 demo。工作流程需已存在預設分支。
4. 完成後下載該次執行的 rfq-output artifact，查看報價草稿及 reconciliation.json。示範用固定虛構日期，與當日無關。
5. 測試 batch 時使用非敏感測試資料，目錄內提供 quote-request.json，po.json 可選。batch 會以執行當日檢查有效性；示範資料過期後跑 batch 被阻擋是正常現象。
6. REVIEW_REQUIRED 回傳 exit 2，因此 Actions 顯示失敗，結果仍會上傳；INVALID_INPUT 為 exit 1。成功也只是草稿處理完成，未核准、未寄送、未建 ERP 訂單。

## 平台分工

| 項目 | 適合位置 |
|---|---|
| 原始碼、版本、測試、部署流程 | GitHub repository + Actions |
| 有限時間的批次計算／核對 | Actions，需評估配額與排程限制 |
| 持續提供 HTTPS API／接 webhook | 正式應用主機或雲端服務 |
| 案件、核准、去重鍵、outbox | 持久資料庫 |
| 詢價原件與報價文件 | 公司文件庫／物件儲存 |
| 公司內網 ERP 查詢或批次橋接 | 經授權的內網服務，或受限的 self-hosted runner |

GitHub Pages 是靜態網站服務，不能執行 Python API 或保存交易狀態；也有用途限制，不應當作這個商業交易產品的正式託管選項。Actions 的 GitHub-hosted runner 是工作執行環境，不能依賴它作為常駐伺服器。Codespaces 適合開發，不能當成正式服務的可用性承諾。

## 正式商用建議

GitHub 推送 → Actions 測試 → 建立版本 → 部署到公司伺服器／雲端應用主機 → 常駐後端接信箱與 ERP。

後端設有：登入與角色、文件解析、模型工具呼叫、案件資料庫、版本核准、outbox worker、服務端權限、監控及備份。這些尚未包含在此版本中；這次新增的是 GitHub 執行入口，沒有假裝已完成完整後端。

## ERP 與 self-hosted runner

如果 ERP 只能內網存取，可以在公司授權的主機安裝 self-hosted runner，讓指定 Actions 批次工作查詢內網。但運算主機、維護和資料權限仍由公司負責，並不是 GitHub 代管了 ERP 後端。

不要直接把現有公共 PR 測試工作流改成跑內網 runner。另設 private repository／runner group、允許的工作流程、保護分支及環境審核；不執行不可信 PR 程式。正式 ERP 寫入仍須整合契約中的核准、唯一 action key 與回執查證。現有 workflows 沒有 ERP 寫入程式。

## 自動更新與資料

- 程式改動會觸發測試；尚無自動部署工作流，不會自動更新廠商主機。
- 主檔可透過後端即時 API 或同步更新；本版只讀 JSON，不會自動同步。
- Actions 工作之間不能把本機 SQLite 或 out/ 當成持久資料庫；cache／artifact 也不作正式交易帳本。
- 排程可能延遲，不提供即時接單保證。正式 webhook 先到後端，再視需要發起批次工作。
- 成本與客戶原件不要提交進 Git 歷史。現有手動 workflow 僅適合非敏感測試資料；正式資料需要另外做已授權的資料庫／文件庫讀取 adapter。
- Artifact 含完整內部報價，非客戶可公開文件；公開 repository 只使用虛構資料。目前保留一天，仍須遵守公司政策與存取權限。
- 憑證用 Secrets／Environment 或支援的短期身分機制，不寫入 repository；本版示範不需要任何憑證。

## 維護

Actions 目前使用官方主要版本標籤。正式環境應依組織政策鎖定審查過的 commit SHA、管理版本更新，並在更新前跑回放測試。部署工作流只在目標平台與環境決定後加入，避免產生不可執行的假部署設定。
