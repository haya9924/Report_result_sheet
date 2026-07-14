"""FastAPI サーバー。

計算はすべてここ(= Python の engine)経由で行い、フロントエンドの JS は
一切計算しない。GUI のライブ計算は POST /api/reports/{id}/compute を叩く。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from resultsheet.cli import build_show_payload, render_markdown
from resultsheet.engine.compute import compute_all, fit_line
from resultsheet.errors import EvalError, ResultSheetError, StoreError
from resultsheet.schema import Definition, load_definition
from resultsheet.store import ReportStore, get_template, list_templates

WEB_DIR = Path(__file__).parent / "web"


def create_app(reports_dir: Path) -> FastAPI:
    app = FastAPI(title="resultsheet", docs_url=None, redoc_url=None)
    store = ReportStore(reports_dir)

    # ------------------------------------------------------------ レポート管理

    @app.get("/api/reports")
    def list_reports():
        return store.list_reports()

    @app.post("/api/reports", status_code=201)
    def create_report(body: dict = Body(...)):
        report_id = body.get("id", "")
        yaml_text = body.get("yaml")
        template = body.get("template")
        if yaml_text is None and template is None:
            _bad_request("yaml または template のどちらかを指定してください")
        if yaml_text is None:
            yaml_text = _wrap(lambda: get_template(template))
        report = _wrap(lambda: store.create(report_id, yaml_text))
        return _report_payload(report.id, report.definition, report.results)

    @app.get("/api/templates")
    def templates():
        return list_templates()

    @app.get("/api/reports/{report_id}/definition", response_class=PlainTextResponse)
    def get_definition(report_id: str):
        return _wrap(lambda: store.definition_text(report_id))

    @app.put("/api/reports/{report_id}/definition")
    def put_definition(report_id: str, body: dict = Body(...)):
        yaml_text = body.get("yaml")
        if not isinstance(yaml_text, str):
            _bad_request("yaml (文字列) は必須です")
        report = _wrap(lambda: store.update_definition(report_id, yaml_text))
        return _report_payload(report.id, report.definition, report.results)

    @app.delete("/api/reports/{report_id}", status_code=204)
    def delete_report(report_id: str):
        _wrap(lambda: store.delete(report_id))

    @app.post("/api/validate")
    def validate(body: dict = Body(...)):
        yaml_text = body.get("yaml")
        if not isinstance(yaml_text, str):
            _bad_request("yaml (文字列) は必須です")
        try:
            d = load_definition(yaml_text)
        except ResultSheetError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "definition": _definition_json(d)}

    # ---------------------------------------------------------- 入力・計算・結果

    @app.get("/api/reports/{report_id}")
    def get_report(report_id: str):
        report = _wrap(lambda: store.load(report_id))
        return _report_payload(report.id, report.definition, report.results)

    @app.post("/api/reports/{report_id}/compute")
    def compute(report_id: str, body: dict = Body(...)):
        report = _wrap(lambda: store.load(report_id))
        inputs = body.get("inputs", {})
        tables = body.get("tables", {})
        try:
            result = compute_all(report.definition, inputs, tables)
        except (EvalError, ResultSheetError) as e:
            _bad_request(str(e))
        payload = {
            "computed": result.computed,
            "computed_columns": result.computed_columns,
            "computed_columns_display": result.computed_columns_display,
            "errors": result.errors,
            "range_warnings": result.range_warnings,
        }
        adhoc = body.get("adhoc_fit")
        if adhoc:
            payload["adhoc_fit"] = _adhoc_fit(report.definition, tables, result, adhoc)
        return payload

    @app.put("/api/reports/{report_id}/results")
    def save_results(report_id: str, body: dict = Body(...)):
        return _wrap(
            lambda: store.save_results(
                report_id, body.get("inputs", {}), body.get("tables", {})
            )
        )

    @app.get("/api/reports/{report_id}/results")
    def get_results(report_id: str):
        report = _wrap(lambda: store.load(report_id))
        if report.results is None:
            raise HTTPException(404, detail={"message": "結果はまだ保存されていません"})
        return report.results

    @app.get("/api/reports/{report_id}/export")
    def export(report_id: str, format: str = "json"):
        payload = _wrap(lambda: build_show_payload(store, report_id))
        if format == "md":
            return PlainTextResponse(
                render_markdown(payload), media_type="text/markdown; charset=utf-8"
            )
        return payload

    # ------------------------------------------------------------------ 静的配信

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(WEB_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app


# ---------------------------------------------------------------------- helpers

def _wrap(fn):
    """ResultSheetError を適切な HTTP エラーに変換して実行する。"""
    try:
        return fn()
    except StoreError as e:
        msg = str(e)
        raise HTTPException(
            404 if "存在しません" in msg else 400, detail={"message": msg}
        ) from e
    except ResultSheetError as e:
        raise HTTPException(400, detail={"message": str(e)}) from e


def _bad_request(message: str):
    raise HTTPException(400, detail={"message": message})


def _adhoc_fit(definition: Definition, tables: dict, result, spec: dict) -> dict:
    """散布図用に、選択された2列の直線フィットをサーバ側で計算する。"""
    tname = spec.get("table")
    xcol, ycol = spec.get("x"), spec.get("y")
    try:
        table = definition.table(tname)
    except ResultSheetError as e:
        return {"error": str(e)}
    vectors: dict[str, list] = {}
    from resultsheet.engine.compute import _table_vectors

    try:
        vectors.update(_table_vectors(table, tables.get(tname)))
    except EvalError as e:
        return {"error": str(e)}
    vectors.update(result.computed_columns.get(tname, {}))
    if xcol not in vectors or ycol not in vectors:
        return {"error": f"列 {xcol!r} / {ycol!r} が見つかりません"}
    try:
        return fit_line(vectors[xcol], vectors[ycol])
    except EvalError as e:
        return {"error": str(e)}


def _report_payload(report_id: str, definition: Definition, results: dict | None) -> dict:
    return {
        "id": report_id,
        "definition": _definition_json(definition),
        "results": results,
    }


def _definition_json(d: Definition) -> dict:
    """フロントエンドがフォームを自動生成するための定義の完全な JSON 化。"""
    return {
        "id": d.id,
        "title": d.title,
        "description": d.description,
        "sha256": d.sha256,
        "constants": [
            {"name": c.name, "value": c.value, "unit": c.unit, "description": c.description}
            for c in d.constants
        ],
        "inputs": [
            {
                "name": i.name,
                "label": i.label,
                "unit": i.unit,
                "description": i.description,
                "display": i.display,
                "range": i.range,
            }
            for i in d.inputs
        ],
        "tables": [
            {
                "name": t.name,
                "label": t.label,
                "description": t.description,
                "min_rows": t.min_rows,
                "columns": [
                    {
                        "name": c.name,
                        "label": c.label,
                        "unit": c.unit,
                        "description": c.description,
                        "range": c.range,
                    }
                    for c in t.columns
                ],
                "derived_columns": [
                    {
                        "name": dc.name,
                        "label": dc.label,
                        "expr": dc.expr,
                        "unit": dc.unit,
                        "display": dc.display,
                        "range": dc.range,
                    }
                    for dc in t.derived_columns
                ],
            }
            for t in d.tables
        ],
        "derived": [
            {
                "name": dv.name,
                "label": dv.label,
                "expr": dv.expr,
                "unit": dv.unit,
                "description": dv.description,
                "display": dv.display,
                "range": dv.range,
            }
            for dv in d.derived
        ],
    }
