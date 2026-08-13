/* ============================================================================
 * account.js — 帳號與自選清單雲端同步（Supabase）。
 *
 * 全部走 Supabase 的原生 HTTP 端點（auth/v1 與 rest/v1），不引入任何
 * 套件——網站維持零依賴。anon key 是公開金鑰（設計上就會出現在前端），
 * 資料的隔離靠資料庫的 Row Level Security：每個使用者只能讀寫自己那列。
 *
 * 沒設定 window.__SB（Supabase 未開通）時整支自動休眠：
 * 登入介面不出現，自選清單維持純 localStorage，什麼都不壞。
 *
 * 與 quotes.js 的介面：
 *   window.__wlCloud = { ready, get(), set(tw, us) }   登入後才存在
 *   登入完成時發出 "wl-cloud-ready" 事件，quotes.js 收到後做合併。
 * ========================================================================== */
(() => {
  "use strict";

  const CONF = window.__SB;
  const slots = [...document.querySelectorAll("[data-account-slot]")];
  if (!CONF || !CONF.url || !CONF.key || !slots.length) return;

  const SESSION_KEY = "sb-session";

  /* ------------------------------------------------------------ session -- */

  const loadSession = () => {
    try { return JSON.parse(localStorage.getItem(SESSION_KEY)); }
    catch { return null; }
  };
  const saveSession = (s) => {
    try {
      if (s) localStorage.setItem(SESSION_KEY, JSON.stringify(s));
      else localStorage.removeItem(SESSION_KEY);
    } catch {}
  };

  let session = loadSession();

  async function authFetch(path, body) {
    const response = await fetch(CONF.url + path, {
      method: "POST",
      headers: { apikey: CONF.key, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.msg || payload.error_description
                      || payload.error || `HTTP ${response.status}`);
    }
    return payload;
  }

  function adoptSession(payload) {
    if (!payload || !payload.access_token) return false;
    session = {
      access: payload.access_token,
      refresh: payload.refresh_token,
      expires: Date.now() + (payload.expires_in || 3600) * 1000,
      email: payload.user?.email || "",
      uid: payload.user?.id || "",
    };
    saveSession(session);
    return true;
  }

  async function freshToken() {
    if (!session) return null;
    if (Date.now() < session.expires - 60_000) return session.access;
    try {
      const payload = await authFetch("/auth/v1/token?grant_type=refresh_token",
                                      { refresh_token: session.refresh });
      adoptSession(payload);
      return session.access;
    } catch {
      session = null;                     // refresh token 失效 → 當作登出
      saveSession(null);
      renderAll();
      return null;
    }
  }

  /* ------------------------------------------------- 雲端清單（RLS 保護） */

  async function restFetch(method, query, body) {
    const token = await freshToken();
    if (!token) throw new Error("未登入");
    const headers = {
      apikey: CONF.key,
      Authorization: "Bearer " + token,
      "Content-Type": "application/json",
    };
    if (method !== "GET") {
      headers.Prefer = "resolution=merge-duplicates,return=minimal";
    }
    const response = await fetch(CONF.url + "/rest/v1/watchlists" + query, {
      method, headers, body: body ? JSON.stringify(body) : undefined,
    });
    if (!response.ok) throw new Error("HTTP " + response.status);
    return method === "GET" ? response.json() : null;
  }

  function installCloud() {
    window.__wlCloud = {
      ready: true,
      async get() {
        const rows = await restFetch("GET", "?select=tw,us");
        return rows[0] || { tw: [], us: [] };
      },
      async set(tw, us) {
        await restFetch("POST", "", { user_id: session.uid, tw, us });
      },
    };
    document.dispatchEvent(new Event("wl-cloud-ready"));
  }

  function uninstallCloud() {
    delete window.__wlCloud;
    document.dispatchEvent(new Event("wl-cloud-gone"));
  }

  /* ----------------------------------------------------------------- UI -- */

  function renderAll() {
    for (const slot of slots) render(slot);
  }

  function render(slot) {
    if (session) {
      slot.innerHTML =
        `<div class="acct acct-in">` +
        `<span class="acct-mail">${escapeHtml(session.email)}</span>` +
        `<span class="acct-note">清單已跨裝置同步</span>` +
        `<button type="button" class="acct-link" data-acct-out>登出</button></div>`;
      slot.querySelector("[data-acct-out]").addEventListener("click", () => {
        session = null;
        saveSession(null);
        uninstallCloud();
        renderAll();
      });
      return;
    }
    slot.innerHTML =
      `<details class="acct"><summary class="acct-link">` +
      `登入或註冊，讓清單跨裝置同步</summary>` +
      `<form class="acct-form">` +
      `<input type="email" required placeholder="email" autocomplete="email">` +
      `<input type="password" required minlength="8" placeholder="密碼（至少 8 碼）" ` +
      `autocomplete="current-password">` +
      `<button type="submit" data-acct="in">登入</button>` +
      `<button type="submit" data-acct="up">註冊</button>` +
      `<span class="wl-msg" aria-live="polite"></span></form></details>`;

    const form = slot.querySelector("form");
    const msg = form.querySelector(".wl-msg");
    let mode = "in";
    for (const btn of form.querySelectorAll("[data-acct]")) {
      btn.addEventListener("click", () => { mode = btn.dataset.acct; });
    }
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const [email, password] = [...form.querySelectorAll("input")].map(i => i.value);
      msg.textContent = "…";
      try {
        const path = mode === "up"
          ? "/auth/v1/signup"
          : "/auth/v1/token?grant_type=password";
        const payload = await authFetch(path, { email, password });
        if (adoptSession(payload)) {
          renderAll();
          installCloud();
        } else {
          msg.textContent = "已寄出確認信，點過連結後再回來登入";
        }
      } catch (error) {
        msg.textContent = zhError(String(error.message || error));
      }
    });
  }

  function zhError(text) {
    if (/already registered/i.test(text)) return "這個 email 已註冊過，直接登入即可";
    if (/invalid login credentials/i.test(text)) return "email 或密碼不對";
    if (/at least 8/i.test(text) || /password/i.test(text)) return "密碼至少 8 碼";
    if (/rate limit/i.test(text)) return "試太多次了，稍等一下再試";
    return "失敗：" + text;
  }

  function escapeHtml(raw) {
    return String(raw).replace(/[&<>"']/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;",
                '"': "&quot;", "'": "&#39;" }[c]));
  }

  renderAll();
  if (session) freshToken().then((token) => { if (token) installCloud(); });
})();
