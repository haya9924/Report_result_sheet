// 小さな DOM ユーティリティとモーダル

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith("on") && typeof v === "function") {
      node.addEventListener(k.slice(2), v);
    } else if (v !== null && v !== undefined) {
      node.setAttribute(k, v);
    }
  }
  for (const c of children) {
    if (c === null || c === undefined || c === "") continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

export function openModal(build) {
  const root = document.getElementById("modal-root");
  const backdrop = el("div", { class: "modal-backdrop" });
  const modal = el("div", { class: "modal" });
  const close = () => backdrop.remove();
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });
  modal.append(build(close));
  backdrop.append(modal);
  root.append(backdrop);
  return close;
}

export function debounce(fn, ms) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

// 数値入力欄の値を number | null に変換(空欄・不正は null、不正は invalid クラス)
export function parseNumberInput(input) {
  const raw = input.value.trim();
  if (raw === "") {
    input.classList.remove("invalid");
    return null;
  }
  const v = Number(raw);
  if (Number.isFinite(v)) {
    input.classList.remove("invalid");
    return v;
  }
  input.classList.add("invalid");
  return null;
}
