import math

import pytest

from resultsheet.engine.safe_eval import evaluate, extract_references
from resultsheet.errors import EvalError


class TestEvaluate:
    def test_arithmetic(self):
        assert evaluate("2 + 3 * 4", {}) == 14.0
        assert evaluate("(1 + 2) ** 2", {}) == 9.0
        assert evaluate("7 % 3", {}) == 1.0
        assert evaluate("7 // 2", {}) == 3.0
        assert evaluate("-x", {"x": 2.0}) == -2.0

    def test_variables(self):
        assert evaluate("m / V", {"m": 12.0, "V": 4.0}) == 3.0

    def test_full_precision(self):
        # 丸めなしのフル精度計算であること
        assert evaluate("m / V", {"m": 12.345, "V": 4.567}) == 12.345 / 4.567

    def test_builtin_constants(self):
        assert evaluate("pi", {}) == math.pi
        assert evaluate("e", {}) == math.e

    def test_namespace_shadows_constants(self):
        # ユーザー定義は組み込み定数より優先(schema 側で衝突は禁止しているが防御)
        assert evaluate("pi", {"pi": 3.0}) == 3.0

    def test_functions(self):
        assert evaluate("sqrt(16)", {}) == 4.0
        assert evaluate("mean(t.v)", {"t.v": [1.0, 2.0, 3.0]}) == 2.0

    def test_table_column_reference(self):
        ns = {"drops.t": [1.0, 2.0]}
        assert evaluate("sum(drops.t)", ns) == 3.0

    def test_none_propagates(self):
        assert evaluate("m / V", {"m": None, "V": 4.0}) is None
        assert evaluate("-x", {"x": None}) is None
        assert evaluate("mean(t.v)", {"t.v": [1.0, None]}) is None

    def test_zero_division(self):
        with pytest.raises(EvalError, match="ゼロ除算"):
            evaluate("1 / x", {"x": 0.0})

    def test_undefined_variable(self):
        with pytest.raises(EvalError, match="定義されていません"):
            evaluate("q + 1", {})


class TestRejection:
    @pytest.mark.parametrize(
        "expr",
        [
            "__import__('os')",       # 未知の関数
            "().__class__",           # タプル → 禁止構文
            "x.__class__",            # table.col 以外の属性は ns に無い
            "x[0]",                   # Subscript
            "lambda: 0",              # Lambda
            "'abc'",                  # 文字列リテラル
            "x if x else 0",          # 条件式
            "x == 1",                 # 比較
            "[1, 2]",                 # リストリテラル
            "{1: 2}",                 # 辞書
            "x and 1",                # ブール演算
            "True",                   # 真偽値リテラル
            "mean(v, axis=0)",        # キーワード引数
            "unknown_fn(1)",          # 未登録関数
            "sqrt(1, 2)",             # アリティ違反
            "a.b.c",                  # ネストした属性
        ],
    )
    def test_rejected(self, expr):
        with pytest.raises(EvalError):
            evaluate(expr, {"x": 1.0, "v": [1.0], "a.b": [1.0]})

    def test_syntax_error(self):
        with pytest.raises(EvalError, match="解釈できません"):
            evaluate("1 +", {})


class TestExtractReferences:
    def test_names_and_columns(self):
        assert extract_references("2 * a + slope(drops.t2, drops.h)") == {
            "a",
            "drops.t2",
            "drops.h",
        }

    def test_constants_and_functions_excluded(self):
        assert extract_references("pi * sqrt(x)") == {"x"}

    def test_rejects_forbidden_syntax(self):
        with pytest.raises(EvalError):
            extract_references("__import__('os').system('ls')")
