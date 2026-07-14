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

    def test_csv(self, reports_dir, capsys):
        import csv
        import io

        code, out, _ = run(["show", "dens", "--format", "csv"], reports_dir, capsys)
        assert code == 0
        # Excel 用に UTF-8 BOM 付き
        assert out.startswith("\ufeff")
        rows = list(csv.reader(io.StringIO(out.lstrip("\ufeff"))))
        # レポート形式: タイトル・セクション見出しを含む
        assert rows[0] == ["金属試料の密度測定"]
        assert ["■ 測定値"] in rows
        assert ["■ 導出量"] in rows

        m_row = next(r for r in rows if r and r[0] == "m")
        assert m_row[2] == "12.345"          # 値
        assert m_row[3] == "g"               # 単位

        rho_row = next(r for r in rows if r and r[0] == "rho")
        assert rho_row[2] == "2.70"                    # 表示値
        assert rho_row[4] == repr(12.345 / 4.567)      # フル精度値
        assert rho_row[5] == "m / V"                   # 式

    def test_csv_table_grid(self, tmp_path, capsys, free_fall_data):
        d = tmp_path / "reports"
        store = ReportStore(d)
        store.create("ff", get_template("free_fall"))
        store.save_results("ff", {}, free_fall_data)
        code, out, _ = run(["show", "ff", "--format", "csv"], d, capsys)
        assert code == 0
        import csv
        import io
        rows = list(csv.reader(io.StringIO(out.lstrip("\ufeff"))))
        # 表はグリッド: 単位つきヘッダ + 各行 1 レコード
        header = next(r for r in rows if r and r[0] == "#")
        assert "落下距離 [m]" in header
        assert "時間の二乗 [s^2]" in header
        data_start = rows.index(header) + 1
        first = rows[data_start]
        assert first[0] == "1"          # 行番号
        assert first[1] == "0.5"        # h
        assert first[3] == "0.1024"     # t2 の表示値(グリッドセル)
        # 5 行分ある
        grid = rows[data_start:data_start + 5]
        assert [r[0] for r in grid] == ["1", "2", "3", "4", "5"]


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


class TestDefinitionEditing:
    """AI が CUI から定義を読み・差し替えて、誤差の導出量を後付けする流れ。"""

    def test_get_definition(self, reports_dir, capsys):
        code, out, _ = run(["get-definition", "dens"], reports_dir, capsys)
        assert code == 0
        assert "meta:" in out and "rho" in out

    def test_set_definition_from_file_adds_derived(self, reports_dir, capsys, tmp_path):
        # 現在の定義を取得
        _, current, _ = run(["get-definition", "dens"], reports_dir, capsys)
        # 誤差用の導出量を追記(rho の文献値からの差)
        new_yaml = current + (
            "  - name: rho_dev\n"
            "    label: 文献値からの偏差\n"
            "    expr: \"abs(rho - 7.874)\"\n"
            "    unit: g/cm^3\n"
            "    display: {sigfigs: 2}\n"
        )
        f = tmp_path / "new.yaml"
        f.write_text(new_yaml, encoding="utf-8")

        code, out, _ = run(["set-definition", "dens", str(f)], reports_dir, capsys)
        assert code == 0
        assert "再計算" in out

        # 既存の入力値(m, V)は保持され、新しい導出量が既存データに対して計算される
        code, gout, _ = run(["get", "dens", "rho_dev", "--json"], reports_dir, capsys)
        assert code == 0
        entry = json.loads(gout)
        assert entry["value"] == abs((12.345 / 4.567) - 7.874)

        # 再計算して保存し直されたので verify も通る
        code, _, _ = run(["verify", "dens"], reports_dir, capsys)
        assert code == 0

    def test_set_definition_from_stdin(self, reports_dir, capsys, monkeypatch):
        _, current, _ = run(["get-definition", "dens"], reports_dir, capsys)
        import io
        monkeypatch.setattr("sys.stdin", io.StringIO(current))
        code, out, _ = run(["set-definition", "dens"], reports_dir, capsys)
        assert code == 0

    def test_set_definition_invalid_keeps_original(self, reports_dir, capsys, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text("meta: {id: dens}\n", encoding="utf-8")  # title 欠落
        code, _, err = run(["set-definition", "dens", str(f)], reports_dir, capsys)
        assert code == 1
        assert "NG" in err
        # 元の定義は無傷
        code, out, _ = run(["get-definition", "dens"], reports_dir, capsys)
        assert "金属試料の密度測定" in out

    def test_add_fit_error_end_to_end(self, tmp_path, capsys, free_fall_data):
        """自由落下: 結果入力後に slope_err で g の誤差を後付けする。"""
        d = tmp_path / "reports"
        store = ReportStore(d)
        store.create("ff", get_template("free_fall"))
        store.save_results("ff", {}, free_fall_data)
        # この時点では g の誤差は無い。誤差版テンプレートに差し替える。
        new_def = get_template("free_fall_error").replace(
            "id: free_fall_error", "id: ff"
        )
        f = tmp_path / "ff_err.yaml"
        f.write_text(new_def, encoding="utf-8")
        code, out, _ = run(["set-definition", "ff", str(f)], d, capsys)
        assert code == 0
        # g_error が既存の測定データに対して計算されている
        code, gout, _ = run(["get", "ff", "g_error", "--json"], d, capsys)
        entry = json.loads(gout)
        assert entry["value"] is not None and entry["value"] > 0
        assert entry["expr"] == "2 * a_slope_err"
