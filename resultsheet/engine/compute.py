"""計算オーケストレーション。

compute_all() が CLI / API / 保存処理から呼ばれる唯一の計算入口。
評価順序:
  1. namespace ← constants + inputs
  2. 各テーブル: 入力列をベクトル化 → derived_columns を行ごとにトポ順評価
  3. namespace に table.col ベクトル(入力列 + 導出列)を登録
  4. derived をトポ順に評価し、逐次 namespace へ
値はすべてフル精度 float(未確定は None)。display は表示専用の文字列。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from resultsheet.engine import rounding
from resultsheet.engine.graph import topological_order
from resultsheet.engine.safe_eval import evaluate
from resultsheet.errors import EvalError

if TYPE_CHECKING:
    from resultsheet.schema import Definition


@dataclass
class ComputeResult:
    # derived 名 -> {value, display, unit, expr, label, rounding, error?}
    computed: dict[str, dict] = field(default_factory=dict)
    # テーブル名 -> 導出列名 -> フル精度値リスト
    computed_columns: dict[str, dict[str, list]] = field(default_factory=dict)
    # テーブル名 -> 導出列名 -> 表示文字列リスト
    computed_columns_display: dict[str, dict[str, list]] = field(default_factory=dict)
    # 変数名 / "table.col" -> エラーメッセージ
    errors: dict[str, str] = field(default_factory=dict)


def compute_all(definition: Definition, inputs: dict, tables: dict) -> ComputeResult:
    """定義と入力値から全導出量を計算する。

    inputs: {name: 数値 | None}
    tables: {テーブル名: {"columns": [列名...], "rows": [[...], ...]}}
    部分入力を許容し、計算できない値は None として伝播する。
    個別の式のエラー(ゼロ除算など)はその変数だけ止め、他は計算を続ける。
    """
    result = ComputeResult()
    ns: dict = {}

    for c in definition.constants:
        ns[c.name] = c.value
    for i in definition.inputs:
        ns[i.name] = _as_number(inputs.get(i.name), i.name)

    for t in definition.tables:
        col_vectors = _table_vectors(t, tables.get(t.name))
        n_rows = len(next(iter(col_vectors.values()))) if col_vectors else 0

        dcol_exprs = {dc.name: dc.expr for dc in t.derived_columns}
        dcol_by_name = {dc.name: dc for dc in t.derived_columns}
        order = topological_order(dcol_exprs, set(col_vectors) | set(ns))

        derived_vectors: dict[str, list] = {name: [] for name in dcol_exprs}
        for name in order:
            dc = dcol_by_name[name]
            values: list = []
            for r in range(n_rows):
                row_ns = dict(ns)
                for col, vec in col_vectors.items():
                    row_ns[col] = vec[r]
                for done, vec in derived_vectors.items():
                    if len(vec) == n_rows:
                        row_ns[done] = vec[r]
                try:
                    values.append(evaluate(dc.expr, row_ns))
                except EvalError as e:
                    values.append(None)
                    result.errors.setdefault(f"{t.name}.{name}", str(e))
            derived_vectors[name] = values

        result.computed_columns[t.name] = derived_vectors
        result.computed_columns_display[t.name] = {
            name: [
                rounding.format_display(v, dcol_by_name[name].display) for v in vec
            ]
            for name, vec in derived_vectors.items()
        }
        for col, vec in col_vectors.items():
            ns[f"{t.name}.{col}"] = vec
        for name, vec in derived_vectors.items():
            ns[f"{t.name}.{name}"] = vec

    derived_exprs = {dv.name: dv.expr for dv in definition.derived}
    derived_by_name = {dv.name: dv for dv in definition.derived}
    for name in topological_order(derived_exprs, set(ns)):
        dv = derived_by_name[name]
        error: str | None = None
        try:
            value = evaluate(dv.expr, ns)
        except EvalError as e:
            value, error = None, str(e)
        ns[name] = value
        entry = {
            "value": value,
            "display": rounding.format_display(value, dv.display),
            "unit": dv.unit,
            "expr": dv.expr,
            "label": dv.label,
            "rounding": dv.display or {"sigfigs": rounding.DEFAULT_SIGFIGS},
        }
        if error is not None:
            entry["error"] = error
            result.errors[name] = error
        result.computed[name] = entry

    return result


def fit_line(x: list, y: list) -> dict:
    """散布図のアドホックフィット用: y = a x + b の a, b, r を返す。"""
    from resultsheet.engine.functions import _intercept, _rvalue, _slope

    return {
        "slope": _slope(x, y),
        "intercept": _intercept(x, y),
        "rvalue": _rvalue(x, y),
    }


def _table_vectors(table, data) -> dict[str, list]:
    """入力テーブルデータを {列名: 値リスト} に正規化する。

    data は {"columns": [...], "rows": [[...], ...]} 形式。列は定義済み入力列の
    サブセットであること。欠けた列・欠けたセルは None で埋める。
    """
    defined = [c.name for c in table.columns]
    if data is None:
        return {name: [] for name in defined}
    if not isinstance(data, dict):
        raise EvalError(f"テーブル {table.name} のデータ形式が不正です")
    columns = data.get("columns", defined)
    if not isinstance(columns, list):
        raise EvalError(f"テーブル {table.name}: columns はリストにしてください")
    unknown = set(columns) - set(defined)
    if unknown:
        raise EvalError(
            f"テーブル {table.name}: 未知の列 {', '.join(sorted(unknown))} が含まれています"
        )
    rows = data.get("rows", [])
    if not isinstance(rows, list):
        raise EvalError(f"テーブル {table.name}: rows はリストにしてください")

    vectors: dict[str, list] = {name: [] for name in defined}
    for r, row in enumerate(rows):
        if not isinstance(row, list):
            raise EvalError(f"テーブル {table.name} の {r + 1} 行目が行形式ではありません")
        by_col = dict(zip(columns, row))
        for name in defined:
            vectors[name].append(_as_number(by_col.get(name), f"{table.name}.{name}"))
    return vectors


def _as_number(v, name: str) -> float | None:
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise EvalError(f"{name} の値 {v!r} は数値ではありません")
    return float(v)
