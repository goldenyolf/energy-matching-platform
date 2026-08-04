# 寫入密碼輸入 UI Design

- **狀態**：Approved (design)
- **日期**：2026-08-04
- **對應**：PRD EPIC-1.1 的前哨（`ADMIN_WRITE_TOKEN` 退場前的過渡）
- **一句話**：讓線上 demo 可以真的設 `ADMIN_WRITE_TOKEN`——目前設了就等於把自己鎖在外面，因為 SPA 根本沒有輸入密碼的地方。

---

## 1. 為什麼現在做

線上部署啟動時會印：

```
WARNING app: ADMIN_WRITE_TOKEN is unset in production — all create/update/delete/import
endpoints are OPEN to the public.
```

這不是理論風險。**upsert 上線後它變嚴重了**：以前重複匯入會被靜默略過，現在會覆蓋，所以任何拿到網址的人可以改掉合約售電價、刪掉案場，而不只是塞進被略過的重複資料。

但直接去 Render 設 token 會把自己鎖在外面：`web/app.js:2475-2476` 明寫「密碼保護暫時隱藏（之後再設計呈現）… 屆時再補密碼輸入 UI」。設了 token，瀏覽器每個寫入都 403，連剛做完的 CSV 匯入預覽都 demo 不了。

`web/api.js:80` 的 `api.setToken()` 管線已經在了，只差沒有東西呼叫它。

## 2. 已定決策

| 項目 | 決定 | 理由 |
|---|---|---|
| 觸發時機 | **只在 403 時跳出**，平時沒有任何常駐元件 | 台智電看的是公開展示頁，不該看到登入框 |
| 保存 | `sessionStorage` | 同分頁不用重打；關掉分頁就消失，demo 筆電留在會議室也不會把密碼留下 |
| 解鎖後 | **自動重試原本那個動作** | 否則使用者要重按一次，而匯入預覽還得重選檔案 |
| 攔截點 | **`api.js` 一處**，不是 7 個呼叫端 | 見 §3 |

## 3. 架構：一個攔截點，不是七個

`web/app.js` 有 **7 處** `writeErr(err)` 呼叫，每個寫入失敗都經過它。但 `writeErr` 回傳字串，沒辦法重試。

所以攔截點放在 `web/api.js` 的 `request()` 與 `upload()`：它們是所有寫入的唯一出口，而且拿得到原始請求參數，重試只是再呼叫一次自己。

**分層不能混**：`api.js` 不可以自己畫 UI。改用回呼：

```javascript
// api.js
var onAuthRequired = null;   // app.js 註冊；回傳 Promise<token|null>

api.setAuthPrompt = function (fn) { onAuthRequired = fn; };
```

流程：

1. 請求收到 403
2. 若 `onAuthRequired` 未註冊，或這次已經重試過 → 照舊丟 `ApiError`
3. 否則呼叫 `onAuthRequired()`，等使用者輸入
4. 使用者取消（resolve `null`）→ 丟原本的 `ApiError`
5. 拿到密碼 → `setToken()` 後**重試一次**原請求
6. 重試再 403 → 丟錯（密碼是錯的），**不再跳第二次**

「重試一次」是硬上限。沒有它，錯誤的密碼會讓使用者陷在無盡的彈窗迴圈裡。

## 4. UI

沿用既有的 `overlay show formov` ＋ `formmodal` 慣例（`web/app.js:2759` 的 `showFormModal` 就是這個形狀），不要另創一套。

- 標題：`需要編輯密碼`
- 說明：`此環境已啟用寫入保護。請輸入密碼以繼續。`
- 一個 `<input type="password">`，開啟即 focus
- 按鈕：`取消` / `解鎖`
- 密碼錯誤時（重試仍 403）：在既有的 `.fm-err` 區塊顯示 `密碼不正確。`

Esc 與點擊遮罩等同取消，與現有 modal 一致。

## 5. 分頁內保存

`app.js` 啟動時：若 `sessionStorage` 有 `emp_admin_token`，`api.setToken()` 一次。成功解鎖後寫入；使用者取消不寫。

**不做登出按鈕。** 關掉分頁就是登出，而常駐的登出入口會違反 §2 的「平時沒有任何常駐元件」。

## 6. 檔案異動

- `web/api.js` — `setAuthPrompt`、403 攔截與單次重試
- `web/app.js` — 密碼 modal、註冊回呼、啟動時讀 `sessionStorage`
- `web/styles.css` — 只在既有 modal 樣式不夠用時才動；預期不用改
- `tests/integration/test_spa_static.py` — 冒煙測試

**不動後端。** `require_write_access` 與 `X-Admin-Token` 契約完全不變，這純粹是把既有機制接上使用者。

## 7. 測試

SPA 沒有 JS 測試框架，主要驗證是真瀏覽器走查（真實座標點擊，不用合成事件）：

1. 未設 token 時，寫入照常成功，**完全不跳密碼框**（不能為了安全把沒開保護的環境也弄得很煩）
2. 設了 token 時，寫入 → 跳密碼框 → 輸入正確 → **原動作自動完成**，不需要再按一次
3. 輸入錯誤密碼 → 顯示「密碼不正確」→ **不會無限跳窗**
4. 取消 → 顯示原本的 403 訊息，什麼都沒寫進去
5. 解鎖後在同分頁換頁再寫入 → 不用重打
6. CSV 匯入預覽（`dry_run=true`）也是寫入端點，同樣會觸發，解鎖後預覽正常出現

第 1 點與第 6 點最容易漏：前者是「沒開保護就不該有摩擦」，後者是這支分支存在的理由——匯入是 demo 的主角。

## 8. 範圍外

- **真正的帳號系統**（OIDC、角色、稽核軌跡）——那是 PRD EPIC-1.1，`ADMIN_WRITE_TOKEN` 屆時退場
- **登出按鈕**、常駐鎖頭圖示——見 §5
- **記住密碼跨分頁**（`localStorage`）——刻意不做，見 §2
