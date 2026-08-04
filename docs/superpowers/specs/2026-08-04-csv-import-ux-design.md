# 自助 CSV 匯入強化（範本／逐列錯誤／預覽）Design

- **狀態**：Approved (design)
- **日期**：2026-08-04
- **對應**：PRD EPIC-1.2 (c)、Roadmap 卡片 A6
- **一句話**：讓「把自己的資料餵進來」這件事在按下匯入**之前**就看得見結果，而且錯了知道錯在哪一列、哪一欄、該改成什麼。

---

## 1. 目標與觀眾

主要觀眾有兩層，都要服務，但先跑通第二層：

1. **售電業的營運人員**——拿自家 Excel 導出的檔來餵，欄名不一定對、日期格式不一、可能有 BOM 與全形數字。他們要的是「真的擋得住髒資料，並告訴我怎麼修」。
2. **現場 demo**——在客戶面前匯一份檔，讓對方看到「資料進得來、錯了看得懂」。

驗收的一句話：**預覽說會進 12 筆，按下去就是 12 筆。**

## 2. 現況與問題

| 位置 | 問題 |
|---|---|
| `web/app.js:2573` `IMPORT_COLS` | 欄位清單在前端手寫，**已經過期**：合約缺 `monthly_shares` / `min_offtake_percent` / `price_escalation_percent` / `price_base_year`，案場缺五個風電工程屬性，客戶缺 `green_target_type` / `target_energy_mwh`。等於 UI 從沒告訴任何人這些欄位可以匯入 |
| `csv_importer.py` | 錯誤是 `f"row {n}: {exc}"` 的原始 Python 英文字串，中文頁面印英文 |
| `web/app.js:2612` | 前端只顯示前 5 筆錯誤 |
| `web/app.js:2615` | modal 4 秒後自動關閉，錯誤還沒讀完就消失 |
| `csv_importer.py` | `DomainError` 一律吃掉算 `skipped`，使用者不知道為何被略過 |
| 全域 | 沒有 dry-run，按下去就直接寫進資料庫 |
| `measurements.create_generation()` | **沒有重複檢查**，同一份發電 CSV 匯兩次資料直接變兩倍，而發電量是結算金額的分母之一 |
| `batteries` | `csv_importer.import_batteries()` 存在但**沒有 `/batteries/import` 端點**，只有 `tests/conftest.py` 呼叫得到 |
| `generation` / `consumption` | 後端 `/import` 端點有，SPA 沒有入口 |
| `web/app.js:2477` | `var editMode = true` 從未被改寫，三處 `if (!editMode) return ""` 是死碼 |
| `_lookup_id()` | 每列查一次 DB（合約每列兩次），一萬列即兩萬次查詢 |

根因不是「少做了範本下載」，是**欄位清單沒有單一真相**、**驗證只能在寫入時才發生**。

## 3. 已定決策

| 項目 | 決定 |
|---|---|
| 預覽架構 | **後端 dry-run**（方案 A）。前端本地解析（B）會產生第二份驗證邏輯，預覽全綠、按下去一半失敗正是最難堪的失敗模式；staging 表（C）對現在的資料量是過度設計 |
| dry-run 隔離 | 綁 connection ＋ `join_transaction_mode="create_savepoint"`，**service 與 repository 一行不改** |
| API 契約 | `ImportResult` **新增**結構化欄位，`errors: list[str]` 保留並由結構化結果推導 → 現有測試與 SPA 不斷 |
| 錯誤呈現 | 依 (欄位 × 錯誤種類) **分組**，不是截斷列數 |
| upsert | 納入本次範圍（重複匯入改為更新而非靜默略過） |
| 匯入入口 | 補齊 generation / consumption / battery |
| `editMode` | 死碼移除 |

## 4. 架構

### 4.1 欄位表成為單一真相（新檔 `app/ingestion/schema.py`）

`IMPORT_COLS` 會過期不是意外，是結構問題——欄位清單在前端手寫一份、importer 手寫另一份，沒有東西逼它們一致。

```python
Kind = Literal["str", "float", "int", "date", "enum", "shares"]

@dataclass(frozen=True)
class Column:
    name: str            # CSV 欄名，如 "installed_capacity_mw"
    label: str           # 中文說明，如 "裝置容量 (MW)"
    kind: Kind
    required: bool = False
    example: str = ""    # 範本的示範值
    note: str | None = None   # enum 允許值、月別配比格式…

@dataclass(frozen=True)
class EntitySpec:
    entity: str                  # "farm" | "customer" | ...
    label: str                   # "發電案場"
    natural_key: tuple[str, ...] # 判定 create vs update 的欄位
    columns: tuple[Column, ...]
```

一份 `SPECS: dict[str, EntitySpec]` 同時餵四個消費端：

1. importer 讀哪些欄
2. 範本下載的標題列與示範列
3. UI 的欄位說明（前端不再自己寫）
4. 錯誤訊息裡的欄位中文名

加欄位時漏改的可能性從「四處」降到「一處」，其餘由 §7 的漂移測試釘住。

本次一併補上目前 UI 沒揭露的欄位：合約四個深化欄位、案場五個風電工程屬性、客戶兩個綠電目標欄位。

### 4.2 dry-run 怎麼保證不落地

陷阱：`BaseRepository.create()` 內部就 `db.commit()`，所以「跑完驗證再 rollback」在現有結構下做不到——service 早就 commit 了。

解法不動 service 也不動 repository。**關鍵是不要另開連線**：`tests/conftest.py` 用 `sqlite://` ＋ `StaticPool`，整個 engine 共用同一條 DBAPI 連線，`engine.connect()` 拿到的就是外層 session 正在用的那條，`conn.begin()` 會直接撞 `cannot start a transaction within a transaction`。（此路已實測失敗，見下方註記。）

改綁在**外層 session 自己的連線**上做 SAVEPOINT：

```python
@contextmanager
def dry_run_session(db: Session) -> Iterator[Session]:
    """一條與外界隔絕的 session：內層 commit 只釋放 SAVEPOINT，離開時退回。"""
    conn = db.connection()
    sp = conn.begin_nested()
    factory = sessionmaker(bind=conn, join_transaction_mode="create_savepoint")
    scoped = factory()
    try:
        yield scoped
    finally:
        scoped.close()
        if sp.is_active:
            sp.rollback()
        db.expire_all()
```

SQLAlchemy 2.0 在 `create_savepoint` 模式下把內層 `commit()` 變成釋放 SAVEPOINT，外層 SAVEPOINT 不受影響。**驗證路徑與真匯入是同一份程式碼**——這是選方案 A 的整個賣點，不在這裡打折。

**已實測**（2026-08-04，本機 SQLAlchemy 2.x）：

| 做法 | 記憶體 SQLite ＋ StaticPool | 檔案式 SQLite |
|---|---|---|
| `engine.connect()` 另開連線 | ❌ 漏水／`cannot start a transaction within a transaction` | — |
| 綁外層 session 連線 ＋ `begin_nested()` | ✅ dry-run 無殘留、外層事後仍可正常寫入 | ✅ |

**尚未實測：Postgres。** 本機無 Docker，線上為 Neon。機制本身是 SQLAlchemy 的標準用法，但 §4.3.1 的每列 SAVEPOINT 對 Postgres 是**必要**而非優化。

### 4.3.1 每列一個 SAVEPOINT

importer 的語意是「單列出錯就記下來、繼續跑下一列」。在 Postgres 上，交易中一旦有語句失敗，整個交易就進入 aborted 狀態，之後每一句都會被拒絕——**除非退回到某個 SAVEPOINT**。所以每列的寫入要包在自己的 `begin_nested()` 裡，出錯就退回該列的 savepoint：

```python
nested = session.begin_nested()
try:
    ...persist...
    session.commit()
except Exception as exc:
    if nested.is_active:
        nested.rollback()
    ...記錄錯誤，繼續下一列...
```

已實測在 SQLite 下同樣成立：壞列被隔離，dry-run 與真匯入產出**完全相同**的成功列與錯誤列。

### 4.3 共用匯入管線（改寫 `app/ingestion/csv_importer.py`）

現在七個 `import_*` 是七個近乎相同的迴圈。抽出共用骨架，每個實體只留三個小函式：

```python
def run_import(db, spec, rows, *, handler, dry_run=False) -> ImportResult
```

`handler` 提供：

- `build(db, row, ctx) -> payload`（欄位解析與外鍵解析，用 §4.4 的預載 ctx）
- `locate(db, row, ctx) -> object | None`（依自然鍵找既有列）
- `create(db, payload)` / `update(db, existing, payload)`

骨架負責：列號、動作判定、錯誤收集、分組、計數。

### 4.4 外鍵預載，消掉 N+1

進迴圈前把被參照的自然鍵一次撈成 dict（每張表一次 `SELECT code, id`），迴圈內只查記憶體。一萬列從兩萬次查詢降到常數次。dry-run 才可能在合理時間內回應；真匯入也順帶變快。

### 4.5 API 契約

四種動作的定義必須沒有灰帶，否則實作時各憑想像：

| action | 何時 |
|---|---|
| `create` | 自然鍵在 DB 中不存在 |
| `update` | 自然鍵已存在，且 CSV 提供的非空欄位中**至少一欄與現值不同** |
| `skip` | 自然鍵已存在，且**沒有任何欄位會變**（no-op） |
| `error` | 該列無法處理：解析失敗、外鍵找不到、或 service 拋 `DomainError` |

注意 `DomainError` 歸 `error` 而非 `skip`——今天它被靜默算成 skip 正是「不知道為什麼被略過」的來源。

這個定義順帶讓契約保持相容：`tests/integration/test_taipower_contracts.py:76` 斷言重複匯入同一份檔得到 `skipped == 8`，在新語意下這 8 列是既有且無變更的 no-op，**仍然是 skip，測試不需要改**。

```python
class RowResult(BaseModel):
    row: int      # CSV 行號（標題列 = 1，資料首列 = 2）
    action: Literal["create", "update", "skip", "error"]
    key: str | None       # 該列的自然鍵值
    changed: list[str] = []   # action=update 時，會被改動的欄位
    message: str | None = None

class ErrorGroup(BaseModel):
    field: str | None
    message: str              # 中文，這一類的說明
    count: int
    sample_rows: list[int]    # 前 10 個列號
    sample_value: str | None  # 一個實例值

class ImportResult(BaseModel):
    imported: int
    updated: int = 0
    skipped: int = 0
    errors: list[str] = []            # 保留相容，由 error_groups 推導
    error_groups: list[ErrorGroup] = []
    sample_rows: list[RowResult] = []  # 成功／更新的前 20 列
    total_rows: int = 0
    dry_run: bool = False
```

**為什麼分組而不是截斷列數。** 預覽服務三件事，它們對數量的需求相反：決定要不要按下去只需要總數；拿去修檔案需要**每一個**錯誤；確認欄位對上了只需要幾列樣本。錯誤依 (欄位 × 種類) 分組後，payload 由錯誤的**種類數**決定（天生就少），而使用者拿到的資訊反而更有用——他看得出「日期整欄格式不對，共 2,431 列」是系統性問題，一次改完整欄，而不是逐列修。

沒有東西被靜默丟棄：錯誤是被**歸納**，不是被截斷。

### 4.6 端點

新增 `app/api/v1/imports.py`（prefix `/import`），把跨實體的東西集中：

| 端點 | 說明 | 寫入權限 |
|---|---|---|
| `GET /import/schema` | 全部實體的欄位表，前端一次拿完 | 否 |
| `GET /import/template/{entity}` | 標題列＋一列示範值 | 否 |

路徑不寫成 `{entity}.csv`——那會讓 path 參數收到 `"farm.csv"`。檔名由 `Content-Disposition: attachment; filename="farm_template.csv"` 決定，`media_type="text/csv"`。

既有六個 `/import` 加 `dry_run: bool = Query(False)`；補上 `POST /batteries/import`。

範本**帶 UTF-8 BOM**：沒有 BOM，Excel 開中文欄位說明就是亂碼，而範本的整個用途就是給人用 Excel 打開。（`parse_csv()` 已用 `utf-8-sig` 解碼，回灌無虞。）

### 4.7 upsert 語意

| 實體 | 自然鍵 |
|---|---|
| farm / customer / meter / battery | `code` |
| contract | `contract_number` |
| generation | `(wind_farm_id, period_start, period_end)` |
| consumption | `(customer_id, period_start, period_end)` |

規則：

- **只更新 CSV 有給且非空的欄位**。Excel 導出常整欄空白，空白視為「不動」而非「清空」
- 自然鍵本身不可改（改了就是另一筆）
- 預覽的 `update` 列會列出 `changed` 欄位

generation / consumption 的自然鍵順帶關掉 §2 那個「匯兩次變兩倍」的問題。

### 4.8 前端流程（`web/app.js`）

選檔後**自動**送 dry-run，不要求先按「預覽」再按「匯入」——多一次點擊只會讓人跳過預覽。

面板結構：

1. 頂端一列「下載範本」＋欄位說明（讀 `/import/schema`）
2. 三個數字：新增 N／更新 N／錯誤 N
3. 錯誤分組清單：欄位中文名、原因、筆數、列號、實例值
4. 成功樣本表：前 20 列，列號＋自然鍵＋動作徽章
5. 底部「確認匯入」；有錯誤時仍可按，但按鈕明寫「確認匯入（將略過 N 列）」

一併清掉：`setTimeout(close, 4000)`、`errors.slice(0, 5)`、`IMPORT_COLS`、`editMode` 死碼。

### 4.9 錯誤處理

- 解析器改成帶欄位脈絡：失敗時產出「裝置容量 (MW)「abc」不是數字」，不是 `could not convert string to float: 'abc'`
- `DomainError` 不再靜默算 skip → 依 §4.5 歸 `action="error"`，並把 service 的訊息轉成中文原因
- **標題列缺自然鍵是整檔層級錯誤**（見下方「與 §4.7 的協調」），直接說缺哪幾欄，不逐列洗一千行版
- 多餘欄位只警告不擋（Excel 常多欄）
- 空檔／非 CSV／解碼失敗給明確中文訊息

**與 §4.7 的協調（實作階段補記，2026-08-04）**：原稿這裡寫的是「標題列缺**必填**
欄是整檔層級錯誤」，跟 §4.7「只更新 CSV 有給且非空的欄位」是兩條互相矛盾的規則
——一份只給 `contract_number,price_per_kwh` 的 partial-update 檔案，必填欄檢查
會因為缺 `wind_farm_code`／`customer_code`／`start_date`／`end_date` 而把整檔擋
下，即使這份檔案根本不打算建立新合約。專案負責人裁決：**支援 partial update**。
協調後的規則：

- 標題檢查只看**自然鍵**（`_check_header` 讀 `spec.natural_key`，不是
  `spec.required_names()`）。自然鍵缺席仍是整檔層級錯誤——連是哪一列都定不下
  來，逐列報沒有意義。
- 非自然鍵的必填欄（如案場名稱、合約的案場代碼／客戶代碼）留給**逐列**檢查：
  既有列（`update`）的空白視為「不動」，新建列（`create`）的空白由
  `_require_for_create` 攔下，給出一則指名欄位的中文錯誤——不再是整檔層級，
  而是跟其他逐列錯誤一樣，同欄同因會被 §4.5 的分組收斂成一組。

## 5. 檔案異動

**新增**

- `app/ingestion/schema.py` — 欄位表單一真相
- `app/ingestion/template.py` — 由 spec 產生範本 CSV
- `app/api/v1/imports.py` — schema 與範本端點
- `tests/test_import_schema.py`、`tests/test_import_dry_run.py`、`tests/test_import_upsert.py`

**改寫**

- `app/ingestion/csv_importer.py` — 共用管線、外鍵預載、結構化結果
- `app/ingestion/parsing.py` — 帶欄位脈絡的解析錯誤
- `app/schemas/common.py` — `RowResult` / `ErrorGroup` / 擴充 `ImportResult`
- `app/api/v1/{wind_farms,customers,contracts,meters,generation,consumption}.py` — `dry_run` 參數
- `app/api/v1/batteries.py` — 補 `/import`
- `app/api/v1/router.py` — 掛新 router
- `web/api.js`、`web/app.js`、`web/styles.css` — 預覽面板

**不動**：`app/matching/*`（匹配引擎與本次無關）、`app/services/*` 的寫入語意（upsert 走 importer 層，不改 service 契約）

## 6. 風險

| 風險 | 處理 |
|---|---|
| ~~測試環境的 StaticPool 與另開連線互踩~~ | **已解決**：改綁外層 session 自己的連線 ＋ `begin_nested()`，兩種 SQLite 設定都實測通過（§4.2） |
| **Postgres 未實測**（本機無 Docker） | §4.3.1 的每列 SAVEPOINT 就是為此而設。實作完成後**必須在 Neon 或本機 Postgres 上實跑一次含壞列的匯入**，確認錯誤列不會毒死整批。這是唯一還沒證明的假設 |
| 共用管線改寫動到七個 importer，可能回歸 | 先讓現有 import 測試全綠再重構，逐實體遷移 |
| upsert 改變寫入語意，既有使用者預期「重複會略過」 | 預覽明確標示 `update` 與 `changed` 欄位，按下去前看得到；no-op 仍算 skip，語意連續 |
| dry-run 讓每次匯入變兩次請求 | 檔案上限 10 MB 不變；外鍵預載後單次成本大幅下降 |
| 預覽與確認之間資料可能改變（他人同時寫入，或使用者換了檔案） | **接受**。預覽是決策輔助不是鎖；真匯入回傳的仍是實際結果，前端以第二次的回應為準顯示 |

## 7. 測試

骨架級（不是補充，是這個設計成立的條件）：

- **schema 漂移防護** — 每個 spec 宣告的欄名，必須確實是 importer 會讀的鍵。這條測試存在的意義就是讓 `IMPORT_COLS` 那種過期不可能再發生
- **dry-run 不落地** — 跑完 dry-run，DB 筆數不變
- **dry-run 說真話** — 同一份檔先 dry-run 再真匯入，兩次的 action 序列必須相同
- **範本可回灌** — 下載範本 → 原封不動匯回去 → 成功。範本永遠是合法輸入
- **upsert 冪等** — 同檔匯入兩次，第二次全部是 update、總筆數不變（含 generation 的重複防護）

一般級：

- 逐列錯誤的列號、欄位、中文訊息正確
- 錯誤分組：同欄同因的多列收斂成一組，`count` 與 `sample_rows` 正確
- 標題列缺必填欄 → 整檔層級錯誤，不逐列展開
- 空白欄位在 update 時不覆蓋既有值
- `/batteries/import` 可用
- SPA 冒煙：`/import/schema` 與範本端點可服務

## 8. 範圍外

- **錯誤報告 CSV 下載**（把原檔加一欄錯誤原因讓使用者在 Excel 裡對照修）——對大檔是更好的 UX，但需要保留檔案內容，本次不做
- **欄位對應 UI**（讓使用者把自家欄名拖到平台欄名）——真正吃客戶 Excel 的終極解，屬 EPIC-1.2 (a)/(b) 的範圍
- **軟刪除／資料版本**（Roadmap A6 的另一半）——歸 PRD EPIC-1.4 資料治理
- **15 分鐘 interval 電表檔匯入**——EPIC-1.2 (a)
- **台電轉供結算檔解析**——EPIC-1.2 (b)
