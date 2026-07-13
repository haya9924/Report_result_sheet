// 定義エディタ: 計算方式 YAML(definition.yaml)をブラウザ上で編集・検証・保存。
// 実験結果(results.json)とは別ファイル。ここでは計算方式のみを扱う。

import { api } from "./api.js";
import { el } from "./ui.js";
import { setTopbarStatus } from "./app.js";

export async function renderEditor(app, reportId) {
  const text = await api.getDefinition(reportId);

  app.innerHTML = "";
  const area = el("textarea", { class: "yaml-editor", spellcheck: "false" });
  area.value = text;
  const resultBox = el("div", {});
  let dirty = false;

  area.addEventListener("input", () => {
    dirty = true;
    setTopbarStatus("● 未保存(定義)", "");
  });

  app.append(
    el("div", { class: "toolbar" },
      el("a", { href: `#/report/${reportId}` }, "← 入力に戻る"),
      el("h1", {}, "計算方式の編集"),
      el("span", { class: "spacer" }),
      el("button", { onclick: doValidate }, "検証"),
      el("button", { class: "primary", onclick: doSave }, "保存"),
    ),
    el("p", { class: "muted small" },
      "計算方式(変数・単位・計算式・丸め)を定義します。実験結果とは別ファイル(definition.yaml)として保存されます。" +
      "「検証」で計算式や参照の誤りを保存前に確認できます。"),
    el("div", { class: "panel" }, area),
    resultBox,
  );

  async function doValidate() {
    resultBox.innerHTML = "";
    let res;
    try {
      res = await api.validate(area.value);
    } catch (e) {
      showResult(false, e.message);
      return;
    }
    if (res.ok) {
      const d = res.definition;
      const nVars = d.inputs.length +
        d.tables.reduce((s, t) => s + t.columns.length + t.derived_columns.length, 0);
      showResult(true,
        `OK: ${d.id} — ${d.title}\n入力 ${nVars} 変数 / 導出 ${d.derived.length} 量`);
    } else {
      showResult(false, res.error);
    }
  }

  async function doSave() {
    try {
      await api.putDefinition(reportId, area.value);
      dirty = false;
      setTopbarStatus("定義を保存しました", "");
      showResult(true, "定義を保存しました。入力画面に戻ると新しい計算方式で再計算されます。");
    } catch (e) {
      showResult(false, "保存できません(検証エラー): " + e.message);
    }
  }

  function showResult(ok, msg) {
    resultBox.innerHTML = "";
    resultBox.append(el("div", { class: "validate-result " + (ok ? "ok" : "ng") }, msg));
  }

  return function cleanup() {
    if (dirty) {
      return confirm("定義に未保存の変更があります。移動すると破棄されます。よろしいですか?");
    }
    return true;
  };
}
