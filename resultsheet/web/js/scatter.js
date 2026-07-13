// SVG 自前描画の散布図。フィット直線はサーバ (adhoc_fit) が計算した値を使う。
// 外部ライブラリ不使用(オフライン動作・依存最小)。

import { el } from "./ui.js";

const SVG_NS = "http://www.w3.org/2000/svg";
const W = 640, H = 420, PAD_L = 64, PAD_B = 48, PAD_T = 16, PAD_R = 16;

export function renderScatter(container, def, state, reportId, api) {
  if (!def.tables.length) return { update() {} };

  // 列選択の候補: 各テーブルの入力列 + 導出列
  // (定義ファイルはどの列を散布図にするか指定しない。ここで実データの全列から
  //  ユーザーがオプションボタンで自由に X/Y を選ぶ)
  const multiTable = def.tables.length > 1;
  const options = [];
  for (const t of def.tables) {
    const push = (c, label) => options.push({
      table: t.name, col: c.name, unit: c.unit,
      label: `${t.label}: ${label}`,                 // 軸ラベル・凡例用
      chip: multiTable ? `${t.label}·${label}` : label,  // ボタン表示用(短め)
    });
    for (const c of t.columns) push(c, c.label);
    for (const c of t.derived_columns) push(c, c.label || c.name);
  }

  // オプションボタン(トグル chip)で X/Y を選ぶ。ドロップダウンより一覧性が高く
  // タッチ操作にも向く。選択肢は実データの列そのものなので設定ファイルに縛られない。
  let xIndex = 0;
  let yIndex = Math.min(1, options.length - 1);
  const fitChk = el("input", { type: "checkbox", id: "fit-chk", checked: "checked" });
  const fitInfo = el("span", { class: "fit-info" });

  const xRow = el("div", { class: "axis-chips", role: "group", "aria-label": "X軸の列" });
  const yRow = el("div", { class: "axis-chips", role: "group", "aria-label": "Y軸の列" });

  function buildChips() {
    for (const [row, axis] of [[xRow, "x"], [yRow, "y"]]) {
      row.innerHTML = "";
      options.forEach((o, i) => {
        const selected = (axis === "x" ? xIndex : yIndex) === i;
        const other = axis === "x" ? yIndex : xIndex;
        const chip = el("button", {
          type: "button",
          class: "chip" + (selected ? " active" : "") + (i === other ? " chip-other" : ""),
          "aria-pressed": selected ? "true" : "false",
          title: o.label + (o.unit ? ` [${o.unit}]` : ""),
          onclick: () => {
            if (axis === "x") xIndex = i; else yIndex = i;
            buildChips();
            update(lastResult);
          },
        }, o.chip, o.unit ? el("span", { class: "chip-unit" }, o.unit) : "");
        row.append(chip);
      });
    }
  }

  const controls = el("div", { class: "scatter-controls" },
    el("div", { class: "axis-line" }, el("span", { class: "axis-label" }, "X軸"), xRow),
    el("div", { class: "axis-line" }, el("span", { class: "axis-label" }, "Y軸"), yRow),
    el("div", { class: "axis-line" },
      el("label", { class: "fit-toggle" }, fitChk, " フィット直線を重ねる"), fitInfo),
  );
  buildChips();
  const svgHost = el("div", { class: "table-wrap" });
  container.append(controls, svgHost);

  let lastResult = null;

  function currentCols() {
    return { x: options[xIndex], y: options[yIndex] };
  }

  function columnValues(result, opt) {
    // 入力列は state から、導出列は result から取得
    const st = state.tables[opt.table];
    const inputIdx = st.columns.indexOf(opt.col);
    if (inputIdx >= 0) return st.rows.map((r) => r[inputIdx]);
    return result?.computed_columns?.[opt.table]?.[opt.col] ?? [];
  }

  async function update(result) {
    lastResult = result;
    const { x, y } = currentCols();
    if (!x || !y) { svgHost.innerHTML = ""; return; }
    const xv = columnValues(result, x);
    const yv = columnValues(result, y);
    const points = [];
    const n = Math.min(xv.length, yv.length);
    for (let i = 0; i < n; i++) {
      if (xv[i] !== null && xv[i] !== undefined && yv[i] !== null && yv[i] !== undefined) {
        points.push([xv[i], yv[i]]);
      }
    }

    let fit = null;
    if (fitChk.checked && x.table === y.table && points.length >= 2) {
      try {
        const res = await api.compute(reportId, {
          inputs: state.inputs, tables: state.tables,
          adhoc_fit: { table: x.table, x: x.col, y: y.col },
        });
        if (res.adhoc_fit && !res.adhoc_fit.error && res.adhoc_fit.slope !== null) {
          fit = res.adhoc_fit;
        }
      } catch (e) { /* フィットは任意機能なので失敗は無視 */ }
    }
    drawSvg(points, x, y, fit);
    if (fit) {
      fitInfo.textContent = `y = ${fmt(fit.slope)}·x + ${fmt(fit.intercept)}  (r = ${fmt(fit.rvalue)})`;
    } else {
      fitInfo.textContent = "";
    }
  }

  function drawSvg(points, x, y, fit) {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("class", "scatter-svg");
    svg.setAttribute("role", "img");

    if (points.length === 0) {
      svgHost.innerHTML = "";
      svgHost.append(el("p", { class: "muted small" }, "データ点がありません。値を入力してください。"));
      return;
    }

    const xs = points.map((p) => p[0]), ys = points.map((p) => p[1]);
    const xr = niceRange(Math.min(...xs), Math.max(...xs));
    const yr = niceRange(Math.min(...ys), Math.max(...ys));
    const sx = (v) => PAD_L + ((v - xr.min) / (xr.max - xr.min)) * (W - PAD_L - PAD_R);
    const sy = (v) => H - PAD_B - ((v - yr.min) / (yr.max - yr.min)) * (H - PAD_T - PAD_B);

    // 軸・グリッド・目盛
    for (const tick of xr.ticks) {
      const px = sx(tick);
      svg.append(line(px, PAD_T, px, H - PAD_B, "#eef0f3"));
      svg.append(text(px, H - PAD_B + 16, fmt(tick), "middle"));
    }
    for (const tick of yr.ticks) {
      const py = sy(tick);
      svg.append(line(PAD_L, py, W - PAD_R, py, "#eef0f3"));
      svg.append(text(PAD_L - 8, py + 4, fmt(tick), "end"));
    }
    svg.append(line(PAD_L, PAD_T, PAD_L, H - PAD_B, "#9aa1ac"));
    svg.append(line(PAD_L, H - PAD_B, W - PAD_R, H - PAD_B, "#9aa1ac"));

    // 軸ラベル
    svg.append(text(PAD_L + (W - PAD_L - PAD_R) / 2, H - 8, axisLabel(x), "middle", 13, "#4b5563"));
    const yl = text(16, PAD_T + (H - PAD_T - PAD_B) / 2, axisLabel(y), "middle", 13, "#4b5563");
    yl.setAttribute("transform", `rotate(-90 16 ${PAD_T + (H - PAD_T - PAD_B) / 2})`);
    svg.append(yl);

    // フィット直線
    if (fit) {
      const x1 = xr.min, x2 = xr.max;
      const y1 = fit.slope * x1 + fit.intercept, y2 = fit.slope * x2 + fit.intercept;
      const seg = line(sx(x1), sy(y1), sx(x2), sy(y2), "#dc2626");
      seg.setAttribute("stroke-width", "2");
      svg.append(seg);
    }

    // 点
    for (const [px, py] of points) {
      const c = document.createElementNS(SVG_NS, "circle");
      c.setAttribute("cx", sx(px));
      c.setAttribute("cy", sy(py));
      c.setAttribute("r", "4.5");
      c.setAttribute("fill", "#2563eb");
      c.setAttribute("fill-opacity", "0.75");
      c.append(titleNode(`(${fmt(px)}, ${fmt(py)})`));
      svg.append(c);
    }

    svgHost.innerHTML = "";
    svgHost.append(svg);
  }

  // X/Y の選択は各 chip の onclick で処理する(buildChips 内)。
  fitChk.addEventListener("change", () => update(lastResult));

  return { update };
}

function axisLabel(opt) {
  return opt.unit ? `${opt.label} [${opt.unit}]` : opt.label;
}

function line(x1, y1, x2, y2, stroke) {
  const l = document.createElementNS(SVG_NS, "line");
  l.setAttribute("x1", x1); l.setAttribute("y1", y1);
  l.setAttribute("x2", x2); l.setAttribute("y2", y2);
  l.setAttribute("stroke", stroke);
  return l;
}

function text(x, y, str, anchor, size = 11, fill = "#6b7280") {
  const t = document.createElementNS(SVG_NS, "text");
  t.setAttribute("x", x); t.setAttribute("y", y);
  t.setAttribute("text-anchor", anchor);
  t.setAttribute("font-size", size);
  t.setAttribute("fill", fill);
  t.textContent = str;
  return t;
}

function titleNode(str) {
  const t = document.createElementNS(SVG_NS, "title");
  t.textContent = str;
  return t;
}

// nice ticks (1-2-5 系列)
function niceRange(min, max) {
  if (min === max) { min -= 1; max += 1; }
  const span = max - min;
  const step = niceStep(span / 5);
  const nmin = Math.floor(min / step) * step;
  const nmax = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = nmin; v <= nmax + step * 1e-9; v += step) {
    ticks.push(Number((Math.round(v / step) * step).toPrecision(12)));
  }
  return { min: nmin, max: nmax, ticks };
}

function niceStep(raw) {
  const exp = Math.floor(Math.log10(raw));
  const base = raw / Math.pow(10, exp);
  const nice = base <= 1 ? 1 : base <= 2 ? 2 : base <= 5 ? 5 : 10;
  return nice * Math.pow(10, exp);
}

function fmt(v) {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  const a = Math.abs(v);
  if (a !== 0 && (a >= 1e5 || a < 1e-3)) return v.toExponential(2);
  return String(Number(v.toPrecision(6)));
}
