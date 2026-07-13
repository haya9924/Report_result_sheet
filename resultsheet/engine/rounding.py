"""表示用の丸め文字列生成。

不変条件: この module が返すのは常に「文字列」であり、計算の namespace には
決して戻さない。丸めた値で再計算するバグを構造的に防ぐための境界。

丸めモードは四捨五入 (ROUND_HALF_UP)。float の二進表現由来の境界問題を避ける
ため、Decimal(repr(x)) 経由で処理する(例: 0.35 は repr が "0.35" なので
十進の 0.35 として四捨五入される)。
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

# 未入力・計算不能値の表示
NULL_DISPLAY = "—"

# この範囲を外れたら指数表記に切り替える
_EXP_UPPER = Decimal("1e5")
_EXP_LOWER = Decimal("1e-4")

DEFAULT_SIGFIGS = 4


def format_sigfigs(x: float | None, n: int) -> str:
    """有効数字 n 桁の表示文字列。末尾ゼロを保持する。

    例: format_sigfigs(1.2, 3) == "1.20"
        format_sigfigs(9.996, 3) == "10.0"   (桁上がり)
        format_sigfigs(123456.0, 3) == "1.23e+05"
    """
    if x is None:
        return NULL_DISPLAY
    if n < 1:
        raise ValueError("sigfigs は 1 以上を指定してください")
    d = Decimal(repr(float(x)))
    if d.is_nan():
        return NULL_DISPLAY
    if d == 0:
        # 0 は "0.000" のように n 桁で表示
        return str(Decimal(0).quantize(Decimal(1).scaleb(1 - n)))

    # 丸め先の指数: 最上位桁の指数 - (n - 1)
    exponent = d.adjusted() - (n - 1)
    q = d.quantize(Decimal(1).scaleb(exponent), rounding=ROUND_HALF_UP)
    # 丸めで桁上がりした場合 (9.996 -> 10.00) は adjusted が変わるので再量子化
    if q.adjusted() != d.adjusted():
        exponent = q.adjusted() - (n - 1)
        q = q.quantize(Decimal(1).scaleb(exponent), rounding=ROUND_HALF_UP)

    abs_q = abs(q)
    if abs_q >= _EXP_UPPER or abs_q < _EXP_LOWER:
        return _to_exp_string(q, n)
    return _to_plain_string(q)


def format_decimals(x: float | None, n: int) -> str:
    """小数点以下 n 桁固定の表示文字列。"""
    if x is None:
        return NULL_DISPLAY
    if n < 0:
        raise ValueError("decimals は 0 以上を指定してください")
    d = Decimal(repr(float(x)))
    if d.is_nan():
        return NULL_DISPLAY
    q = d.quantize(Decimal(1).scaleb(-n), rounding=ROUND_HALF_UP)
    return _to_plain_string(q)


def format_display(x: float | None, rounding: dict | None) -> str:
    """display 指定 ({"sigfigs": N} または {"decimals": N}) に従い表示文字列を返す。

    display 未指定時は有効数字 DEFAULT_SIGFIGS 桁。
    """
    if rounding is None:
        return format_sigfigs(x, DEFAULT_SIGFIGS)
    if "sigfigs" in rounding:
        return format_sigfigs(x, rounding["sigfigs"])
    if "decimals" in rounding:
        return format_decimals(x, rounding["decimals"])
    return format_sigfigs(x, DEFAULT_SIGFIGS)


def _to_plain_string(q: Decimal) -> str:
    """指数表記を使わない文字列化(末尾ゼロは保持)。"""
    sign, digits, exp = q.as_tuple()
    s = "".join(str(d) for d in digits)
    if exp >= 0:
        s = s + "0" * exp
    else:
        if len(s) <= -exp:
            s = "0" * (-exp - len(s) + 1) + s
        s = s[:exp] + "." + s[exp:]
    return ("-" if sign else "") + s


def _to_exp_string(q: Decimal, n: int) -> str:
    """有効数字 n 桁の指数表記 "1.23e+05" 形式。"""
    sign, digits, _ = q.as_tuple()
    mantissa_digits = "".join(str(d) for d in digits)[:n].ljust(n, "0")
    if n == 1:
        mantissa = mantissa_digits
    else:
        mantissa = mantissa_digits[0] + "." + mantissa_digits[1:]
    e = q.adjusted()
    return f"{'-' if sign else ''}{mantissa}e{e:+03d}"
