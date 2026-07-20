# 部署（Google Cloud Run + Neon Postgres）

把平台部署成**單一個 Cloud Run 服務**(FastAPI app,同時在 `/app` 服務靜態 SPA),
由 `Dockerfile` 建置,後端接 **Neon** serverless PostgreSQL。Cloud Run 能 scale 到零
(用多少付多少),`asia-east1` 在台灣(彰化),延遲極佳。

```mermaid
flowchart LR
    U[Browser] --> A[emp-api<br/>FastAPI + SPA on Cloud Run]
    A -->|DATABASE_URL / SSL| N[(Neon PostgreSQL)]
    B[Cloud Build] -->|image| AR[(Artifact Registry)]
    AR --> A
    AR --> D
    J[Cloud Run Jobs:<br/>migrate + seed] --> N
```

## 前置需求

- 已安裝並登入 `gcloud` CLI:`gcloud auth login`
- 一個**已啟用計費**的 GCP 專案
- 一個 [Neon](https://neon.tech) 資料庫。連線字串用 `postgresql+psycopg://…` 形式,保留
  `?sslmode=require`(Neon 區域選靠近 `asia-east1` 的,例如東京 `ap-northeast-1` 或
  新加坡 `ap-southeast-1`)。

## 一行部署

repo 附了 [`scripts/deploy_cloudrun.sh`](../scripts/deploy_cloudrun.sh),它會建置映像、
跑遷移、部署服務並載入資料:

```bash
export PROJECT_ID="your-gcp-project"
export DATABASE_URL="postgresql+psycopg://user:pass@ep-xxx.aws.neon.tech/neondb?sslmode=require"
./scripts/deploy_cloudrun.sh
```

可選的覆寫:`REGION`(預設 `asia-east1`)、`REPO`、`IMAGE_TAG`、`SEED`(預設 `true`)。

最後它會印出 API/Swagger 與 SPA(`…/app/`)的網址。

## 腳本做了什麼(逐步)

1. **啟用 API** — Cloud Run、Cloud Build、Artifact Registry。
2. **建立 Artifact Registry** 的 Docker repo(冪等)。
3. **建置並推送**一份映像,由 `Dockerfile` 經 Cloud Build 產生。
4. **遷移** — 一個一次性的 **Cloud Run Job** 對 Neon 跑 `alembic upgrade head`
   (刻意放在服務容器之外,避免啟動時的競態)。
5. **部署 `emp-api`** — 綁定 `$PORT`、設好 `DATABASE_URL`、對外公開;同時在 `/app`
   服務靜態 SPA。
6. **載入資料** — 一個一次性的 Cloud Run Job 跑 `python -m scripts.seed --reset`。

## 手動等價指令(如果你偏好自己下指令)

```bash
PROJECT_ID=your-project ; REGION=asia-east1 ; REPO=energy-matching
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/app:latest"
DATABASE_URL="postgresql+psycopg://...:...@.../db?sslmode=require"

gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
gcloud artifacts repositories create $REPO --repository-format=docker --location=$REGION
gcloud builds submit --tag "$IMAGE"

gcloud run jobs deploy emp-migrate --image "$IMAGE" --region $REGION \
  --set-env-vars "DATABASE_URL=$DATABASE_URL" --command sh --args '-c,alembic upgrade head'
gcloud run jobs execute emp-migrate --region $REGION --wait

gcloud run deploy emp-api --image "$IMAGE" --region $REGION --allow-unauthenticated \
  --set-env-vars "DATABASE_URL=$DATABASE_URL,ENVIRONMENT=production" \
  --command sh --args '-c,uvicorn app.main:app --host 0.0.0.0 --port $PORT'

API_URL=$(gcloud run services describe emp-api --region $REGION --format 'value(status.url)')
echo "Web UI (SPA): $API_URL/app/"
```

## 注意事項與眉角

- **`$PORT`** — Cloud Run 會注入它;兩個服務都必須綁到它(上面的指令有做)。它是以字面
  傳入的,好讓容器的 `sh` 在執行期展開。
- **機密** — 正式環境建議用 **Secret Manager** 而非 `--set-env-vars` 來放 `DATABASE_URL`
  (`--set-secrets DATABASE_URL=emp-db-url:latest`)。
- **冷啟動** — scale-to-zero 代表閒置後第一個請求會慢一點;想讓它常駐,對 `emp-api` 設
  `--min-instances 1`(成本較高)。
- **成本** — 在 scale-to-zero、低流量下大概只花幾分錢;一個 demo 常常落在 Cloud Run 的
  免費額度內。
- **區域** — 讓 Cloud Run 與 Neon 地理上靠近以降低延遲。

另見 [`deployment.md`](deployment.md) 裡的 Render 選項。
