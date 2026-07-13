import pytest

from resultsheet.engine.rounding import (
    NULL_DISPLAY,
    format_decimals,
    format_display,
    format_sigfigs,
)


class TestSigfigs:
    @pytest.mark.parametrize(
        "x, n, expected",
        [
            (1.2, 3, "1.20"),          # 末尾ゼロ保持
            (9.996, 3, "10.0"),        # 桁上がり
            (0.0009995, 3, "0.00100"),  # 桁上がりで 1e-4 以上になり通常表記
            (2.7032894736842106, 3, "2.70"),
            (9.80665, 4, "9.807"),
            (0.35, 2, "0.35"),
            (0.345, 2, "0.35"),        # ROUND_HALF_UP (十進で処理)
            (-1.2345, 3, "-1.23"),
            (123456.0, 3, "1.23e+05"),  # 大きい値は指数表記
            (0.000012345, 3, "1.23e-05"),  # 小さい値は指数表記
            (0.0001, 2, "0.00010"),     # ちょうど 1e-4 は通常表記(< で切替)
            (99999.4, 4, "1.000e+05"),  # 丸めで 1e5 に到達し指数表記
            (100.0, 4, "100.0"),
            (7.0, 3, "7.00"),
            (0.0, 3, "0.00"),
            (1500.0, 2, "1500"),
        ],
    )
    def test_values(self, x, n, expected):
        assert format_sigfigs(x, n) == expected

    def test_none(self):
        assert format_sigfigs(None, 3) == NULL_DISPLAY

    def test_nan(self):
        assert format_sigfigs(float("nan"), 3) == NULL_DISPLAY

    def test_invalid_n(self):
        with pytest.raises(ValueError):
            format_sigfigs(1.0, 0)


class TestDecimals:
    @pytest.mark.parametrize(
        "x, n, expected",
        [
            (1.005, 2, "1.01"),   # 十進の四捨五入 (float の 1.005 表現に依らない)
            (9.7912345, 2, "9.79"),
            (1.0, 3, "1.000"),
            (-0.5, 0, "-1"),      # ROUND_HALF_UP
            (2.5, 0, "3"),
            (0.0, 2, "0.00"),
        ],
    )
    def test_values(self, x, n, expected):
        assert format_decimals(x, n) == expected

    def test_none(self):
        assert format_decimals(None, 2) == NULL_DISPLAY


class TestFormatDisplay:
    def test_default_is_sigfigs4(self):
        assert format_display(9.80665, None) == "9.807"

    def test_sigfigs(self):
        assert format_display(1.2, {"sigfigs": 3}) == "1.20"

    def test_decimals(self):
        assert format_display(1.2, {"decimals": 3}) == "1.200"


def test_display_reparse_differs_from_full_precision():
    """回帰検知: 丸め表示値を再パースして再計算すると
    フル精度計算値と一致しない、という前提が実際に成り立つケース。
    (このシステムが display を namespace に戻さない理由の実証)"""
    m, v = 12.345, 4.567
    rho_full = m / v  # 2.7030873220056933...
    rho_display = format_sigfigs(rho_full, 3)  # "2.70"
    ratio_from_display = float(rho_display) / 7.874
    ratio_full = rho_full / 7.874
    assert format_sigfigs(ratio_full, 6) != format_sigfigs(ratio_from_display, 6)
