# AFC Workspace 操作手冊 v0.8.6

本手冊說明如何用一套 AFC runtime 管理多個來源資料夾，並依 KB ID 將
知識整理、更新、查詢和移植。KB ID 是日常選擇知識庫所需的唯一識別碼；
Release ID 由系統內部管理，僅在稽核或回復時查看。

## 1. 安裝

AFC 全套 runtime 最低要求為 Python 3.10。先設定要使用的直譯器，再安裝套件和依賴；啟動器會在所有命令執行前檢查版本。

```bash
export AFC_PYTHON="$(command -v python3.10)"
"$AFC_PYTHON" --version
```

在目標專案中安裝套件。`--target` 決定技能與規則裝到哪個 harness 讀得到的位置，
`both` 為預設值：

```bash
bash install.sh /path/to/project --target both
```

| target | 技能安裝位置 | 規則檔 | plugin manifest |
| --- | --- | --- | --- |
| `codex` | `.codex/skills`、`.agents/skills` | `AGENTS.md` | `.codex-plugin/plugin.json` |
| `claude` | `.claude/skills` | `CLAUDE.md` | `.claude-plugin/plugin.json` |

兩個 target 的技能、腳本、設定與規則都是同一份來源檔案，target 只決定落點；
`verify_install.sh` 會在兩份安裝副本不一致時失敗。單一 target 也可以用
`install_codex.sh` 或 `install_claude.sh` 這兩個包裝腳本。

安裝完成後驗證：

```bash
bash verify_install.sh /path/to/project --target both
```

必要依賴安裝方式：

```bash
"$AFC_PYTHON" -m pip install -r /path/to/project/.afc-card-experiment/requirements.txt
```

圖片與掃描 PDF 使用本機 OCR。需要另外安裝 Tesseract、文件所需語言包，
以及 PDF 頁面渲染依賴：

```bash
"$AFC_PYTHON" -m pip install -r /path/to/project/.afc-card-experiment/requirements-ocr.txt
```

沒有安裝 OCR 時，流程仍會保留圖片或掃描頁來源單位，但會將文字辨識列為
待處理；不會自動把來源送到多模態模型。

### 選用：程式碼結構解析

Java、Flutter/Dart、Ionic 的 JavaScript/TypeScript／HTML 模板、PHP 結構解析是選用功能；
它使用同一個 Python 3.10+ runtime，只有程式碼語法檔需要額外下載。
安裝完成後預先下載語法解析器：

```bash
"$AFC_PYTHON" -m pip install -r "$(./afc --home)/requirements-code.txt"
./afc prepare_code_parser.py
```

第一次準備 parser 需要網路連線；完成後語法檔留在 AFC runtime 的本機快取，掃描時
不需再次下載。

## 2. 初始化工作區目錄

工作區目錄是由 `workspace.py` 維護的 JSON 檔，預設位於專案根目錄的
`afc-workspace.json`。使用命令新增和修改項目，不必手動編輯它：

```bash
cd /path/to/project
./afc workspace.py init
```

查看已登錄的 KB、來源資料夾和目前接受版本：

```bash
./afc workspace.py list
```

KB 根目錄可放在專案外。路徑會相對於工作區目錄保存；同一工作區搬移時，
相對路徑可維持可用。來源文件不會因登錄而複製或移動。

## 3. 建立領域知識庫

每個 KB 管理一個連貫知識領域。商品知識設定 `product`；沒有商品適用性的
通用知識設定 `not-applicable`。

建立汽車險 KB，並登錄多個相關文件目錄：

```bash
./afc workspace.py init-kb \
  --kb-id auto-insurance \
  --name "汽車險" \
  --kb-root ../knowledge/auto-insurance \
  --scope-policy product \
  --source ../product-docs/auto/cproduct \
  --source ../shared-docs/auto-policy
```

建立不需要商品 Scope 的 PMP 參考 KB：

```bash
./afc workspace.py init-kb \
  --kb-id pmp \
  --name "PMP" \
  --kb-root ../knowledge/pmp \
  --scope-policy not-applicable \
  --source ../study/pmp
```

KB ID 只能使用小寫英文字母開頭，後接小寫字母、數字、點、底線或連字號，
最多 64 字元。建立後不要把同一 ID 改指向另一個知識庫；若領域更名，保留
原 ID，更新顯示名稱。

為既有 KB 登錄來源目錄：

```bash
./afc workspace.py register \
  --kb-id pmp --name "PMP" \
  --kb-root ../knowledge/pmp \
  --scope-policy not-applicable \
  --source ../study/pmp
```

新增或移除來源目錄：

```bash
./afc workspace.py add-source --kb-id pmp --source ../study/pmp-updates
./afc workspace.py remove-source --kb-id pmp --source ../study/pmp-updates
```

一個 KB 可以有多個來源目錄，也可以同時收文件、試算表、PDF、文字資料和
程式碼，只要它們共同支援同一領域。不要只因檔案格式不同就建立另一個 KB。

## 4. 決定產品 Scope

`product` KB 的單次掃描需要明確 Scope。可在 prompt 指定，或在來源目錄放
`afc-scope.md`：

```markdown
## 預設 Scope
- `CA` — 汽車險

## 排除 Scope
- `CB`
```

最近的 `afc-scope.md` 套用到該目錄；子目錄可以建立自己的檔案。排除 Scope
仍有效，除非使用者在本次執行中明確要求覆寫。

若既沒有 prompt Scope，也沒有目錄預設，來源會標記為 `Needs Scope`，不會
進入可萃取清單。Business Context 對照表是選用的名稱映射；已明確提供 Scope
時不需要它。

`not-applicable` KB 表示商品 Scope 不適用，例如 PMP 或多語系參考知識。它不
代表「忘了設定 Scope」。來源目錄仍是硬邊界。

## 5. 掃描並解析來源

每次先指定 KB ID 和本次知識目標。沒有指定來源子集時，使用該 KB 登錄的所有
來源目錄；若指定子集，只能在已登錄目錄內選擇：

```bash
./afc workspace.py inventory \
  --kb-id pmp \
  --behavior "完整萃取 PMP 濃縮講義的知識"
```

只掃描某個已登錄子目錄：

```bash
./afc workspace.py inventory \
  --kb-id auto-insurance \
  --source ../product-docs/auto/cproduct \
  --behavior "乘客險加買條件"
```

只有涵蓋該 KB 所有登錄來源根目錄的完整盤點，才可加
`--complete-boundary`。局部掃描不要使用它，以免把未掃描來源誤判為移除。

盤點會建立 `runs/<run-id>/candidate/eligible-source-paths.json`。透過統一派送器
解析這份清單，避免掃到未選取的檔案：

```bash
./afc parse_sources.py \
  --kb-id pmp \
  --eligible-list ../knowledge/pmp/runs/<run-id>/candidate/eligible-source-paths.json \
  --output-dir work \
  --pdf-profile article
```

`--pdf-profile article` is opt-in for article/study-guide PDFs; omit it to keep
the fast legacy PDF path. After changing the profile, inventory with
`--rescan-unchanged` so unchanged PDFs are parsed again.

派送器目前會選擇下列解析器。圖片不是獨立輸入格式：先由 Word、Excel 或 PDF
解析器輸出嵌入圖片／掃描頁，再依 `afc-context` 的 OCR 步驟處理。

- DOCX、XLSX／XLSM、PDF：結構式文件解析；
- Markdown、文字、CSV、JSON、YAML、XML：文字／表格解析；
- 圖片及掃描 PDF 頁：先由本機 OCR 擷取，再保留信心度及來源位置；
- Python：標準 AST 解析模組、類別、函式、匯入、呼叫和行號；
- Java、Dart、JavaScript、TypeScript、PHP、HTML／HTM 模板：Tree-sitter 靜態語法樹解析；
- Vue 單檔元件：解析 template、script，並依 script 的 JS/TS 標記擷取符號；
- CSS／SCSS：解析樣式規則。

Flutter 以 Dart 語法解析；Ionic 的 Angular、React、Vue 專案以 TS/JS、TSX/JSX、Vue
及 HTML 模板解析。這是靜態語法結構，不會執行程式、解析型別、建置專案或推斷執行期
行為。Kotlin、Go、Rust、Ruby、C#、C/C++ 等其他程式語言仍會列為 `unsupported`。
若未安裝可選 parser，程式碼會保留原始模組文字並在報告標為未完成結構解析。

模組與類別／函式單位可能涵蓋相同行數；萃取 Evidence 時須依來源檔案和行號去重。
解析後先看
`work/step-card-0-*-structure-report.json` 和不支援來源報告，再進行 Context
選取。解析器、OCR 或來源範圍改變時，依 inventory 指示使用
`--rescan-unchanged`。

## 6. 執行知識萃取與發布

AFC 的一般 Step 0–6 流程仍由 `afc-pipeline` 執行；`afc-workspace` 負責選定
KB、來源根目錄、Scope 政策和持久化位置。使用下列指令形式啟動：

```text
Use afc-workspace to process KB ID `pmp`.
Use the inventory run and its eligible source list.
Analyze the selected source folders for the requested behavior.
This is a Scope-neutral reference KB. Run the full AFC pipeline, review all
unsupported structures and OCR gaps, then stage the changes for my decisions.
Do not publish until every proposal has my explicit decision.
```

商品知識需補上 Scope 指示，例如「本次 Scope 為 CA」；通用知識不需要提供
Business Context 或商品 Scope。若要完整建立首次通用知識庫，使用者可明確要求
完整萃取，再由 Context 步驟將解析後的內容交給 Cards 萃取。只針對單一行為時，
使用該行為的主題詞作為 anchors，避免整份文件無關內容進入候選集。

多個 KB 必須依序處理，不能交錯共用 `work/`、`output/`。每個 KB 的候選資料
都要在該 KB 下 stage、審閱、決策和 publish。未經使用者逐項決定的提案不可
發布。

## 7. 查詢

只查一個領域：

```bash
./afc workspace.py query \
  --kb-id pmp \
  --query "風險應對有哪些策略？"
```

明確跨兩個領域查詢時，重複指定 KB ID：

```bash
./afc workspace.py query \
  --kb-id pmp \
  --kb-id auto-insurance \
  --query "有哪些風險應對要求？"
```

跨 KB 時工具會分別查詢並標示 KB ID。回答應維持來源分層；只有證據支持時才
綜合不同 KB 的結論。系統預設讀取每個 KB 的目前接受版本，使用者不必輸入
Release ID。

查詢詞彙會優先使用知識庫移植包中的 `config/query-terms.yaml`。從 v0.8.2
升級時，第一次查詢會自動重建舊版索引，後續查詢使用新版索引。

## 8. 討論並收納知識變更

發現缺漏、衝突、過時答案或證據問題時，先用 `afc-discuss` 調查指定 KB，
比較目前接受知識與來源證據，並把討論結論和未解問題收納成討論紀錄。此時
不改動接受版本。若 KB、Scope、Box 或 Domain Key 有多種會影響結論的解讀，
先請使用者確認。

討論紀錄標記 `Ready for Update` 並由使用者確認後，再用 `afc-update` 形成
正式變更提案。盤點和解析仍使用原 KB ID；提案只在該 KB 的 run 下 stage。
逐筆記錄接受、拒絕或延後與理由，全部提案都有明確決定後才發布，並重建該 KB
索引。討論共識用來描述預期知識變更；提案決定則授權哪些物件進入接受版本。

範例：

```text
Use afc-discuss for KB `cproduct`. Investigate the passenger insurance add-on
period conflict, collect source evidence and alternatives, and save a discussion
record. Do not change the accepted release.
```

```text
Use afc-update to turn the `Ready for Update` discussion record for KB
`cproduct` into release proposals. Show me every proposal for an explicit
accept, reject, or defer decision before publishing.
```

來源內容改變時由雜湊觸發增量掃描；只更改萃取目標或 parser／skill 版本時，
使用 `--rescan-unchanged` 重新處理原始來源。

## 9. 移植到另一台電腦

輸出指定 KB 的已接受快照：

```bash
./afc workspace.py export --kb-id pmp --output ./dist/pmp.afc-kb.zip
```

另一台電腦安裝相容 AFC runtime 後匯入，再登錄本機路徑：

```bash
./afc knowledge_pack.py import \
  --archive ./pmp.afc-kb.zip \
  --kb-root ../knowledge/pmp
./afc knowledge_base.py validate --kb-root ../knowledge/pmp
./afc knowledge_base.py index --kb-root ../knowledge/pmp
./afc workspace.py register \
  --kb-id pmp --name "PMP" --kb-root ../knowledge/pmp \
  --scope-policy not-applicable --source ../study/pmp
```

預設包不含原始文件、暫存 run 或可重建的索引。原始文件若需在接收端開啟，
需另行移轉。知識庫包會保留 KB ID、接受版本、Evidence 和治理歷史；接收端
的來源目錄可以不同，但必須更新 workspace catalog。

## 10. 技能範圍限制

每個技能都在 `config/skill-scopes.yaml` 宣告它可以執行哪些腳本，以及它最多能造成
哪一級變更（`read-only` / `work` / `release`）。跟著某個技能工作時，把 `AFC_SKILL`
設成那個技能的名稱：

```bash
export AFC_SKILL=afc-cards      # 接著執行該技能的命令
```

啟動器會拒絕範圍外的命令，並指出該命令屬於哪個技能。這是為了讓「技能不要順手做掉
下一步的工作」變成可檢查的限制，而不是寫在散文裡的期望——查詢時不會回頭重掃來源、
驗證時不會順手發布、找不到答案時不會自己補一張卡。

```bash
./afc --scope afc-validate      # 看某個技能的邊界
```

不設定 `AFC_SKILL` 就不會檢查，那是給直接操作用的；不要用它來繞過一次拒絕。
需要調整邊界時改 `config/skill-scopes.yaml`，再執行
`./afc sync_skill_metadata.py --write` 讓每個 SKILL.md 的 Scope 段落與
`allowed-tools` 跟著更新；兩邊不一致時自我測試會失敗。

## 11. 常用檢查

```bash
./afc workspace.py list
./afc check_environment.py
bash /path/to/afc-card-experiment-v0.8.6/verify_install.sh .
```

工作區 catalog 是程式維護的登錄資料，建議納入專案版本控制以保留 KB ID 和
來源目錄對應；不應把使用者原始文件放進 AFC runtime 安裝目錄。
