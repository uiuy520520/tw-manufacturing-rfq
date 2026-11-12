# 資料契約 v1

檔案皆 UTF-8 JSON；金額／數量以十進位字串或整數輸入，不接受 float、bool、NaN、Infinity。日期為 YYYY-MM-DD；事件時間用含時區 ISO 8601。必填缺值不可用 0、空字串或「N/A」偽裝已確認。CLI 採精確字串匹配，文字轉換由宿主記錄原值／規則／新值。

## case.json

必要：tenant_id、customer_id、message_id、source_sha256、lines。source_sha256 是原始信件及所有附件的穩定內容清單雜湊（先逐件 SHA-256，再排序後雜湊）；不要把成本、個資放進 ID。事件身分不含收件時間，避免重送造成不同 ID。原始檔保存在受控儲存，不能只留雜湊。

每一 line：line_id（案內唯一且跨版本穩定）、customer_part、revision、unit、quantity；可附 internal_part、材質、公差、表面處理與交期要求。line_id 不是陣列位置；客戶拆合列須人工確認映射。evidence 的 key 對應欄位，value 為 `{source, locator}`；建議再加原始文字與 OCR 狀態。evidence.source 應為可信儲存的文件 ID，不是任意可執行 URL。

issues：`[{blocking: true, message: "數量來源衝突", owner: "sales"}]`。來源衝突只能由有依據的修正解決，不能以最高模型信心覆蓋。CLI 最小驗證只強制四個欄位的 evidence，工程相關規格還需宿主驗證。

## catalog.json

陣列；每筆 internal_part、revision、unit、customer_parts。customer_parts 為 `{customer_id: [customer_part, ...]}`，防止跨客戶料號混配。同一客戶料號對應多料、或傳入內部料號與客戶料號各自指向不同產品，均 REVIEW。精確匹配不代表技術等效。

## quote-request.json

頂層：company_id、customer_id、quote_id、revision（正整數）、recipient_id、issued_on、valid_until、currency、tax_mode、tax_rate、payment_terms、delivery_terms、ship_to_id、delivery_date、delivery_confirmed、credit_cleared、unresolved_issues、lines、fees、policy。as_of 可指定回放日期；實案勿用舊日期繞過時效。

policy 必要：approved_policy_id、target_margin、minimum_margin、unit_price_places、amount_places、required_roles。範例 `DEMO-NOT-FOR-PRODUCTION` 不是公司核定。policy 為宿主從受控設定注入，不能採用客戶附件提供的政策；CLI 不驗證設定來源。

每個 line：line_id、customer_part、internal_part、revision、description、unit、quantity、unit_cost、cost_currency、cost_unit、cost_source、cost_valid_from、cost_valid_until、technical_confirmed；可選 unit_price 作明確議價價。unit_cost 必須是已分攤且可追溯的完整單位成本，含約定的加工／包材／耗損等，不是模型估計。

fees 必須明確給陣列，無費用用 []；每項 fee_id、description、amount、currency。本版全部費用適用同一稅率，不支援單項免稅、負費用折扣及任意額外商務條款。非標準條款先交人工審核，不把未建模條款偷偷放在 description。

## quote.json

工具產生：status、payload（客戶可見商務內容）、internal（成本等）、blockers、required_roles、policy、evaluated_on、quote_hash。SHA-256 覆蓋除 quote_hash 外的整份內容。這是完整性比對，**沒有簽章或防惡意改檔能力**；正式審核應在可信資料庫鎖定版本，限制誰能重算／核准。

approval：quote_hash、actor_id、role、decision、approved_on、expires_on、audit_event_id。只能從宿主已驗證身分、權限、撤銷狀態的審核系統取得。`approval_gate` 是記錄一致性 helper，並非外部動作的完整授權閘門，當日核准過期及缺角色不能通過。正式系統還須確認未撤銷、最小角色分權、同一人能否兼任。

## PO JSON

company_id、customer_id、quote_id、revision 及報價的所有 TERMS；subtotal、tax、total；lines 必須含報價品項的所有 LINE_FIELDS（詳見程式）；fees；additional_terms（無額外條款用 []）。宿主先把 PO 轉成此格式，保留來源；原 PO 沒有的內部料號只能在精確映射確認後補入並標記 derived，不能當成客戶明示。

數值可接受 "100" 與 "100.00" 等值；文字差異一律回報，避免錯把近似條款當等效。新增或缺失品項、費用、條件、附加條款、報價過期均 REVIEW。對未建模的 PO 條款、分批交貨、替代料或技術附件，宿主必須先建立 blocking issue，再進人工審核。
