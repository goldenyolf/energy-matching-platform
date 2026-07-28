# ADR-001：後端正式部署選型

- **狀態**：建議中（Proposed）— 對應 Roadmap `H2`（Phase 5 · 部署與資安），尚未執行
- **日期**：2026-07-28
- **決策者**：專案團隊
- **相關**：Roadmap `H3`（資料庫正式化）、`H4`（求解移背景佇列）、`H5`（觀測性正式化）；`docs/PRD.md` 第 8 節（GA 判準）

---

## 背景（Context）

平台目前以「示範」形態部署在 **Render 免費層 + Neon Postgres**：免費層閒置 ~15 分鐘會休眠、首次請求冷啟動慢，且區域最近只到新加坡。要邁向正式對外服務，需要選定正式後端。

服務對象與技術特性影響選型：

- **對象**：台灣售電業（B2B），初期使用者數不大，重可靠度與信任，非高流量。
- **資料敏感度**：含台電轉供、企業客戶用電等資料 → **資料落地台灣**對合規與客戶信任是實在加分（個資法/PDPA 層面、政府與大型客戶偏好）。
- **運算特性**：媒合最佳化用 **PuLP + CBC**，CBC 以 subprocess 執行、**CPU-bound**、單次可達數秒；目前同步執行＋semaphore 限並發。
- **架構**：FastAPI 容器（啟動跑 `alembic upgrade head`）、同源服務靜態 SPA、需外掛 Postgres。

## 評估準則（Criteria）

1. **資料落地台灣**（合規／信任）與**對台灣的延遲**
2. 可靠度與維運成本（越託管越好，團隊小）
3. 對 **CBC CPU-bound / 長求解** 的支援（逾時、可搭配佇列）
4. 成本
5. 落地成本（現有腳本／熟悉度）與擴展性

## 選項比較（Options）

| 方案 | 台灣區域 | 延遲 | 維運 | 備註 |
|---|---|---|---|---|
| **GCP Cloud Run（asia-east1／彰化）** | ✅ 有（彰化） | 最低 | 全託管、scale-to-zero 或 min-instances | repo 已有部署腳本；與 Cloud Tasks 搭配佳；請求逾時可調長 |
| **Fly.io（Tokyo `nrt`）** | ❌ 無 | 低（~30–40ms） | 中（Postgres 較 DIY） | always-on 便宜、DX 好，但**資料出境** |
| **AWS ECS Fargate + RDS（東京/香港）** | ❌ 無 | 低–中 | 高（設定/成本較重） | 企業級、最有彈性，現階段偏重 |
| **Render 付費 / Railway** | ❌（新加坡） | 中 | 低 | 最少改動的跳板，正式化再遷 |

## 決策（Decision）

**首選：GCP Cloud Run（asia-east1／彰化）＋ Cloud SQL for PostgreSQL（asia-east1）。**

理由：

- **唯一有台灣境內區域**的雲 → 同時給到**最低延遲**與**資料落地台灣**（面對能源 B2B 客戶談資安/合規/信任最有利）。
- **全託管容器**，可設 `min-instances=1` 免冷啟動；請求逾時可調長，CBC subprocess 在容器中正常運作。
- **repo 已有 `scripts/deploy_cloudrun.sh`**，落地成本低。
- 與 **Cloud Tasks** 天生一對，便於把 MILP 求解**移出請求執行緒**（見 `H4`）。
- 資料庫用 **Cloud SQL（asia-east1）**：與 Cloud Run 同區、延遲最低、資料同在台灣，含自動備份＋PITR。

### 何時改選替代方案

- **極度成本敏感且可接受資料在東京** → **Fly.io（Tokyo）＋ managed Postgres**（always-on 最省）。
- **客戶明確要求 AWS 生態／企業級 SLA** → **AWS ECS Fargate + RDS**。
- **只想最小改動先撐一段** → **Render 付費**（新加坡）當跳板，之後再遷。

## 搭配必做（一起完成才算正式化）

- 離開免費層、設 `min-instances=1`（不休眠、無冷啟動）
- **managed Postgres**：自動備份＋PITR＋還原演練（`H3`）
- **MILP 求解移到背景佇列**（Cloud Tasks / Celery / RQ，`H4`）— 承載真實流量的關鍵
- **prod / staging 分離** ＋ secrets 管理（不落 repo）
- **觀測性**：Sentry ＋ 指標（求解耗時/請求量/失敗率）＋ 告警（`H5`）
- 網域、TLS/HSTS、健康檢查上線（資安見 Roadmap 領域 `G`）

## 影響（Consequences）

- **正向**：資料落地台灣、低延遲、維運省事、可擴、與求解佇列整合順。
- **成本**：Cloud Run + Cloud SQL 小型實例約**月數十美元**（依流量）；較 Render/Fly 免費或極省方案為高，但換得可靠度與資料落地。
- **鎖定**：偏向 GCP 生態（Cloud SQL、Cloud Tasks、Secret Manager）；可用容器化＋標準 Postgres 降低遷移成本。
- **待驗證**：正式流量下的 CBC 求解延遲與並發、Cloud SQL 規格、實際月成本 → 於 `H2` 的 PoC 階段量測後定案。

---

> 本文件為決策紀錄（ADR）。正式定案後請把「狀態」改為 **已採納（Accepted）**，並於 `H2` 卡片標記完成。
