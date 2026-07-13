// fetch ラッパ。API エラーはメッセージ付きの Error として投げる。

async function request(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  if (res.status === 204) return null;
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) {
    let msg;
    if (data && typeof data === "object" && data.detail) {
      msg = data.detail.message || JSON.stringify(data.detail);
    } else {
      msg = typeof data === "string" ? data : JSON.stringify(data);
    }
    throw new Error(msg);
  }
  return data;
}

export const api = {
  listReports: () => request("GET", "/api/reports"),
  listTemplates: () => request("GET", "/api/templates"),
  createReport: (payload) => request("POST", "/api/reports", payload),
  deleteReport: (id) => request("DELETE", `/api/reports/${id}`),
  getReport: (id) => request("GET", `/api/reports/${id}`),
  getDefinition: (id) => request("GET", `/api/reports/${id}/definition`),
  putDefinition: (id, yaml) => request("PUT", `/api/reports/${id}/definition`, { yaml }),
  validate: (yaml) => request("POST", "/api/validate", { yaml }),
  compute: (id, payload) => request("POST", `/api/reports/${id}/compute`, payload),
  saveResults: (id, payload) => request("PUT", `/api/reports/${id}/results`, payload),
  exportReport: (id, format) => request("GET", `/api/reports/${id}/export?format=${format}`),
};
