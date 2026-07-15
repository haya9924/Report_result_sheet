"""定義YAMLのロード・バリデーション。

AIが生成するYAMLの品質を担保する検問所。未知キー・名前重複・禁止構文・
未定義参照・循環依存はすべて「値の入力前」にここで検出する。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

import yaml

from resultsheet.engine.graph import topological_order
from resultsheet.engine.safe_eval import extract_references
from resultsheet.errors import DefinitionError, EvalError

_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

DEFAULT_MIN_ROWS = 3


@dataclass
class Constant:
    name: str
    value: float
    unit: str | None = None
    description: str | None = None


@dataclass
class Input:
    name: str
    label: str
    unit: str | None = None
    description: str | None = None
    display: dict | None = None
    range: dict | None = None


@dataclass
class Column:
    name: str
    label: str
    unit: str | None = None
    description: str | None = None
    range: dict | None = None


@dataclass
class DerivedColumn:
    name: str
    expr: str
    label: str | None = None
    unit: str | None = None
    display: dict | None = None
    range: dict | None = None


@dataclass
class Table:
    name: str
    label: str
    columns: list[Column]
    derived_columns: list[DerivedColumn] = field(default_factory=list)
    description: str | None = None
    min_rows: int = DEFAULT_MIN_ROWS


@dataclass
class Derived:
    name: str
    expr: str
    label: str | None = None
    unit: str | None = None
    description: str | None = None
    display: dict | None = None
    range: dict | None = None


@dataclass
class Definition:
    id: str
    title: str
    description: str | None
    constants: list[Constant]
    inputs: list[Input]
    tables: list[Table]
    derived: list[Derived]
    source_yaml: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.source_yaml.encode("utf-8")).hexdigest()

    def table(self, name: str) -> Table:
        for t in self.tables:
            if t.name == name:
                return t
        raise DefinitionError(f"テーブル {name!r} は定義されていません")


def load_definition(text: str) -> Definition:
    """YAML文字列から Definition を構築し、全面的に検証する。"""
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise DefinitionError(f"YAMLを解釈できません: {e}") from e
    if not isinstance(raw, dict):
        raise DefinitionError("定義ファイルのトップレベルはマッピングにしてください")

    _check_keys(raw, {"meta", "constants", "inputs", "tables", "derived"}, "トップレベル")

    meta = raw.get("meta")
    if not isinstance(meta, dict):
        raise DefinitionError("meta (id, title) は必須です")
    _check_keys(meta, {"id", "title", "description"}, "meta")
    rid = _req_str(meta, "id", "meta")
    if not _NAME_RE.match(rid):
        raise DefinitionError(f"meta.id {rid!r} は英数字とアンダースコアのみ使用できます")
    title = _req_str(meta, "title", "meta")

    constants = _parse_constants(raw.get("constants"))
    inputs = _parse_inputs(raw.get("inputs"))
    tables = _parse_tables(raw.get("tables"))
    derived = _parse_derived(raw.get("derived"))

    definition = Definition(
        id=rid,
        title=title,
        description=_opt_str(meta, "description", "meta"),
        constants=constants,
        inputs=inputs,
        tables=tables,
        derived=derived,
        source_yaml=text,
    )
    _validate_names(definition)
    _validate_expressions(definition)
    return definition


# ---------------------------------------------------------------- パース各部

def _parse_constants(raw) -> list[Constant]:
    if raw is None:
        return []
    if not isinstance(raw, dict):
        raise DefinitionError("constants は「名前: {value: ...}」のマッピングにしてください")
    out = []
    for name, spec in raw.items():
        if not isinstance(spec, dict):
            raise DefinitionError(f"constants.{name} は {{value: 数値}} の形にしてください")
        _check_keys(spec, {"value", "unit", "description"}, f"constants.{name}")
        value = spec.get("value")
        if not _is_number(value):
            raise DefinitionError(f"constants.{name}.value は数値にしてください")
        out.append(
            Constant(
                name=str(name),
                value=float(value),
                unit=_opt_str(spec, "unit", f"constants.{name}"),
                description=_opt_str(spec, "description", f"constants.{name}"),
            )
        )
    return out


def _parse_inputs(raw) -> list[Input]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise DefinitionError("inputs はリストにしてください")
    out = []
    for i, item in enumerate(raw):
        ctx = f"inputs[{i}]"
        if not isinstance(item, dict):
            raise DefinitionError(f"{ctx} はマッピングにしてください")
        _check_keys(item, {"name", "label", "unit", "description", "display", "range"}, ctx)
        out.append(
            Input(
                name=_req_str(item, "name", ctx),
                label=_req_str(item, "label", ctx),
                unit=_opt_str(item, "unit", ctx),
                description=_opt_str(item, "description", ctx),
                display=_parse_display(item.get("display"), ctx),
                range=_parse_range(item.get("range"), ctx),
            )
        )
    return out


def _parse_tables(raw) -> list[Table]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise DefinitionError("tables はリストにしてください")
    out = []
    for i, item in enumerate(raw):
        ctx = f"tables[{i}]"
        if not isinstance(item, dict):
            raise DefinitionError(f"{ctx} はマッピングにしてください")
        _check_keys(
            item,
            {"name", "label", "description", "min_rows", "columns", "derived_columns"},
            ctx,
        )
        tname = _req_str(item, "name", ctx)
        cols_raw = item.get("columns")
        if not isinstance(cols_raw, list) or not cols_raw:
            raise DefinitionError(f"{ctx} ({tname}): columns は 1 つ以上必要です")
        columns = []
        for j, c in enumerate(cols_raw):
            cctx = f"{ctx}.columns[{j}]"
            if not isinstance(c, dict):
                raise DefinitionError(f"{cctx} はマッピングにしてください")
            _check_keys(c, {"name", "label", "unit", "description", "range"}, cctx)
            columns.append(
                Column(
                    name=_req_str(c, "name", cctx),
                    label=_req_str(c, "label", cctx),
                    unit=_opt_str(c, "unit", cctx),
                    description=_opt_str(c, "description", cctx),
                    range=_parse_range(c.get("range"), cctx),
                )
            )
        dcols = []
        for j, c in enumerate(item.get("derived_columns") or []):
            cctx = f"{ctx}.derived_columns[{j}]"
            if not isinstance(c, dict):
                raise DefinitionError(f"{cctx} はマッピングにしてください")
            _check_keys(c, {"name", "label", "expr", "unit", "display", "range"}, cctx)
            dcols.append(
                DerivedColumn(
                    name=_req_str(c, "name", cctx),
                    expr=_req_str(c, "expr", cctx),
                    label=_opt_str(c, "label", cctx),
                    unit=_opt_str(c, "unit", cctx),
                    display=_parse_display(c.get("display"), cctx),
                    range=_parse_range(c.get("range"), cctx),
                )
            )
        min_rows = item.get("min_rows", DEFAULT_MIN_ROWS)
        if not isinstance(min_rows, int) or min_rows < 1:
            raise DefinitionError(f"{ctx} ({tname}): min_rows は 1 以上の整数にしてください")
        out.append(
            Table(
                name=tname,
                label=_req_str(item, "label", ctx),
                description=_opt_str(item, "description", ctx),
                min_rows=min_rows,
                columns=columns,
                derived_columns=dcols,
            )
        )
    return out


def _parse_derived(raw) -> list[Derived]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise DefinitionError("derived はリストにしてください")
    out = []
    for i, item in enumerate(raw):
        ctx = f"derived[{i}]"
        if not isinstance(item, dict):
            raise DefinitionError(f"{ctx} はマッピングにしてください")
        _check_keys(
            item, {"name", "label", "expr", "unit", "description", "display", "range"}, ctx
        )
        out.append(
            Derived(
                name=_req_str(item, "name", ctx),
                expr=_req_str(item, "expr", ctx),
                label=_opt_str(item, "label", ctx),
                unit=_opt_str(item, "unit", ctx),
                description=_opt_str(item, "description", ctx),
                display=_parse_display(item.get("display"), ctx),
                range=_parse_range(item.get("range"), ctx),
            )
        )
    return out


def _parse_display(raw, ctx: str) -> dict | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise DefinitionError(f"{ctx}.display は {{sigfigs: N}} か {{decimals: N}} にしてください")
    _check_keys(raw, {"sigfigs", "decimals"}, f"{ctx}.display")
    if ("sigfigs" in raw) == ("decimals" in raw):
        raise DefinitionError(
            f"{ctx}.display は sigfigs / decimals のどちらか一方だけを指定してください"
        )
    if "sigfigs" in raw:
        n = raw["sigfigs"]
        if not isinstance(n, int) or n < 1:
            raise DefinitionError(f"{ctx}.display.sigfigs は 1 以上の整数にしてください")
        return {"sigfigs": n}
    n = raw["decimals"]
    if not isinstance(n, int) or n < 0:
        raise DefinitionError(f"{ctx}.display.decimals は 0 以上の整数にしてください")
    return {"decimals": n}


def _parse_range(raw, ctx: str) -> dict | None:
    """妥当範囲 range: {min, max, message?} をパース・検証する。

    min / max は片方だけの指定も可(下限のみ・上限のみ)。誤差を考えても
    あり得ない範囲の外側を弾くための緩い境界を想定。範囲外でも入力自体は
    ブロックせず、警告を出すためだけに使う。
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise DefinitionError(
            f"{ctx}.range は {{min: 数値, max: 数値}} の形にしてください"
        )
    _check_keys(raw, {"min", "max", "message"}, f"{ctx}.range")
    lo, hi = raw.get("min"), raw.get("max")
    if lo is None and hi is None:
        raise DefinitionError(f"{ctx}.range は min か max の少なくとも一方が必要です")
    for key, v in (("min", lo), ("max", hi)):
        if v is not None and not _is_number(v):
            raise DefinitionError(f"{ctx}.range.{key} は数値にしてください")
    if lo is not None and hi is not None and float(lo) > float(hi):
        raise DefinitionError(f"{ctx}.range は min <= max にしてください")
    message = raw.get("message")
    if message is not None and not isinstance(message, str):
        raise DefinitionError(f"{ctx}.range.message は文字列にしてください")
    return {
        "min": float(lo) if lo is not None else None,
        "max": float(hi) if hi is not None else None,
        "message": message,
    }


# ------------------------------------------------------------ 検証(名前・式)

def _validate_names(d: Definition) -> None:
    from resultsheet.engine.functions import CONSTANTS, FUNCTIONS

    seen: dict[str, str] = {}

    def add(name: str, kind: str) -> None:
        if not _NAME_RE.match(name):
            raise DefinitionError(
                f"{kind} の名前 {name!r} は英字またはアンダースコアで始まる"
                "英数字のみ使用できます"
            )
        if name in FUNCTIONS or name in CONSTANTS:
            raise DefinitionError(
                f"{kind} の名前 {name!r} は組み込みの関数/定数と衝突しています"
            )
        if name in seen:
            raise DefinitionError(
                f"名前 {name!r} が重複しています ({seen[name]} と {kind})"
            )
        seen[name] = kind

    for c in d.constants:
        add(c.name, "constants")
    for i in d.inputs:
        add(i.name, "inputs")
    for t in d.tables:
        add(t.name, "tables")
        col_seen: set[str] = set()
        for col in t.columns + list(t.derived_columns):
            if not _NAME_RE.match(col.name):
                raise DefinitionError(
                    f"テーブル {t.name} の列名 {col.name!r} は英数字と"
                    "アンダースコアのみ使用できます"
                )
            if col.name in col_seen:
                raise DefinitionError(
                    f"テーブル {t.name} の列名 {col.name!r} が重複しています"
                )
            col_seen.add(col.name)
    for dv in d.derived:
        add(dv.name, "derived")


def _refs(expr: str, ctx: str) -> set[str]:
    """式の参照抽出。禁止構文・構文エラーは DefinitionError に変換する。"""
    try:
        return extract_references(expr)
    except EvalError as e:
        raise DefinitionError(f"{ctx}: {e}") from e


def _validate_expressions(d: Definition) -> None:
    """全式の禁止構文・未定義参照・循環依存を入力前に検出する。"""
    scalar_names = {c.name for c in d.constants} | {i.name for i in d.inputs}
    table_cols = {
        f"{t.name}.{c.name}"
        for t in d.tables
        for c in list(t.columns) + list(t.derived_columns)
    }

    # 表の行内導出列: 同じ表の列(裸名)+ スカラー(constants / inputs / derived)を参照可。
    # スカラー導出量(例: HI_factor)は導出列より先に評価されるため参照できる。
    derived_scalar_names = {dv.name for dv in d.derived}
    dcol_scalar_names = scalar_names | derived_scalar_names
    for t in d.tables:
        row_names = {c.name for c in t.columns}
        exprs = {dc.name: dc.expr for dc in t.derived_columns}
        for dc in t.derived_columns:
            for ref in _refs(dc.expr, f"テーブル {t.name} の導出列 {dc.name}"):
                if "." in ref:
                    raise DefinitionError(
                        f"テーブル {t.name} の導出列 {dc.name}: 行内の式では"
                        f"「{ref}」のようなテーブル参照は使えません。"
                        "同じ表の列は列名だけで参照してください"
                    )
                if ref not in row_names and ref not in exprs and ref not in dcol_scalar_names:
                    raise DefinitionError(
                        f"テーブル {t.name} の導出列 {dc.name}: {ref!r} は"
                        "定義されていません(参照できるのは同じ表の列・constants・inputs・derived)"
                    )
        topological_order(exprs, row_names | dcol_scalar_names)  # 循環検出

    # スカラー導出量: constants / inputs / 他の derived / table.col を参照可
    derived_exprs = {dv.name: dv.expr for dv in d.derived}
    for dv in d.derived:
        for ref in _refs(dv.expr, f"derived {dv.name}"):
            if "." in ref:
                if ref not in table_cols:
                    raise DefinitionError(
                        f"derived {dv.name}: テーブル列 {ref!r} は定義されていません"
                    )
            elif ref not in scalar_names and ref not in derived_exprs:
                raise DefinitionError(
                    f"derived {dv.name}: {ref!r} は定義されていません"
                )
    topological_order(derived_exprs, scalar_names | table_cols)  # 循環検出


# ------------------------------------------------------------------ ユーティリティ

def _check_keys(d: dict, allowed: set[str], ctx: str) -> None:
    unknown = set(d) - allowed
    if unknown:
        raise DefinitionError(
            f"{ctx} に未知のキーがあります: {', '.join(sorted(str(k) for k in unknown))}"
            f"(使用可能: {', '.join(sorted(allowed))})"
        )


def _req_str(d: dict, key: str, ctx: str) -> str:
    v = d.get(key)
    if not isinstance(v, str) or not v.strip():
        raise DefinitionError(f"{ctx}.{key} は必須の文字列です")
    return v.strip()


def _opt_str(d: dict, key: str, ctx: str) -> str | None:
    v = d.get(key)
    if v is None:
        return None
    if not isinstance(v, str):
        raise DefinitionError(f"{ctx}.{key} は文字列にしてください")
    return v


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)
