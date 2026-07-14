"""妥当範囲(range)チェックのテスト。"""

import pytest

from resultsheet.engine.compute import compute_all, range_warning
from resultsheet.errors import DefinitionError
from resultsheet.schema import load_definition


class TestRangeWarningHelper:
    def test_within_range(self):
        assert range_warning(5.0, {"min": 0, "max": 10}, "x", None) is None

    def test_below_min(self):
        msg = range_warning(-1.0, {"min": 0, "max": 10}, "質量", "g")
        assert msg is not None and "下限" in msg and "質量" in msg

    def test_above_max(self):
        msg = range_warning(99.0, {"min": 0, "max": 10}, "x", None)
        assert "上限" in msg

    def test_only_min(self):
        assert range_warning(-1.0, {"min": 0, "max": None}, "x", None) is not None
        assert range_warning(1e9, {"min": 0, "max": None}, "x", None) is None

    def test_only_max(self):
        assert range_warning(1e9, {"min": None, "max": 10}, "x", None) is not None

    def test_none_value(self):
        assert range_warning(None, {"min": 0, "max": 10}, "x", None) is None

    def test_no_spec(self):
        assert range_warning(5.0, None, "x", None) is None

    def test_custom_message_appended(self):
        msg = range_warning(99.0, {"min": 0, "max": 10, "message": "確認して"}, "x", None)
        assert "確認して" in msg


class TestSchemaRange:
    def test_range_parsed(self):
        d = load_definition(
            "meta: {id: t, title: T}\n"
            "inputs:\n  - {name: x, label: X, range: {min: 0, max: 10}}\n"
        )
        assert d.inputs[0].range == {"min": 0.0, "max": 10.0, "message": None}

    @pytest.mark.parametrize(
        "range_yaml, match",
        [
            ("{}", "min か max"),
            ("{min: 5, max: 1}", "min <= max"),
            ("{min: abc}", "数値"),
            ("{min: 0, bad: 1}", "未知のキー"),
        ],
    )
    def test_invalid_range_rejected(self, range_yaml, match):
        with pytest.raises(DefinitionError, match=match):
            load_definition(
                "meta: {id: t, title: T}\n"
                f"inputs:\n  - {{name: x, label: X, range: {range_yaml}}}\n"
            )

    def test_templates_have_ranges(self, density_def, free_fall_def):
        assert density_def.inputs[0].range is not None
        # rho(導出量)にも範囲がある
        rho = next(dv for dv in density_def.derived if dv.name == "rho")
        assert rho.range == {"min": 0.5, "max": 25.0, "message": "測定・計算ミスの可能性があります"}


class TestComputeRangeWarnings:
    def test_input_out_of_range(self, density_def):
        # V を巨大にすると range を外れる
        result = compute_all(density_def, {"m": 12.0, "V": 9999.0}, {})
        assert "V" in result.range_warnings["inputs"]

    def test_input_within_range_no_warning(self, density_def):
        result = compute_all(density_def, {"m": 12.0, "V": 4.5}, {})
        assert result.range_warnings["inputs"] == {}

    def test_derived_out_of_range(self, density_def):
        # m/V が極端に小さく rho の下限 0.5 を割る
        result = compute_all(density_def, {"m": 0.1, "V": 100.0}, {})
        assert "rho" in result.range_warnings["derived"]
        assert "range_warning" in result.computed["rho"]

    def test_derived_within_range(self, density_def):
        result = compute_all(density_def, {"m": 35.0, "V": 4.5}, {})  # ~7.8
        assert result.range_warnings["derived"] == {}
        assert "range_warning" not in result.computed["rho"]

    def test_table_cell_out_of_range(self, free_fall_def, free_fall_data):
        # t の1セルを妥当範囲(max 10)外に
        free_fall_data["drops"]["rows"][0][1] = 99.0
        result = compute_all(free_fall_def, {}, free_fall_data)
        assert result.range_warnings["columns"]["drops"]["t"][0] is not None

    def test_normal_data_no_warnings(self, free_fall_def, free_fall_data):
        result = compute_all(free_fall_def, {}, free_fall_data)
        assert result.range_warnings["inputs"] == {}
        assert result.range_warnings["columns"] == {}
        assert result.range_warnings["derived"] == {}  # g≈9.8 は範囲内
