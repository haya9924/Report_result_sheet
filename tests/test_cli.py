import json

import pytest

from resultsheet.cli import main
from resultsheet.store import ReportStore, get_template


@pytest.fixture
def reports_dir(tmp_path):
    d = tmp_path / "reports"
    store = ReportStore(d)
    store.create("dens", get_template("density"))
    store.save_results("dens", {"m": 12.345, "V": 4.567}, {})
    return d


def run(args, reports_dir, capsys):
    code = main(["--reports-dir", str(reports_dir), *args])
    out, err = capsys.readouterr()
    return code, out, err


class TestShow:
    def test_json_parseable_and_full_precision(self, reports_dir, capsys):
        code, out, _ = run(["show", "dens", "--format", "json"], reports_dir, capsys)
        assert code == 0
        payload = json.loads(out)
        assert payload["derived"]["rho"]["value"] == 12.345 / 4.567
        assert payload["derived"]["rho"]["display"] == "2.70"
        assert payload["derived"]["rho"]["expr"] == "m / V"
        assert payload["inputs"]["m"]["value"] == 12.345

    def test_markdown(self, reports_dir, capsys):
        code, out, _ = run(["show", "dens", "--format", "md"], reports_dir, capsys)
        assert code == 0
        assert "| rho | 2.70 |" in out
        assert "`m / V`" in out

    def test_missing_report(self, reports_dir, capsys):
        code, _, err = run(["show", "nope"], reports_dir, capsys)
        assert code == 1
        assert "存在しません" in err


class TestGet:
    def test_plain(self, reports_dir, capsys):
        code, out, _ = run(["get", "dens", "rho"], reports_dir, capsys)
        assert code == 0
        assert f"value: {12.345 / 4.567!r}" in out
        assert "display: 2.70" in out
        assert "expr: m / V" in out
        assert "unit: g/cm^3" in out

    def test_json(self, reports_dir, capsys):
        code, out, _ = run(["get", "dens", "rho", "--json"], reports_dir, capsys)
        entry = json.loads(out)
        assert entry["value"] == 12.345 / 4.567
        assert entry["rounding"] == {"sigfigs": 3}

    def test_input_variable(self, reports_dir, capsys):
        code, out, _ = run(["get", "dens", "m", "--json"], reports_dir, capsys)
        assert json.loads(out)["value"] == 12.345

    def test_unknown_variable(self, reports_dir, capsys):
        code, _, err = run(["get", "dens", "zzz"], reports_dir, capsys)
        assert code == 1
        assert "存在しません" in err

    def test_table_column(self, tmp_path, capsys, free_fall_data):
        d = tmp_path / "reports"
        store = ReportStore(d)
        store.create("ff", get_template("free_fall"))
        store.save_results("ff", {}, free_fall_data)
        code, out, _ = run(["get", "ff", "drops.t2", "--json"], d, capsys)
        assert code == 0
        entry = json.loads(out)
        assert entry["kind"] == "derived_column"
        assert entry["values"][0] == 0.320**2


class TestVerifyValidateList:
    def test_verify_ok(self, reports_dir, capsys):
        code, out, _ = run(["verify", "dens"], reports_dir, capsys)
        assert code == 0
        assert "OK" in out

    def test_verify_ng(self, reports_dir, capsys):
        path = reports_dir / "dens" / "results.json"
        data = json.loads(path.read_text())
        data["computed"]["rho"]["value"] = 2.7
        path.write_text(json.dumps(data))
        code, _, err = run(["verify", "dens"], reports_dir, capsys)
        assert code == 1
        assert "一致しません" in err

    def test_validate_ok(self, reports_dir, capsys, tmp_path):
        p = tmp_path / "def.yaml"
        p.write_text(get_template("density"), encoding="utf-8")
        code, out, _ = run(["validate", str(p)], reports_dir, capsys)
        assert code == 0 and "OK" in out

    def test_validate_ng(self, reports_dir, capsys, tmp_path):
        p = tmp_path / "def.yaml"
        p.write_text("meta: {id: x, title: T}\nbad_key: 1", encoding="utf-8")
        code, _, err = run(["validate", str(p)], reports_dir, capsys)
        assert code == 1 and "NG" in err

    def test_list(self, reports_dir, capsys):
        code, out, _ = run(["list", "--json"], reports_dir, capsys)
        entries = json.loads(out)
        assert entries[0]["id"] == "dens"
        assert entries[0]["has_results"] is True
