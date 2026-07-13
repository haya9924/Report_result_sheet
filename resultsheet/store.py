"""レポートの永続化層。

1 レポート = reports/<id>/ ディレクトリ:
  definition.yaml  … 定義(真実のソースその1)
  results.json     … 入力値(真実のソースその2)+ 計算キャッシュ(computed)

computed はロードのたびに再計算して照合できるキャッシュであり、
verify() が「保存時の計算」と「現在の定義での再計算」の一致を検証する。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

from resultsheet.engine.compute import ComputeResult, compute_all
from resultsheet.errors import StoreError
from resultsheet.schema import Definition, load_definition

SCHEMA_VERSION = 1
_ID_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_-]*$")


@dataclass
class Report:
    id: str
    definition: Definition
    results: dict | None  # results.json の生データ(なければ None)


class ReportStore:
    def __init__(self, reports_dir: Path):
        self.reports_dir = Path(reports_dir)

    # ------------------------------------------------------------- 一覧・取得

    def list_reports(self) -> list[dict]:
        out = []
        if not self.reports_dir.is_dir():
            return out
        for d in sorted(self.reports_dir.iterdir()):
            def_path = d / "definition.yaml"
            if not d.is_dir() or not def_path.is_file():
                continue
            entry = {"id": d.name, "title": d.name, "has_results": False, "saved_at": None}
            try:
                definition = load_definition(def_path.read_text(encoding="utf-8"))
                entry["title"] = definition.title
            except Exception as e:  # 壊れた定義も一覧には出す(GUIで直せるように)
                entry["error"] = str(e)
            res_path = d / "results.json"
            if res_path.is_file():
                entry["has_results"] = True
                try:
                    entry["saved_at"] = json.loads(
                        res_path.read_text(encoding="utf-8")
                    ).get("saved_at")
                except Exception:
                    pass
            out.append(entry)
        return out

    def load(self, report_id: str) -> Report:
        d = self._report_dir(report_id)
        def_path = d / "definition.yaml"
        if not def_path.is_file():
            raise StoreError(f"レポート {report_id!r} は存在しません")
        definition = load_definition(def_path.read_text(encoding="utf-8"))
        results = None
        res_path = d / "results.json"
        if res_path.is_file():
            try:
                results = json.loads(res_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                raise StoreError(f"{res_path} を解釈できません: {e}") from e
        return Report(id=report_id, definition=definition, results=results)

    def definition_text(self, report_id: str) -> str:
        d = self._report_dir(report_id)
        def_path = d / "definition.yaml"
        if not def_path.is_file():
            raise StoreError(f"レポート {report_id!r} は存在しません")
        return def_path.read_text(encoding="utf-8")

    # ------------------------------------------------------------- 作成・更新

    def create(self, report_id: str, yaml_text: str) -> Report:
        self._check_id(report_id)
        d = self.reports_dir / report_id
        if (d / "definition.yaml").is_file():
            raise StoreError(f"レポート {report_id!r} は既に存在します")
        load_definition(yaml_text)  # 保存前に検証
        d.mkdir(parents=True, exist_ok=True)
        (d / "definition.yaml").write_text(yaml_text, encoding="utf-8")
        return self.load(report_id)

    def update_definition(self, report_id: str, yaml_text: str) -> Report:
        d = self._report_dir(report_id)
        if not (d / "definition.yaml").is_file():
            raise StoreError(f"レポート {report_id!r} は存在しません")
        load_definition(yaml_text)  # 保存前に検証
        (d / "definition.yaml").write_text(yaml_text, encoding="utf-8")
        return self.load(report_id)

    def delete(self, report_id: str) -> None:
        d = self._report_dir(report_id)
        if not d.is_dir():
            raise StoreError(f"レポート {report_id!r} は存在しません")
        for p in sorted(d.rglob("*"), reverse=True):
            p.unlink() if p.is_file() else p.rmdir()
        d.rmdir()

    def save_results(self, report_id: str, inputs: dict, tables: dict) -> dict:
        """入力値をサーバ側で再計算したうえで results.json に保存する。"""
        report = self.load(report_id)
        computed = compute_all(report.definition, inputs, tables)
        payload = build_results_payload(report.definition, inputs, tables, computed)
        path = self._report_dir(report_id) / "results.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return payload

    # ---------------------------------------------------------------- 検証

    def verify(self, report_id: str) -> list[str]:
        """保存済み computed と再計算の一致・定義ハッシュ一致を検証。

        問題のリストを返す(空なら整合)。
        """
        report = self.load(report_id)
        if report.results is None:
            return ["results.json がまだ保存されていません"]
        problems: list[str] = []
        saved = report.results
        if saved.get("definition_sha256") != report.definition.sha256:
            problems.append(
                "定義ファイルが保存時から変更されています"
                "(保存し直すと computed が現在の定義で再計算されます)"
            )
        recomputed = compute_all(
            report.definition, saved.get("inputs", {}), saved.get("tables", {})
        )
        for name, entry in recomputed.computed.items():
            saved_entry = saved.get("computed", {}).get(name)
            if saved_entry is None:
                problems.append(f"computed.{name} が保存されていません")
                continue
            if saved_entry.get("value") != entry["value"]:
                problems.append(
                    f"computed.{name}: 保存値 {saved_entry.get('value')!r} と"
                    f"再計算値 {entry['value']!r} が一致しません"
                )
            if saved_entry.get("display") != entry["display"]:
                problems.append(
                    f"computed.{name}: 表示値 {saved_entry.get('display')!r} と"
                    f"再計算表示値 {entry['display']!r} が一致しません"
                )
        for tname, cols in recomputed.computed_columns.items():
            saved_cols = saved.get("computed_columns", {}).get(tname, {})
            for cname, vec in cols.items():
                if saved_cols.get(cname) != vec:
                    problems.append(
                        f"computed_columns.{tname}.{cname} が再計算と一致しません"
                    )
        return problems

    # ------------------------------------------------------------ 内部

    def _report_dir(self, report_id: str) -> Path:
        self._check_id(report_id)
        return self.reports_dir / report_id

    @staticmethod
    def _check_id(report_id: str) -> None:
        if not _ID_RE.match(report_id):
            raise StoreError(
                f"レポートID {report_id!r} は英字で始まる英数字・ハイフン・"
                "アンダースコアのみ使用できます"
            )


def build_results_payload(
    definition: Definition, inputs: dict, tables: dict, computed: ComputeResult
) -> dict:
    """results.json の中身を組み立てる(json.dump デフォルトの repr ベース
    シリアライズで float の完全ラウンドトリップを保証)。"""
    return {
        "schema_version": SCHEMA_VERSION,
        "report_id": definition.id,
        "definition_sha256": definition.sha256,
        "saved_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "inputs": {i.name: inputs.get(i.name) for i in definition.inputs},
        "tables": {
            t.name: _normalize_table(t, tables.get(t.name)) for t in definition.tables
        },
        "computed": computed.computed,
        "computed_columns": computed.computed_columns,
    }


def _normalize_table(table, data) -> dict:
    columns = [c.name for c in table.columns]
    if data is None:
        return {"columns": columns, "rows": []}
    in_cols = data.get("columns", columns)
    rows = []
    for row in data.get("rows", []):
        by_col = dict(zip(in_cols, row))
        rows.append([by_col.get(c) for c in columns])
    return {"columns": columns, "rows": rows}


# ------------------------------------------------------------- テンプレート

def list_templates() -> list[dict]:
    """同梱テンプレート一覧: [{id, title, yaml}]。"""
    out = []
    root = resources.files("resultsheet") / "templates"
    for entry in sorted(root.iterdir(), key=lambda e: e.name):
        if not entry.name.endswith(".yaml"):
            continue
        text = entry.read_text(encoding="utf-8")
        try:
            definition = load_definition(text)
            title = definition.title
        except Exception:
            title = entry.name
        out.append({"id": entry.name[: -len(".yaml")], "title": title, "yaml": text})
    return out


def get_template(template_id: str) -> str:
    for t in list_templates():
        if t["id"] == template_id:
            return t["yaml"]
    raise StoreError(f"テンプレート {template_id!r} は存在しません")
