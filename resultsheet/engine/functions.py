"""計算式で使える関数レジストリ。

- 集計関数は None(未入力)を含むベクトルを受けたら None を返す。
  「未入力を黙って除外して平均する」事故をレポート用途では許さない。
- 戻り値は必ず Python float に正規化する(numpy スカラーを外に漏らさない)。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np

from resultsheet.errors import EvalError

Vector = list  # None を含みうる数値リスト


@dataclass(frozen=True)
class FuncSpec:
    fn: Callable
    arity: int
    description: str


def _scalar(fn: Callable[[float], float], name: str) -> Callable:
    def wrapped(x):
        if x is None:
            return None
        if isinstance(x, list):
            return [None if v is None else wrapped(v) for v in x]
        try:
            return float(fn(float(x)))
        except (ValueError, OverflowError) as e:
            raise EvalError(f"{name}({x}) を計算できません: {e}") from e

    return wrapped


def _vector(fn: Callable[[np.ndarray], float], name: str) -> Callable:
    def wrapped(v):
        arr = _require_vector(v, name)
        if arr is None:
            return None
        return float(fn(arr))

    return wrapped


def _require_vector(v, name: str) -> np.ndarray | None:
    """ベクトル引数の検証。None を含む・空なら None(=未確定)を返す。"""
    if v is None:
        return None
    if not isinstance(v, list):
        raise EvalError(f"{name}() の引数はテーブルの列(例: table.col)を指定してください")
    if len(v) == 0 or any(x is None for x in v):
        return None
    return np.asarray(v, dtype=float)


def _fit(x, y, name: str) -> tuple[float, float] | None:
    """最小二乗直線フィット y = a*x + b。(a, b) を返す。"""
    ax = _require_vector(x, name)
    ay = _require_vector(y, name)
    if ax is None or ay is None:
        return None
    if len(ax) != len(ay):
        raise EvalError(f"{name}(): x と y の要素数が一致しません ({len(ax)} vs {len(ay)})")
    if len(ax) < 2:
        raise EvalError(f"{name}(): フィットには 2 点以上必要です")
    xm, ym = ax.mean(), ay.mean()
    sxx = float(((ax - xm) ** 2).sum())
    if sxx == 0.0:
        raise EvalError(f"{name}(): x がすべて同じ値なのでフィットできません")
    a = float(((ax - xm) * (ay - ym)).sum()) / sxx
    b = float(ym - a * xm)
    return a, b


def _slope(x, y):
    r = _fit(x, y, "slope")
    return None if r is None else r[0]


def _intercept(x, y):
    r = _fit(x, y, "intercept")
    return None if r is None else r[1]


def _rvalue(x, y):
    ax = _require_vector(x, "rvalue")
    ay = _require_vector(y, "rvalue")
    if ax is None or ay is None:
        return None
    if len(ax) != len(ay):
        raise EvalError(f"rvalue(): x と y の要素数が一致しません ({len(ax)} vs {len(ay)})")
    if len(ax) < 2:
        raise EvalError("rvalue(): 2 点以上必要です")
    c = np.corrcoef(ax, ay)
    return float(c[0, 1])


def _fit_stats(x, y, name: str) -> tuple[float, float] | None:
    """最小二乗フィット y = a x + b の傾き・切片の標準誤差 (SE(a), SE(b)) を返す。

    残差分散 s^2 = Σ(y_i - (a x_i + b))^2 / (n - 2) を用いた標準的な推定量:
        SE(a) = sqrt(s^2 / Sxx)
        SE(b) = sqrt(s^2 * (1/n + xmean^2 / Sxx))
    scipy.stats.linregress の stderr と一致する。誤差の推定には n >= 3 が必要。
    """
    ax = _require_vector(x, name)
    ay = _require_vector(y, name)
    if ax is None or ay is None:
        return None
    if len(ax) != len(ay):
        raise EvalError(f"{name}(): x と y の要素数が一致しません ({len(ax)} vs {len(ay)})")
    n = len(ax)
    if n < 3:
        raise EvalError(f"{name}(): 誤差の推定には 3 点以上必要です")
    xm = ax.mean()
    sxx = float(((ax - xm) ** 2).sum())
    if sxx == 0.0:
        raise EvalError(f"{name}(): x がすべて同じ値なので誤差を推定できません")
    a = float(((ax - xm) * (ay - ay.mean())).sum()) / sxx
    b = float(ay.mean() - a * xm)
    resid = ay - (a * ax + b)
    s_sq = float((resid ** 2).sum()) / (n - 2)
    se_a = math.sqrt(s_sq / sxx)
    se_b = math.sqrt(s_sq * (1.0 / n + xm * xm / sxx))
    return se_a, se_b


def _slope_err(x, y):
    r = _fit_stats(x, y, "slope_err")
    return None if r is None else r[0]


def _intercept_err(x, y):
    r = _fit_stats(x, y, "intercept_err")
    return None if r is None else r[1]


def _sem(a: np.ndarray) -> float:
    """平均値の標準誤差 (standard error of the mean) = 標本標準偏差 / sqrt(n)。"""
    if len(a) < 2:
        raise EvalError("sem(): 平均値の標準誤差には 2 点以上必要です")
    return float(np.std(a, ddof=1) / math.sqrt(len(a)))


def _std_sample(a: np.ndarray) -> float:
    if len(a) < 2:
        raise EvalError("std(): 標本標準偏差 (ddof=1) には 2 点以上必要です")
    return float(np.std(a, ddof=1))


def _round2(x, n):
    if x is None or n is None:
        return None
    return float(round(float(x), int(n)))


FUNCTIONS: dict[str, FuncSpec] = {
    # 要素ごと / スカラー
    "sqrt": FuncSpec(_scalar(math.sqrt, "sqrt"), 1, "平方根"),
    "abs": FuncSpec(_scalar(abs, "abs"), 1, "絶対値"),
    "exp": FuncSpec(_scalar(math.exp, "exp"), 1, "指数関数 e^x"),
    "log": FuncSpec(_scalar(math.log, "log"), 1, "自然対数"),
    "log10": FuncSpec(_scalar(math.log10, "log10"), 1, "常用対数"),
    "sin": FuncSpec(_scalar(math.sin, "sin"), 1, "正弦 (rad)"),
    "cos": FuncSpec(_scalar(math.cos, "cos"), 1, "余弦 (rad)"),
    "tan": FuncSpec(_scalar(math.tan, "tan"), 1, "正接 (rad)"),
    "atan": FuncSpec(_scalar(math.atan, "atan"), 1, "逆正接 (rad)"),
    "floor": FuncSpec(_scalar(math.floor, "floor"), 1, "切り捨て"),
    "ceil": FuncSpec(_scalar(math.ceil, "ceil"), 1, "切り上げ"),
    "round2": FuncSpec(_round2, 2, "小数第 n 位への丸め round2(x, n)"),
    # 集計(None を含む列は結果 None)
    "mean": FuncSpec(_vector(np.mean, "mean"), 1, "平均"),
    "std": FuncSpec(_vector(_std_sample, "std"), 1, "標本標準偏差 (ddof=1)"),
    "pstd": FuncSpec(_vector(lambda a: np.std(a, ddof=0), "pstd"), 1, "母標準偏差 (ddof=0)"),
    "sem": FuncSpec(_vector(_sem, "sem"), 1, "平均値の標準誤差 std/sqrt(n)"),
    "sum": FuncSpec(_vector(np.sum, "sum"), 1, "総和"),
    "min": FuncSpec(_vector(np.min, "min"), 1, "最小値"),
    "max": FuncSpec(_vector(np.max, "max"), 1, "最大値"),
    "count": FuncSpec(_vector(len, "count"), 1, "要素数"),
    # 最小二乗直線フィット y = a x + b(値と標準誤差)
    "slope": FuncSpec(_slope, 2, "最小二乗フィットの傾き slope(x, y)"),
    "intercept": FuncSpec(_intercept, 2, "最小二乗フィットの切片 intercept(x, y)"),
    "rvalue": FuncSpec(_rvalue, 2, "相関係数 rvalue(x, y)"),
    "slope_err": FuncSpec(_slope_err, 2, "フィット傾きの標準誤差 slope_err(x, y)"),
    "intercept_err": FuncSpec(_intercept_err, 2, "フィット切片の標準誤差 intercept_err(x, y)"),
}

CONSTANTS: dict[str, float] = {
    "pi": math.pi,
    "e": math.e,
}
