// ホーム: レポート一覧・新規作成(テンプレート / YAML貼り付け / ファイル選択)・削除

import { api } from "./api.js";
import { openModal, el } from "./ui.js";

export async function renderHome(app) {
  const reports = await api.listReports();
  app.innerHTML = "";

  const toolbar = el("div", { class: "toolbar" });
  toolbar.append(
    el("h1", {}, "レポート一覧"),
    el("span", { class: "spacer" }),
    el("button", { class: "primary", onclick: () => openNewReportModal() }, "+ 新規レポート"),
  );
  app.append(toolbar);

  if (reports.length === 0) {
    app.append(
      el("p", { class: "muted" },
        "レポートがまだありません。「+ 新規レポート」から作成してください。"),
    );
    return null;
  }

  const grid = el("div", { class: "card-grid" });
  for (const r of reports) {
    const card = el("div", { class: "report-card" });
    card.append(
      el("div", { class: "title" }, r.title),
      el("div", { class: "small mono muted" }, r.id),
      el("div", {},
        el("span", { class: "badge" + (r.has_results ? "" : " gray") },
          r.has_results ? "入力済" : "未入力"),
        r.saved_at ? el("span", { class: "small muted" }, " 保存: " + r.saved_at) : "",
      ),
    );
    if (r.error) card.append(el("div", { class: "form-error small" }, "定義エラー: " + r.error));
    const actions = el("div", { class: "actions" });
    actions.append(
      el("button", { class: "primary small-btn", onclick: () => (location.hash = `#/report/${r.id}`) }, "開く"),
      el("button", { class: "small-btn", onclick: () => (location.hash = `#/report/${r.id}/edit`) }, "定義を編集"),
      el("span", { class: "spacer" }),
      el("button", {
        class: "danger small-btn",
        onclick: async () => {
          if (!confirm(`レポート「${r.title}」(${r.id}) を削除します。よろしいですか?\nこの操作は取り消せません。`)) return;
          await api.deleteReport(r.id);
          renderHome(app);
        },
      }, "削除"),
    );
    card.append(actions);
    grid.append(card);
  }
  app.append(grid);
  return null;
}

async function openNewReportModal() {
  const templates = await api.listTemplates();

  const idInput = el("input", { type: "text", placeholder: "例: exp3_free_fall(英数字・_・-)" });
  const srcSelect = el("select", {});
  srcSelect.append(el("option", { value: "" }, "空のYAMLから作成(下に貼り付け)"));
  for (const t of templates) {
    srcSelect.append(el("option", { value: t.id }, `テンプレート: ${t.title} (${t.id})`));
  }
  const yamlArea = el("textarea", {
    placeholder: "ここに定義YAMLを貼り付け(テンプレート選択時は自動入力されます)",
  });
  const fileInput = el("input", { type: "file", accept: ".yaml,.yml,.txt" });
  const errBox = el("div", { class: "form-error" });

  srcSelect.addEventListener("change", () => {
    const t = templates.find((x) => x.id === srcSelect.value);
    if (t) yamlArea.value = t.yaml;
  });
  fileInput.addEventListener("change", async () => {
    const f = fileInput.files[0];
    if (f) yamlArea.value = await f.text();
  });

  openModal((close) => {
    const box = el("div", {});
    box.append(
      el("h2", {}, "新規レポート"),
      el("div", { class: "row" }, el("label", {}, "レポートID"), idInput),
      el("div", { class: "row" }, el("label", {}, "定義の元"), srcSelect),
      el("div", { class: "row" }, el("label", {}, "定義YAMLファイルを選択(任意)"), fileInput),
      el("div", { class: "row" }, el("label", {}, "定義YAML"), yamlArea),
      errBox,
      el("div", { class: "modal-actions" },
        el("button", { onclick: close }, "キャンセル"),
        el("button", {
          class: "primary",
          onclick: async () => {
            errBox.textContent = "";
            const id = idInput.value.trim();
            if (!id) { errBox.textContent = "レポートIDを入力してください"; return; }
            if (!yamlArea.value.trim()) { errBox.textContent = "定義YAMLを入力してください"; return; }
            try {
              await api.createReport({ id, yaml: yamlArea.value });
              close();
              location.hash = `#/report/${id}`;
            } catch (e) {
              errBox.textContent = e.message;
            }
          },
        }, "作成"),
      ),
    );
    return box;
  });
}
