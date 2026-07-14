# Energy Matching Platform

> 台灣綠電交易媒合 MVP — 模擬**風力發電案場**、**企業綠電合約 (CPPA)**、**企業用電**與 **RE 目標** 之間的綠電分配與分析。

以台灣企業購買再生能源（Corporate PPA / 轉供）為情境，把「哪個案場的綠電、以多少比例、轉供給哪家企業」建模成一個可計算、可測試、可透過 API 查詢的媒合引擎，並產出每家企業的 **RE 覆蓋率**與**距離 RE 目標的缺口**。

## ✨ 功能

- **綠電比例分配 (proportional matching)**：合約可用「案場發電量比例」或「固定年電量」兩種方式約定。
- **超額認購自動削減 (curtailment)**：當單一案場的合約需求超過年發電量時，依需求等比例削減。
- **RE 目標分析**：計算每家企業的綠電覆蓋率、RE 目標缺口與是否達標。
- **平台總覽**：整體發電量、分配量、剩餘綠電、綠電利用率與達標企業數。
- **REST API**（FastAPI，內建 Swagger UI）與 **CLI 展示報表**。
- **18 個單元／API 測試**，核心演算法為純函式、易於驗證。

## 🏗️ 技術棧

| 層 | 技術 |
|----|------|
| 語言 | Python 3.10+ |
| Web | FastAPI + Uvicorn |
| 資料驗證 | Pydantic v2 |
| 測試 | pytest + FastAPI TestClient |

## 🚀 快速開始

```bash
# 1. 建立虛擬環境並安裝依賴
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. 執行 CLI 展示（以內建範例資料跑一次媒合）
python -m scripts.demo

# 3. 執行測試
pytest

# 4. 啟動 API 伺服器
uvicorn app.main:app --reload
# 開啟 http://127.0.0.1:8000/docs 查看互動式 API 文件
```

## 📊 範例情境輸出

以內建的 5 個案場、5 家企業、7 張合約執行媒合：

```
[ 企業 RE 目標分析 ]
企業        用電         綠電        覆蓋率   RE目標   缺口        達標
台積電      5,000.0 GWh  4,850.0 GWh  97%    100%   150.0 GWh   未達
台達電        900.0 GWh    800.0 GWh  89%    100%   100.0 GWh   未達
友達光電    2,000.0 GWh  1,850.0 GWh  92%     60%     0.0 GWh   達標
宏碁          150.0 GWh    120.0 GWh  80%     80%     0.0 GWh   達標
大江生醫       60.0 GWh     16.0 GWh  27%     50%    14.0 GWh   未達

[ 平台總覽 ]
  總發電量   : 9,900.0 GWh    綠電利用率   : 77%
  總分配量   : 7,636.0 GWh    RE 目標總缺口 : 264.0 GWh
  剩餘綠電   : 2,264.0 GWh    達標企業數    : 2 / 5
```

## 🔌 API 端點

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET  | `/health` | 健康檢查 |
| GET  | `/dataset` | 取得內建範例資料集 |
| GET  | `/match` | 以範例資料執行媒合並回傳完整分析 |
| POST | `/match` | 以自訂資料集執行媒合 |
| GET  | `/companies/{id}` | 查詢單一企業的 RE 目標分析 |

```bash
curl http://127.0.0.1:8000/match | python -m json.tool
curl http://127.0.0.1:8000/companies/co-tsmc
```

## 🧮 媒合演算法

1. 每個案場有固定年發電量。
2. 綁在案場上的每張合約產生一筆需求：ratio → `比例 × 年發電量`；volume → `約定電量`。
3. 需求總和 ≤ 年發電量 → 全額分配，其餘為剩餘綠電。
4. 需求總和 > 年發電量（超額認購）→ 依需求等比削減，使分配總量剛好等於年發電量。
5. 彙整到企業層級，計算覆蓋率 `= 分配量 / 用電量` 與 RE 缺口 `= max(0, 用電量 × RE目標 − 分配量)`。

詳見 [`docs/architecture.md`](docs/architecture.md) 與 [`docs/data-model.md`](docs/data-model.md)。

## 📁 專案結構

```
energy-matching-platform/
├── app/
│   ├── models.py      # Pydantic 領域模型（案場／企業／合約／結果）
│   ├── matching.py    # 核心媒合引擎（純函式）
│   ├── data.py        # 範例資料載入
│   └── main.py        # FastAPI 應用程式
├── data/sample_data.json  # 台灣情境範例資料
├── scripts/demo.py    # CLI 展示報表
├── tests/             # 18 個 pytest 測試
└── docs/              # 架構、資料模型、API 文件
```

## ⚠️ 範圍與免責

本專案為**作品集用途的 MVP**，資料為公開資訊改編之示意值，並非真實合約或即時電網資料。媒合採「年度總量比例分配」，尚未納入 8760 小時逐時匹配或最佳化求解（可作為後續延伸）。

## 📄 授權

[MIT](LICENSE)
