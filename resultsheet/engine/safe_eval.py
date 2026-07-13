"""AST ホワイトリスト方式のセーフ式評価器。

compile()+eval() は使わず、ast.parse した木を自前で再帰評価する。
許可する構文のみを明示的に列挙し、それ以外は理由付きの EvalError にする。
属性アクセスは「定義済みテーブル名.列名」の形しか通らないため、
`().__class__` のようなサンドボックス脱出は構文レベルで遮断される。
"""

from __future__ import annotations

import ast
import operator

from resultsheet.engine.functions import CONSTANTS, FUNCTIONS
from resultsheet.errors import EvalError

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
}

_UNARY_OPS = {
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def parse_expr(expr: str) -> ast.Expression:
    """式をパースして AST を返す。構文エラーは EvalError。"""
    try:
        return ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise EvalError(f"式 {expr!r} を解釈できません: {e.msg} (位置 {e.offset})") from e


def extract_references(expr: str) -> set[str]:
    """式が参照する名前の集合を返す。

    変数は "name"、テーブル列は "table.col" の形。組み込み定数 (pi, e) と
    関数名は含まない。禁止構文はここでも検出して EvalError にする
    (定義ロード時に全式を検査するための入口)。
    """
    tree = parse_expr(expr)
    refs: set[str] = set()
    _walk_collect(tree.body, expr, refs)
    return refs


def _walk_collect(node: ast.AST, expr: str, refs: set[str]) -> None:
    if isinstance(node, ast.Constant):
        _check_constant(node, expr)
    elif isinstance(node, ast.BinOp):
        _check_op(node.op, _BIN_OPS, expr)
        _walk_collect(node.left, expr, refs)
        _walk_collect(node.right, expr, refs)
    elif isinstance(node, ast.UnaryOp):
        _check_op(node.op, _UNARY_OPS, expr)
        _walk_collect(node.operand, expr, refs)
    elif isinstance(node, ast.Name):
        if node.id not in CONSTANTS:
            refs.add(node.id)
    elif isinstance(node, ast.Attribute):
        refs.add(_attribute_ref(node, expr))
    elif isinstance(node, ast.Call):
        fname = _call_func_name(node, expr)
        spec = FUNCTIONS.get(fname)
        if spec is None:
            raise EvalError(
                f"式 {expr!r}: 未知の関数 {fname}() です。"
                f"使用可能: {', '.join(sorted(FUNCTIONS))}"
            )
        if len(node.args) != spec.arity:
            raise EvalError(
                f"式 {expr!r}: {fname}() の引数は {spec.arity} 個です"
                f"({len(node.args)} 個指定されました)"
            )
        for a in node.args:
            _walk_collect(a, expr, refs)
    else:
        raise EvalError(
            f"式 {expr!r}: {type(node).__name__} 構文は使用できません。"
            "使えるのは数値・変数・table.col・四則演算 (+ - * / ** % //)・"
            "登録済み関数の呼び出しのみです"
        )


def evaluate(expr: str, namespace: dict) -> float | None:
    """namespace のもとで式を評価する。

    namespace の値は float / None / list(テーブル列ベクトル)。
    None が混じる算術は結果 None(未確定の伝播)。
    """
    tree = parse_expr(expr)
    return _eval_node(tree.body, expr, namespace)


def _eval_node(node: ast.AST, expr: str, ns: dict):
    if isinstance(node, ast.Constant):
        _check_constant(node, expr)
        return float(node.value)

    if isinstance(node, ast.BinOp):
        op = _check_op(node.op, _BIN_OPS, expr)
        left = _eval_node(node.left, expr, ns)
        right = _eval_node(node.right, expr, ns)
        if left is None or right is None:
            return None
        try:
            return float(op(left, right))
        except ZeroDivisionError:
            raise EvalError(f"式 {expr!r}: ゼロ除算が発生しました") from None
        except (ValueError, OverflowError) as e:
            raise EvalError(f"式 {expr!r} を計算できません: {e}") from e

    if isinstance(node, ast.UnaryOp):
        op = _check_op(node.op, _UNARY_OPS, expr)
        v = _eval_node(node.operand, expr, ns)
        return None if v is None else float(op(v))

    if isinstance(node, ast.Name):
        if node.id in ns:
            return ns[node.id]
        if node.id in CONSTANTS:
            return CONSTANTS[node.id]
        raise EvalError(f"式 {expr!r}: 変数 {node.id!r} は定義されていません")

    if isinstance(node, ast.Attribute):
        ref = _attribute_ref(node, expr)
        if ref not in ns:
            raise EvalError(f"式 {expr!r}: テーブル列 {ref!r} は定義されていません")
        return ns[ref]

    if isinstance(node, ast.Call):
        fname = _call_func_name(node, expr)
        spec = FUNCTIONS.get(fname)
        if spec is None:
            raise EvalError(f"式 {expr!r}: 未知の関数 {fname}() です")
        if len(node.args) != spec.arity:
            raise EvalError(
                f"式 {expr!r}: {fname}() の引数は {spec.arity} 個です"
            )
        args = [_eval_node(a, expr, ns) for a in node.args]
        return spec.fn(*args)

    raise EvalError(
        f"式 {expr!r}: {type(node).__name__} 構文は使用できません"
    )


def _check_constant(node: ast.Constant, expr: str) -> None:
    if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
        raise EvalError(
            f"式 {expr!r}: リテラル {node.value!r} は使用できません(数値のみ)"
        )


def _check_op(op: ast.AST, table: dict, expr: str):
    fn = table.get(type(op))
    if fn is None:
        raise EvalError(f"式 {expr!r}: 演算子 {type(op).__name__} は使用できません")
    return fn


def _attribute_ref(node: ast.Attribute, expr: str) -> str:
    """`table.col` 形の属性アクセスのみ許可し、参照キーを返す。"""
    if not isinstance(node.value, ast.Name):
        raise EvalError(
            f"式 {expr!r}: 属性アクセスは「テーブル名.列名」の形のみ使用できます"
        )
    return f"{node.value.id}.{node.attr}"


def _call_func_name(node: ast.Call, expr: str) -> str:
    if not isinstance(node.func, ast.Name):
        raise EvalError(f"式 {expr!r}: 関数呼び出しは関数名のみ指定できます")
    if node.keywords:
        raise EvalError(f"式 {expr!r}: キーワード引数は使用できません")
    return node.func.id
