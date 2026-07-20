# 部署（Render + Neon Postgres）

這份指南把平台部署成**單一個 Render web service**(FastAPI app,同時在 `/app` 服務靜態
SPA),由 repo 的 `Dockerfile` 建置,後端接一個 **Neon** serverless PostgreSQL 資料庫。
兩者都有可用的免費方案。

> 為什麼是這個組合:Render 直接跑 Dockerfile;Neon 給一個持久、免費的 Postgres,一條
> 連線字串就搞定。SPA 是由 API 同源服務的靜態檔案,所以不需要獨立的前端服務、也沒有 CORS。

## 雲端上的架構

```mermaid
flowchart LR
    U[Browser] -->|:443| A[emp-api<br/>FastAPI + SPA on Render]
    A -->|DATABASE_URL<br/>SSL| N[(Neon PostgreSQL)]
```

SPA 由 API 同源服務(`/app`),所以沒有獨立的前端服務,瀏覽器端也不需要設定 CORS。

## 前置需求

- repo 已推到 GitHub(就是這個專案)。
- 一個 [Render](https://render.com) 帳號(免費)。
- 一個 [Neon](https://neon.tech) 帳號(免費)。

## 步驟 1 — 建立資料庫(Neon)

1. Neon → **New Project** → 選一個靠近 Render `singapore` 的區域
   (例如 AWS `ap-southeast-1`)。
2. 複製連線字串,長得像:
   ```
   postgresql://user:pass@ep-xxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
   ```
3. **改掉 scheme**,讓 SQLAlchemy 使用 psycopg(保留 `?sslmode=require`):
   ```
   postgresql+psycopg://user:pass@ep-xxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
   ```
   存好——這就是你的 `DATABASE_URL`。

   > ⚠️ **用 Neon 的「直連(DIRECT)」endpoint,不要用 pooled 的。** 如果字串裡的 host 有
   > `-pooler`,把它**拿掉**(`ep-xxx-pooler.c-3...` → `ep-xxx.c-3...`)。Render 免費
   > 網路以解析後的 IP 連線,會丟掉 Neon pooler 用來路由到你專案的 SNI 主機名——這時
   > pooled URL 會以 `database "neondb" does not exist` 失敗。直連 endpoint 應付這個 demo
   > 的流量綽綽有餘。(另外也別加 `options=endpoint%3D...`:那個 `%` 會弄壞 Alembic 的
   > ini 解析。)

## 步驟 2 — 部署服務(Render Blueprint)

1. Render → **New** → **Blueprint** → 連上這個 GitHub repo。
2. Render 讀 [`render.yaml`](../render.yaml) 並提出 **emp-api** 服務。按 **Apply**。
3. 當它問 `sync: false` 的變數時,設定:
   - **emp-api** → `DATABASE_URL` = 步驟 1 的 Neon **直連** URL。

首次啟動時,**emp-api** 會自動跑 `alembic upgrade head`,於是 schema 就建到 Neon 上了。

## 步驟 3 — 遷移 + 載入示範資料(一次即可)

最快的做法——從**你自己的機器**對著 Neon URL 執行。這同時能在真實 Postgres 上驗證遷移、
並載入示範資料 + 時段資料:

```bash
export DATABASE_URL="postgresql+psycopg://user:pass@ep-xxx.../neondb?sslmode=require"
alembic upgrade head                      # create schema (idempotent; Render also runs this on boot)
python -m scripts.seed --reset            # demo: 3 farms, 5 customers, 8 contracts, 12 months
python -m scripts.generate_slot_profiles  # split monthly into peak/half/off-peak (needed for the SPA time-slot panel)
```

或者用 Render 的 **emp-api → Shell**(schema 啟動時已遷移):
`python -m scripts.seed --reset && python -m scripts.generate_slot_profiles`。

## 步驟 4 — 開始使用

- **Web UI(SPA)** → `https://emp-api.onrender.com/app/` ← 整個產品介面,由 API 服務
- API / Swagger → `https://emp-api.onrender.com/docs`
- 健康檢查 → `https://emp-api.onrender.com/health`

## 注意事項與眉角

- **免費方案休眠:** 免費 Render web service 閒置約 15 分鐘後會停機;下一個請求會花
  約 30 秒冷啟動。展示前先暖機。
- **免費方案時數:** 免費 web service 共用每月的實例時數額度。兩個常駐服務會把它用光——
  閒置時休眠才能待在額度內。
- **SSL:** Neon 要求 SSL;URL 保留 `?sslmode=require`。
- **機密:** `DATABASE_URL` 設在 Render 後台(標記 `sync:false`),絕不進版控。`.env` 維持
  git-ignored。
- **部署時的遷移:** 每次部署都會重跑 `alembic upgrade head`(安全、冪等)。
- **區域:** 讓 Render 與 Neon 在對應的區域(都 `singapore`／`ap-southeast-1`)以降低延遲。

## 其他選項

- **改用 Render 託管的 Postgres**(而非 Neon):把 `render.yaml` 裡的 `databases:` 區塊與
  `fromDatabase` 環境變數取消註解。(Render 免費 Postgres 90 天後會被刪除——要做持久的 demo,
  Neon 比較合適。)
- **Google Cloud Run + Cloud SQL / Neon:** 用同一份 Dockerfile 部成兩個 Cloud Run 服務
  (scale-to-zero、用多少付多少)。`--port` 設成 `$PORT`,加上 Cloud SQL connector 或用
  Neon over SSL,並把 `alembic upgrade head` 放在 pre-deploy 步驟或 Cloud Run Job。
