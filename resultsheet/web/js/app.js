// エントリポイント: ハッシュルーティングとビュー切替。
//   #/                  … レポート一覧(ホーム)
//   #/report/<id>       … 入力ビュー
//   #/report/<id>/edit  … 定義エディタ

import { renderHome } from "./home.js";
import { renderReport } from "./report.js";
import { renderEditor } from "./editor.js";

const app = document.getElementById("app");

export function setTopbarStatus(text, cls = "") {
  const el = document.getElementById("topbar-status");
  el.textContent = text;
  el.className = "topbar-status " + cls;
}

let currentView = { cleanup: null };

async function route() {
  if (currentView.cleanup) {
    try {
      const ok = currentView.cleanup();
      if (ok === false) return; // 未保存確認でキャンセルされた場合は遷移しない
    } finally {
      currentView.cleanup = null;
    }
  }
  setTopbarStatus("");
  app.innerHTML = '<p class="muted">読み込み中…</p>';

  const hash = location.hash || "#/";
  const m = hash.match(/^#\/report\/([A-Za-z_][A-Za-z0-9_-]*)(\/edit)?$/);
  try {
    if (m && m[2]) {
      currentView.cleanup = await renderEditor(app, m[1]);
    } else if (m) {
      currentView.cleanup = await renderReport(app, m[1]);
    } else {
      currentView.cleanup = await renderHome(app);
    }
  } catch (e) {
    app.innerHTML = "";
    const p = document.createElement("p");
    p.className = "form-error";
    p.textContent = "エラー: " + e.message;
    const back = document.createElement("p");
    back.innerHTML = '<a href="#/">← 一覧に戻る</a>';
    app.append(p, back);
  }
}

window.addEventListener("hashchange", route);
route();
