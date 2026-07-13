import numpy as np
import pytest

from resultsheet.engine.compute import compute_all, fit_line


class TestDensity:
    def test_full_precision_end_to_end(self, density_def):
        result = compute_all(density_def, {"m": 12.345, "V": 4.567}, {})
        rho = result.computed["rho"]
        assert rho["value"] == 12.345 / 4.567          # フル精度
        assert rho["display"] == "2.70"                # sigfigs 3
        assert rho["unit"] == "g/cm^3"
        assert rho["expr"] == "m / V"
        # rho_ratio はフル精度の rho から計算される(表示値 2.70 からではない)
        ratio = result.computed["rho_ratio"]
        assert ratio["value"] == (12.345 / 4.567) / 7.874
        assert ratio["display"] == "0.343"
        assert result.errors == {}

    def test_partial_input_propagates_none(self, density_def):
        result = compute_all(density_def, {"m": 12.345}, {})
        assert result.computed["rho"]["value"] is None
        assert result.computed["rho"]["display"] == "—"
        assert result.computed["rho_ratio"]["value"] is None
        assert result.errors == {}  # 未入力はエラーではない

    def test_zero_division_isolated(self, density_def):
        result = compute_all(density_def, {"m": 12.345, "V": 0.0}, {})
        assert result.computed["rho"]["value"] is None
        assert "ゼロ除算" in result.computed["rho"]["error"]
        assert "rho" in result.errors
        # 依存先は None 伝播で生き残る(クラッシュしない)
        assert result.computed["rho_ratio"]["value"] is None


class TestFreeFall:
    def test_end_to_end_matches_numpy(self, free_fall_def, free_fall_data):
        result = compute_all(free_fall_def, {}, free_fall_data)
        rows = free_fall_data["drops"]["rows"]
        h = np.array([r[0] for r in rows])
        t = np.array([r[1] for r in rows])
        t2 = t**2

        assert result.computed_columns["drops"]["t2"] == list(t2)
        assert result.computed["t_mean"]["value"] == pytest.approx(t.mean(), abs=0)
        assert result.computed["t_std"]["value"] == pytest.approx(
            np.std(t, ddof=1), rel=1e-15
        )
        a, b = np.polyfit(t2, h, 1)
        assert result.computed["a_slope"]["value"] == pytest.approx(a, rel=1e-12)
        assert result.computed["b_intercept"]["value"] == pytest.approx(b, rel=1e-9)
        assert result.computed["g_measured"]["value"] == pytest.approx(2 * a, rel=1e-12)
        # g は 9.8 付近になるはず(データが h=4.9t^2 ベース)
        assert 9.0 < result.computed["g_measured"]["value"] < 10.5

    def test_incomplete_row_propagates(self, free_fall_def, free_fall_data):
        free_fall_data["drops"]["rows"][2][1] = None  # t の1セルを未入力に
        result = compute_all(free_fall_def, {}, free_fall_data)
        assert result.computed_columns["drops"]["t2"][2] is None
        # None を含む列の集計・フィットはすべて None
        for name in ("t_mean", "t_std", "a_slope", "g_measured"):
            assert result.computed[name]["value"] is None, name
        assert result.computed["t_mean"]["display"] == "—"

    def test_empty_table(self, free_fall_def):
        result = compute_all(free_fall_def, {}, {})
        assert result.computed_columns["drops"]["t2"] == []
        assert result.computed["g_measured"]["value"] is None

    def test_column_order_independent(self, free_fall_def, free_fall_data):
        # 列順を入れ替えて送っても columns で対応づけられる
        swapped = {
            "drops": {
                "columns": ["t", "h"],
                "rows": [[r[1], r[0]] for r in free_fall_data["drops"]["rows"]],
            }
        }
        r1 = compute_all(free_fall_def, {}, free_fall_data)
        r2 = compute_all(free_fall_def, {}, swapped)
        assert r1.computed["g_measured"]["value"] == r2.computed["g_measured"]["value"]

    def test_display_strings_for_columns(self, free_fall_def, free_fall_data):
        result = compute_all(free_fall_def, {}, free_fall_data)
        disp = result.computed_columns_display["drops"]["t2"]
        assert disp[0] == "0.1024"  # 0.320^2 = 0.1024, sigfigs 4


class TestConstants:
    def test_constants_in_namespace(self):
        from resultsheet.schema import load_definition

        d = load_definition(
            "meta: {id: t, title: T}\n"
            "constants:\n"
            "  k: {value: 2.5}\n"
            "derived:\n"
            "  - {name: y, expr: 'k * 2'}\n"
        )
        assert compute_all(d, {}, {}).computed["y"]["value"] == 5.0

    def test_pi(self):
        from resultsheet.schema import load_definition

        d = load_definition(
            "meta: {id: t, title: T}\n"
            "inputs:\n  - {name: r, label: R}\n"
            "derived:\n  - {name: area, expr: 'pi * r ** 2'}\n"
        )
        import math

        assert compute_all(d, {"r": 2.0}, {}).computed["area"]["value"] == math.pi * 4


def test_fit_line_adhoc():
    r = fit_line([0.0, 1.0, 2.0], [1.0, 3.0, 5.0])
    assert r["slope"] == pytest.approx(2.0)
    assert r["intercept"] == pytest.approx(1.0)
    assert r["rvalue"] == pytest.approx(1.0)


def test_fit_line_with_none():
    r = fit_line([0.0, None], [1.0, 2.0])
    assert r["slope"] is None
