import numpy as np
import pytest

from resultsheet.engine.functions import FUNCTIONS
from resultsheet.errors import EvalError


def call(name, *args):
    return FUNCTIONS[name].fn(*args)


class TestAggregates:
    def test_mean(self):
        assert call("mean", [1.0, 2.0, 3.0]) == 2.0

    def test_std_is_sample_std(self):
        data = [1.0, 2.0, 3.0, 4.0]
        assert call("std", data) == pytest.approx(np.std(data, ddof=1))
        assert call("pstd", data) == pytest.approx(np.std(data, ddof=0))

    def test_std_requires_two_points(self):
        with pytest.raises(EvalError, match="2 点以上"):
            call("std", [1.0])

    def test_count(self):
        assert call("count", [1.0, 2.0]) == 2.0

    def test_none_in_vector_returns_none(self):
        # 未入力を黙って除外しない
        assert call("mean", [1.0, None, 3.0]) is None
        assert call("sum", []) is None

    def test_scalar_arg_rejected(self):
        with pytest.raises(EvalError, match="列"):
            call("mean", 1.0)

    def test_returns_python_float(self):
        assert type(call("mean", [1.0, 2.0])) is float


class TestFit:
    # y = 2x + 1 を厳密に通る 3 点
    X = [0.0, 1.0, 2.0]
    Y = [1.0, 3.0, 5.0]

    def test_slope_intercept_exact(self):
        assert call("slope", self.X, self.Y) == pytest.approx(2.0)
        assert call("intercept", self.X, self.Y) == pytest.approx(1.0)
        assert call("rvalue", self.X, self.Y) == pytest.approx(1.0)

    def test_matches_polyfit(self):
        x = [0.1, 0.5, 1.2, 2.3, 3.1]
        y = [0.35, 1.1, 2.55, 4.9, 6.4]
        a, b = np.polyfit(x, y, 1)
        assert call("slope", x, y) == pytest.approx(a)
        assert call("intercept", x, y) == pytest.approx(b)

    def test_length_mismatch(self):
        with pytest.raises(EvalError, match="一致しません"):
            call("slope", [1.0, 2.0], [1.0])

    def test_needs_two_points(self):
        with pytest.raises(EvalError, match="2 点以上"):
            call("slope", [1.0], [1.0])

    def test_constant_x(self):
        with pytest.raises(EvalError, match="フィットできません"):
            call("slope", [1.0, 1.0], [1.0, 2.0])

    def test_none_propagates(self):
        assert call("slope", [1.0, None], [1.0, 2.0]) is None


class TestUncertainty:
    # y = 2x + 1 に近いがぴったりではないデータ(残差あり)
    X = [0.0, 1.0, 2.0, 3.0, 4.0]
    Y = [1.1, 2.9, 5.2, 6.8, 9.1]

    def _expected_fit_errs(self, x, y):
        x = np.asarray(x, float); y = np.asarray(y, float)
        n = len(x)
        a, b = np.polyfit(x, y, 1)
        resid = y - (a * x + b)
        s_sq = (resid**2).sum() / (n - 2)
        sxx = ((x - x.mean())**2).sum()
        se_a = np.sqrt(s_sq / sxx)
        se_b = np.sqrt(s_sq * (1 / n + x.mean()**2 / sxx))
        return float(se_a), float(se_b)

    def test_slope_err_matches_formula(self):
        se_a, se_b = self._expected_fit_errs(self.X, self.Y)
        assert call("slope_err", self.X, self.Y) == pytest.approx(se_a)
        assert call("intercept_err", self.X, self.Y) == pytest.approx(se_b)

    def test_perfect_fit_has_zero_error(self):
        x = [0.0, 1.0, 2.0, 3.0]
        y = [1.0, 3.0, 5.0, 7.0]  # y=2x+1 ぴったり
        assert call("slope_err", x, y) == pytest.approx(0.0, abs=1e-12)
        assert call("intercept_err", x, y) == pytest.approx(0.0, abs=1e-12)

    def test_needs_three_points(self):
        with pytest.raises(EvalError, match="3 点以上"):
            call("slope_err", [1.0, 2.0], [1.0, 2.0])

    def test_none_propagates(self):
        assert call("slope_err", [1.0, 2.0, None], [1.0, 2.0, 3.0]) is None

    def test_sem(self):
        data = [1.0, 2.0, 3.0, 4.0]
        assert call("sem", data) == pytest.approx(np.std(data, ddof=1) / np.sqrt(4))

    def test_sem_none(self):
        assert call("sem", [1.0, None]) is None


class TestScalar:
    def test_sqrt(self):
        assert call("sqrt", 16.0) == 4.0

    def test_sqrt_negative(self):
        with pytest.raises(EvalError):
            call("sqrt", -1.0)

    def test_elementwise_on_vector(self):
        assert call("sqrt", [4.0, None, 9.0]) == [2.0, None, 3.0]

    def test_round2(self):
        assert call("round2", 1.2345, 2) == 1.23
