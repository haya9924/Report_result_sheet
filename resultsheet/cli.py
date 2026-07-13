"""CLI — AI(Claude など)が CUI から結果を取得・検証するためのインターフェース。

人間が使うのは `resultsheet serve` だけで、以降の操作はすべてブラウザで完結する。
それ以外のサブコマンドは、AI がレポート執筆時に値・式・表示値を機械可読で
参照するためのもの:

  resultsheet show <report> --format json   # 全結果ダンプ(主要参照点)
  resultsheet get <report> <var>            # 1変数の value/display/expr/unit
  resultsheet verify <report>               # 保存値と再計算の一致検証
  resultsheet validate <yaml>               # 定義YAMLの静的検証
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from resultsheet import __version__
from resultsheet.engine.compute import compute_all
from resultsheet.errors import ResultSheetError
from resultsheet.store import ReportStore

DEFAULT_REPORTS_DIR = "reports"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except ResultSheetError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="resultsheet",
        description="実験レポートの結果入力システム(GUI起動 + AI向けデータ取得CLI)",
    )
    parser.add_argument("--version", action="version", version=f"resultsheet {__version__}")
    parser.add_argument(
        "--reports-dir",
        default=DEFAULT_REPORTS_DIR,
        help=f"レポート保存ディレクトリ (default: ./{DEFAULT_REPORTS_DIR})",
    )
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("serve", help="Web GUI サーバーを起動(人間用の唯一のコマンド)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("list", help="レポート一覧")
    p.add_argument("--json", action="store_true", dest="as_json")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("validate", help="定義YAMLファイルの静的検証 (exit 0/1)")
    p.add_argument("path", help="定義YAMLのパス")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("show", help="レポートの全結果ダンプ(AIの主要参照点)")
    p.add_argument("report")
    p.add_argument("--format", choices=["json", "md"], default="json")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("get", help="特定変数の値・式・表示値を取得")
    p.add_argument("report")
    p.add_argument("var", help="変数名 または テーブル名.列名")
    p.add_argument("--json", action="store_true", dest="as_json")
    p.set_defaults(func=cmd_get)

    p = sub.add_parser("verify", help="保存済み結果と再計算の一致・定義ハッシュを検証 (exit 0/1)")
    p.add_argument("report")
    p.set_defaults(func=cmd_verify)

    return parser


def _store(args) -> ReportStore:
    return ReportStore(Path(args.reports_dir))


def _dump_json(obj) -> None:
    # json.dump デフォルトの repr ベース出力で float の完全ラウンドトリップを保証
    print(json.dumps(obj, ensure_ascii=False, indent=2))


# ------------------------------------------------------------------ commands

def cmd_serve(args) -> int:
    import uvicorn

    from resultsheet.server import create_app

    reports_dir = Path(args.reports_dir).resolve()
    reports_dir.mkdir(parents=True, exist_ok=True)
    print(f"レポートディレクトリ: {reports_dir}")
    print(f"ブラウザで http://{args.host}:{args.port}/ を開いてください")
    uvicorn.run(create_app(reports_dir), host=args.host, port=args.port, log_level="info")
    return 0


def cmd_list(args) -> int:
    reports = _store(args).list_reports()
    if args.as_json:
        _dump_json(reports)
        return 0
    if not reports:
        print("(レポートはまだありません)")
        return 0
    for r in reports:
        mark = "入力済" if r["has_results"] else "未入力"
        print(f"{r['id']}\t{r['title']}\t[{mark}]" + (f"\t{r['saved_at']}" if r["saved_at"] else ""))
    return 0


def cmd_validate(args) -> int:
    from resultsheet.schema import load_definition

    path = Path(args.path)
    if not path.is_file():
        print(f"エラー: {path} が見つかりません", file=sys.stderr)
        return 1
    try:
        d = load_definition(path.read_text(encoding="utf-8"))
    except ResultSheetError as e:
        print(f"NG: {e}", file=sys.stderr)
        return 1
    n_vars = len(d.inputs) + sum(len(t.columns) + len(t.derived_columns) for t in d.tables)
    print(f"OK: {d.id} — {d.title} (入力 {n_vars} 変数 / 導出 {len(d.derived)} 量)")
    return 0


def build_show_payload(store: ReportStore, report_id: str) -> dict:
    """show の中身: 保存済み入力値から常に再計算した最新の全結果。"""
    report = store.load(report_id)
    saved = report.results or {}
    inputs = saved.get("inputs", {})
    tables = saved.get("tables", {})
    result = compute_all(report.definition, inputs, tables)

    d = report.definition
    payload = {
        "report_id": report_id,
        "title": d.title,
        "description": d.description,
        "saved_at": saved.get("saved_at"),
        "constants": {
            c.name: {"value": c.value, "unit": c.unit, "description": c.description}
            for c in d.constants
        },
        "inputs": {
            i.name: {
                "value": inputs.get(i.name),
                "unit": i.unit,
                "label": i.label,
            }
            for i in d.inputs
        },
        "tables": {
            t.name: {
                "label": t.label,
                "columns": [
                    {"name": c.name, "label": c.label, "unit": c.unit} for c in t.columns
                ],
                "rows": tables.get(t.name, {}).get("rows", []),
                "derived_columns": {
                    dc.name: {
                        "expr": dc.expr,
                        "unit": dc.unit,
                        "label": dc.label,
                        "values": result.computed_columns[t.name][dc.name],
                        "display": result.computed_columns_display[t.name][dc.name],
                    }
                    for dc in t.derived_columns
                },
            }
            for t in d.tables
        },
        "derived": result.computed,
        "errors": result.errors,
    }
    return payload


def cmd_show(args) -> int:
    payload = build_show_payload(_store(args), args.report)
    if args.format == "json":
        _dump_json(payload)
    else:
        print(render_markdown(payload))
    return 0


def render_markdown(p: dict) -> str:
    lines = [f"## {p['report_id']}: {p['title']}", ""]
    if p.get("description"):
        lines += [p["description"], ""]
    if p["inputs"]:
        lines += ["### 測定値", "", "| 変数 | 値 | 単位 | ラベル |", "|---|---|---|---|"]
        for name, e in p["inputs"].items():
            lines.append(
                f"| {name} | {_md_num(e['value'])} | {e['unit'] or ''} | {e['label']} |"
            )
        lines.append("")
    for tname, t in p["tables"].items():
        lines += [f"### 表: {t['label']} ({tname})", ""]
        heads = [c["name"] for c in t["columns"]] + list(t["derived_columns"])
        units = [c["unit"] or "" for c in t["columns"]] + [
            dc["unit"] or "" for dc in t["derived_columns"].values()
        ]
        lines.append("| # | " + " | ".join(heads) + " |")
        lines.append("|---|" + "---|" * len(heads))
        lines.append("| 単位 | " + " | ".join(units) + " |")
        n_rows = len(t["rows"])
        for r in range(n_rows):
            cells = [_md_num(v) for v in t["rows"][r]]
            cells += [dc["display"][r] for dc in t["derived_columns"].values()]
            lines.append(f"| {r + 1} | " + " | ".join(cells) + " |")
        lines.append("")
    if p["derived"]:
        lines += [
            "### 導出量",
            "",
            "| 変数 | 表示値 | 単位 | フル精度値 | 式 |",
            "|---|---|---|---|---|",
        ]
        for name, e in p["derived"].items():
            lines.append(
                f"| {name} | {e['display']} | {e['unit'] or ''} | "
                f"{_md_num(e['value'])} | `{e['expr']}` |"
            )
        lines.append("")
    if p["errors"]:
        lines += ["### エラー", ""]
        for name, msg in p["errors"].items():
            lines.append(f"- **{name}**: {msg}")
        lines.append("")
    return "\n".join(lines)


def _md_num(v) -> str:
    return "—" if v is None else repr(v)


def cmd_get(args) -> int:
    payload = build_show_payload(_store(args), args.report)
    name = args.var

    entry = None
    if name in payload["derived"]:
        e = payload["derived"][name]
        entry = {"name": name, "kind": "derived", **e}
    elif name in payload["inputs"]:
        e = payload["inputs"][name]
        entry = {"name": name, "kind": "input", **e}
    elif name in payload["constants"]:
        e = payload["constants"][name]
        entry = {"name": name, "kind": "constant", **e}
    elif "." in name:
        tname, cname = name.split(".", 1)
        t = payload["tables"].get(tname)
        if t is not None:
            if cname in t["derived_columns"]:
                dc = t["derived_columns"][cname]
                entry = {
                    "name": name,
                    "kind": "derived_column",
                    "expr": dc["expr"],
                    "unit": dc["unit"],
                    "values": dc["values"],
                    "display": dc["display"],
                }
            else:
                for idx, c in enumerate(t["columns"]):
                    if c["name"] == cname:
                        entry = {
                            "name": name,
                            "kind": "column",
                            "unit": c["unit"],
                            "values": [row[idx] for row in t["rows"]],
                        }
                        break

    if entry is None:
        print(f"エラー: 変数 {name!r} はレポート {args.report!r} に存在しません", file=sys.stderr)
        return 1

    if args.as_json:
        _dump_json(entry)
        return 0
    for key in ("name", "kind", "label", "value", "values", "display", "unit", "expr", "rounding", "error"):
        if key in entry and entry[key] is not None:
            v = entry[key]
            if key == "rounding" and isinstance(v, dict):
                v = ", ".join(f"{k}={val}" for k, val in v.items())
            elif key in ("value",) and isinstance(v, float):
                v = repr(v)
            elif isinstance(v, list):
                v = json.dumps(v, ensure_ascii=False)
            print(f"{key}: {v}")
    return 0


def cmd_verify(args) -> int:
    problems = _store(args).verify(args.report)
    if problems:
        print(f"NG: {len(problems)} 件の不整合", file=sys.stderr)
        for msg in problems:
            print(f"- {msg}", file=sys.stderr)
        return 1
    print("OK: 保存済み結果は現在の定義での再計算と一致しています")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
