# 功能規劃：風光互補（A7 + B4）

- **狀態**：規劃中（待實作）— 對應 Roadmap `A7`（太陽能／技術別實體）、`B4`（風光互補混合最佳化），Phase 6
- **日期**：2026-07-29
- **一句話**：太陽能正午 bell 型補上風電白天缺口，讓逐時 CFE 真實提升——不再只是破題圖的示意。

---

## 1. 核心洞見
風電**夜強日弱**、多數工業客戶**日間用電高** → 白天出現缺口（CFE 熱力圖午間偏淡）。太陽能**正午 bell**正好補洞。**風＋光時間互補 → 逐時 CFE 提升、外溢下降**。

## 2. 已定決策
| 項目 | 決定 |
|---|---|
| 資料模型 | **沿用 `wind_farms` 表 + `farm_type="solar"`**（發電資產，不新增獨立表）；派生 `technology`（wind/solar） |
| 24h 圖呈現 | **風 + 光 堆疊區域**（看得出各自貢獻、午間光填缺口） |
| 互補比較 | **預設顯示 uplift**：頂部「只風電 X% → 風光 Y%（+Z pt）」 |
| Seed 規模 | **1 座地面型光電 + 對日間型客戶（電源管理/面板）合約** |

## 3. 設計原則（最小侵入）
太陽能沿用整條既有管線（合約 FK `wind_farm_id`、發電 FK、hourly service 逐一跑 WindFarm）→ **匹配引擎零改動**，互補天然浮現。`technology = "solar" if farm_type=="solar" else "wind"`（helper，不加欄位）。

## 4. 資料層（A7）
- **`hourly_profile.solar_shape()`**：24 點，夜間 0、日出漸升、正午峰、日落歸零（沿用破題圖曲線），normalized。
- **太陽能月型**：夏強冬弱季節係數（與風電相反，凸顯互補）。
- **CF**：太陽能 P50 ~14%、P90 ~11%。
- **slot 拆分 technology-aware**：`generate_slot_profiles` 依 technology 選比例——solar 尖峰/半尖峰重、離峰≈0（風電維持 off-peak 重）。
- **interval synth 依 technology**：solar＝bell × 逐日雲量變異 × 夜間 0（新增 `solar_day_factors`）。
- **seed**：新增 1 座地面型光電（中南部）＋月發電＋對日間客戶的合約。

## 5. 匹配（B4）
- **引擎不改**——solar 只是更多 farm，各有逐時 profile。
- **「只風電 vs 風光」比較**：service 跑兩次（全部資產 vs 排除 solar 資產與其合約），回傳 `wind_only_cfe` + `combined_cfe` + `uplift`（= combined − wind_only）。

## 6. 前端 C6
- **24h 圖**：發電改「風 + 光 堆疊區域」；午間光填缺口。
- **比較讀數**：頂部「只風電 X% → 風光 Y%（+Z pt）」。
- **熱力圖**：午間格子變綠（互補視覺證據）。
- **案場層**：`farmTypeBadge` 支援 solar（太陽能／離岸／陸域）。
- **ⓘ 說明**：新增「風光互補」名詞卡。

## 7. 需留意的副作用
solar 是 `wind_farms` 一員 → 會出現在售電評估、多對多、投資效益、發電案場頁、即時能源。逐頁檢查：文案「風場」→「案場」、`farmTypeBadge` 支援 solar、投資效益 CAPEX/CF 對 solar 合理性（先沿用、標示）。

## 8. 測試（TDD）
- `solar_shape`：夜間 0、正午峰、Σ=1。
- `technology` 分類。
- slot 拆分 technology-aware（solar 離峰≈0）。
- interval synth solar：夜間 0、逐日變異。
- **service：`combined_cfe ≥ wind_only_cfe`**；seed 後 2024-01 combined > wind-only。
- 既有 wind-only 測試不破。

## 9. 交付順序與驗收
1. 後端：`solar_shape`／月型 → slot 拆分 technology-aware → interval synth solar → seed 光電＋合約 → service 加 `wind_only_cfe`/`combined_cfe`/`uplift` → 測試。
2. 前端：堆疊 24h 圖 → uplift 讀數 → farm badge → ⓘ。
3. README：補風光互補圖。

**驗收**：2024-01 風光 CFE > 只風電；午間熱力圖變綠；堆疊圖看得出光的貢獻；全套閘門（ruff/black/mypy/pytest）綠；多半免 migration（沿用 farm_type）。

## 10. 未來延伸
- **B5 儲能**：疊在風光之上再平滑（破題圖第三段「風＋光＋儲」的真實版）。
- 風光**同一 PPA 打包**（hybrid PPA）情境。

---

> 不新增資料表、引擎零改動；太陽能沿用發電資產管線。實作前經使用者確認決策（見 §2）。
