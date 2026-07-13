// 入力ビュー: スカラー入力・表入力・導出量・散布図・保存・エクスポート
// 計算は一切 JS で行わず、変更のたびに POST /compute をサーバに投げる。

import { api } from "./api.js";
import { el, debounce, parseNumberInput, openModal } from "./ui.js";
import { setTopbarStatus } from "./app.js";
import { renderScatter } from "./scatter.js";

export async function renderReport(app, reportId) {
  const data = await api.getReport(reportId);
  const def = data.definition;
  const saved = data.results;

  // 状態: 入力値(スカラー)と表(行の配列)。真実のソースはこの state。
  const state = {
    inputs: {},
    tables: {},
    dirty: false,
    lastComputed: null,
  };
  for (const inp of def.inputs) {
    state.inputs[inp.name] = saved?.inputs?.[inp.name] ?? null;
  }
  for (const t of def.tables) {
    const rows = saved?.tables?.[t.name]?.rows;
    const cols = t.columns.map((c) => c.name);
    if (rows && rows.length) {
      state.tables[t.name] = { columns: cols, rows: rows.map((r) => [...r]) };
    } else {
      const empty = Array.from({ length: t.min_rows }, () => cols.map(() => null));
      state.tables[t.name] = { columns: cols, rows: empty };
    }
  }

  app.innerHTML = "";
  app.append(
    el("div", { class: "toolbar" },
      el("a", { href: "#/" }, "← 一覧"),
      el("h1", {}, def.title),
      el("span", { class: "spacer" }),
      el("button", { onclick: () => (location.hash = `#/report/${reportId}/edit`) }, "定義を編集"),
      el("button", { onclick: () => openExport(reportId) }, "エクスポート"),
      saveBtn(),
    ),
  );
  if (def.description) app.append(el("p", { class: "muted" }, def.description));

  // ---- パネル群
  const derivedPanel = el("div", { class: "panel" });
  const scatterPanel = el("div", { class: "panel" });

  if (def.inputs.length) app.append(buildInputsPanel());
  for (const t of def.tables) app.append(buildTablePanel(t));
  if (def.derived.length) { app.append(el("h2", {}, "導出量")); app.append(derivedPanel); }
  if (def.tables.length) { app.append(el("h2", {}, "散布図")); app.append(scatterPanel); }

  const scheduleCompute = debounce(recompute, 300);

  function markDirty() {
    state.dirty = true;
    setTopbarStatus("● 未保存", "");
    updateSaveBtn();
  }

  function saveBtn() {
    const b = el("button", { class: "primary", id: "save-btn", onclick: doSave }, "保存");
    return b;
  }
  function updateSaveBtn() {
    const b = document.getElementById("save-btn");
    if (b) b.textContent = state.dirty ? "● 保存" : "保存済み";
  }

  async function doSave() {
    try {
      const payload = await api.saveResults(reportId, {
        inputs: state.inputs, tables: state.tables,
      });
      state.dirty = false;
      setTopbarStatus("保存しました (" + (payload.saved_at || "") + ")", "");
      updateSaveBtn();
    } catch (e) {
      setTopbarStatus("保存失敗: " + e.message, "");
      alert("保存に失敗しました: " + e.message);
    }
  }

  // ---- スカラー入力 -------------------------------------------------------
  function buildInputsPanel() {
    const panel = el("div", { class: "panel" });
    const grid = el("div", { class: "input-grid" });
    for (const inp of def.inputs) {
      const input = el("input", {
        type: "text", inputmode: "decimal",
        value: state.inputs[inp.name] ?? "",
      });
      input.addEventListener("input", () => {
        state.inputs[inp.name] = parseNumberInput(input);
        markDirty();
        scheduleCompute();
      });
      const field = el("div", { class: "field" },
        el("label", {}, inp.label + " ", el("span", { class: "mono muted" }, inp.name)),
        el("div", { class: "input-row" }, input, inp.unit ? el("span", { class: "unit" }, inp.unit) : ""),
        inp.description ? el("div", { class: "desc" }, inp.description) : "",
      );
      grid.append(field);
    }
    panel.append(grid);
    return panel;
  }

  // ---- 表入力 -------------------------------------------------------------
  function buildTablePanel(t) {
    const panel = el("div", { class: "panel" });
    panel.append(el("h2", {}, `表: ${t.label}`));
    if (t.description) panel.append(el("p", { class: "muted small" }, t.description));
    const wrap = el("div", { class: "table-wrap" });
    const table = el("table", { class: "data", id: `tbl-${t.name}` });
    wrap.append(table);
    panel.append(wrap);
    panel.append(el("div", { class: "toolbar" },
      el("button", { class: "small-btn", onclick: () => addRow(t) }, "+ 行を追加"),
    ));
    renderTableBody(t, table);
    return panel;
  }

  function renderTableBody(t, table) {
    table.innerHTML = "";
    const inputCols = t.columns;
    const derivedCols = t.derived_columns;
    // ヘッダ
    const head = el("tr", {}, el("th", {}, "#"));
    for (const c of inputCols) head.append(el("th", {}, c.label, c.unit ? el("span", { class: "unit" }, c.unit) : ""));
    for (const c of derivedCols) head.append(el("th", {}, (c.label || c.name), c.unit ? el("span", { class: "unit" }, c.unit) : ""));
    head.append(el("th", {}, ""));
    table.append(head);

    const st = state.tables[t.name];
    st.rows.forEach((row, ri) => {
      const tr = el("tr", {});
      tr.append(el("td", { class: "rownum", "data-label": "#" }, ri + 1));
      inputCols.forEach((c, ci) => {
        const input = el("input", { type: "text", inputmode: "decimal", value: row[ci] ?? "" });
        input.addEventListener("input", () => {
          row[ci] = parseNumberInput(input);
          markDirty();
          scheduleCompute();
        });
        const label = c.unit ? `${c.label} [${c.unit}]` : c.label;
        tr.append(el("td", { "data-label": label }, input));
      });
      for (const c of derivedCols) {
        const label = c.unit ? `${c.label || c.name} [${c.unit}]` : (c.label || c.name);
        tr.append(el("td", { class: "derived", "data-label": label, "data-dcol": `${t.name}.${c.name}`, "data-row": ri }, "—"));
      }
      tr.append(el("td", { class: "rowdel", "data-label": "" },
        el("button", { title: "この行を削除", onclick: () => { st.rows.splice(ri, 1); renderTableBody(t, table); markDirty(); scheduleCompute(); } }, "✕")));
      table.append(tr);
    });
  }

  function addRow(t) {
    const st = state.tables[t.name];
    st.rows.push(t.columns.map(() => null));
    renderTableBody(t, document.getElementById(`tbl-${t.name}`));
    markDirty();
    scheduleCompute();
  }

  // ---- 再計算(サーバ) ---------------------------------------------------
  async function recompute() {
    let result;
    try {
      result = await api.compute(reportId, { inputs: state.inputs, tables: state.tables });
    } catch (e) {
      setTopbarStatus("計算エラー: " + e.message, "");
      return;
    }
    state.lastComputed = result;
    renderDerived(result);
    renderTableDerivedCells(result);
    scatter.update(result);
    if (state.dirty) setTopbarStatus("● 未保存", "");
  }

  function renderDerived(result) {
    derivedPanel.innerHTML = "";
    const list = el("div", { class: "derived-list" });
    for (const dv of def.derived) {
      const e = result.computed[dv.name] || {};
      const item = el("div", { class: "derived-item" + (e.error ? " error" : "") });
      item.append(
        el("span", { class: "dname" }, dv.name),
        el("span", { class: "dvalue" }, e.display ?? "—"),
        dv.unit ? el("span", { class: "dunit" }, dv.unit) : "",
        (dv.label ? el("span", { class: "muted small" }, dv.label) : ""),
        el("span", { class: "spacer" }),
        (e.value !== null && e.value !== undefined
          ? el("span", { class: "dfull" }, "= " + reprFloat(e.value)) : ""),
        el("span", { class: "dexpr mono" }, dv.expr),
      );
      if (e.error) item.append(el("span", { class: "derror" }, "⚠ " + e.error));
      list.append(item);
    }
    derivedPanel.append(list);
  }

  function renderTableDerivedCells(result) {
    for (const t of def.tables) {
      const disp = result.computed_columns_display?.[t.name] || {};
      for (const c of t.derived_columns) {
        const vals = disp[c.name] || [];
        document.querySelectorAll(`[data-dcol="${t.name}.${c.name}"]`).forEach((cell) => {
          const ri = Number(cell.getAttribute("data-row"));
          cell.textContent = vals[ri] ?? "—";
        });
      }
    }
  }

  // ---- 散布図 -------------------------------------------------------------
  const scatter = renderScatter(scatterPanel, def, state, reportId, api);

  // 初回計算
  recompute();
  updateSaveBtn();
  if (state.dirty) setTopbarStatus("● 未保存", "");

  // cleanup: 未保存があれば確認
  return function cleanup() {
    if (state.dirty) {
      return confirm("保存されていない変更があります。移動すると破棄されます。よろしいですか?");
    }
    return true;
  };
}

function reprFloat(v) {
  // Python の repr に近い、情報を落とさない表現
  if (Number.isInteger(v)) return String(v);
  return String(v);
}

async function openExport(reportId) {
  let jsonText = "", mdText = "";
  try {
    jsonText = JSON.stringify(await api.exportReport(reportId, "json"), null, 2);
    mdText = await api.exportReport(reportId, "md");
  } catch (e) {
    alert("エクスポート取得に失敗: " + e.message);
    return;
  }
  openModal((close) => {
    const box = el("div", {});
    const pre = el("pre", { class: "export-box" }, jsonText);
    const showJson = el("button", { class: "primary small-btn" }, "JSON");
    const showMd = el("button", { class: "small-btn" }, "Markdown");
    showJson.onclick = () => { pre.textContent = jsonText; showJson.classList.add("primary"); showMd.classList.remove("primary"); };
    showMd.onclick = () => { pre.textContent = mdText; showMd.classList.add("primary"); showJson.classList.remove("primary"); };
    box.append(
      el("h2", {}, "エクスポート"),
      el("p", { class: "muted small" },
        "AIがLaTeX執筆時に参照する形式です。CLIでは resultsheet show / get でも取得できます。"),
      el("div", { class: "toolbar" }, showJson, showMd,
        el("span", { class: "spacer" }),
        el("button", { class: "small-btn", onclick: () => navigator.clipboard?.writeText(pre.textContent) }, "コピー"),
        el("button", { class: "small-btn", onclick: () => downloadText(reportId, pre.textContent) }, "ダウンロード"),
      ),
      pre,
      el("div", { class: "modal-actions" }, el("button", { onclick: close }, "閉じる")),
    );
    return box;
  });
}

function downloadText(id, text) {
  const isJson = text.trimStart().startsWith("{");
  const blob = new Blob([text], { type: isJson ? "application/json" : "text/markdown" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${id}.${isJson ? "json" : "md"}`;
  a.click();
  URL.revokeObjectURL(a.href);
}
