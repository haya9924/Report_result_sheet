import pytest
from fastapi.testclient import TestClient

from resultsheet.server import create_app
from resultsheet.store import get_template


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path / "reports"))


@pytest.fixture
def with_density(client):
    r = client.post("/api/reports", json={"id": "dens", "template": "density"})
    assert r.status_code == 201
    return client


class TestReportManagement:
    def test_create_from_template(self, with_density):
        r = with_density.get("/api/reports")
        assert [e["id"] for e in r.json()] == ["dens"]

    def test_create_from_yaml(self, client):
        r = client.post(
            "/api/reports", json={"id": "custom", "yaml": get_template("free_fall")}
        )
        assert r.status_code == 201
        assert r.json()["definition"]["tables"][0]["name"] == "drops"

    def test_create_invalid_yaml(self, client):
        r = client.post("/api/reports", json={"id": "bad", "yaml": "meta: {id: x}"})
        assert r.status_code == 400
        assert "title" in r.json()["detail"]["message"]

    def test_create_duplicate(self, with_density):
        r = with_density.post("/api/reports", json={"id": "dens", "template": "density"})
        assert r.status_code == 400

    def test_templates(self, client):
        ids = [t["id"] for t in client.get("/api/templates").json()]
        assert "density" in ids

    def test_definition_roundtrip(self, with_density):
        text = with_density.get("/api/reports/dens/definition").text
        assert "meta:" in text
        r = with_density.put(
            "/api/reports/dens/definition",
            json={"yaml": text.replace("金属試料の密度測定", "改訂")},
        )
        assert r.status_code == 200
        assert r.json()["definition"]["title"] == "改訂"

    def test_put_invalid_definition_rejected(self, with_density):
        r = with_density.put(
            "/api/reports/dens/definition", json={"yaml": "meta: {id: x}"}
        )
        assert r.status_code == 400
        # 元の定義は壊れていない
        assert with_density.get("/api/reports/dens").status_code == 200

    def test_delete(self, with_density):
        assert with_density.delete("/api/reports/dens").status_code == 204
        assert with_density.get("/api/reports/dens").status_code == 404

    def test_validate_endpoint(self, client):
        ok = client.post("/api/validate", json={"yaml": get_template("density")}).json()
        assert ok["ok"] is True
        ng = client.post("/api/validate", json={"yaml": "meta: {id: x}"}).json()
        assert ng["ok"] is False and "title" in ng["error"]

    def test_edit_definition_recomputes_over_existing_results(self, with_density):
        # 結果を入力・保存
        with_density.put(
            "/api/reports/dens/results",
            json={"inputs": {"m": 12.345, "V": 4.567}, "tables": {}},
        )
        # 定義エディタ相当: 誤差の導出量を追記して保存
        text = with_density.get("/api/reports/dens/definition").text
        new_text = text + (
            "  - name: rho_dev\n    expr: \"abs(rho - 7.874)\"\n    unit: g/cm^3\n"
        )
        r = with_density.put("/api/reports/dens/definition", json={"yaml": new_text})
        assert r.status_code == 200
        # 既存の入力に対して新しい導出量が計算され、保存済み結果に反映される
        saved = with_density.get("/api/reports/dens/results").json()
        assert saved["inputs"]["m"] == 12.345
        assert saved["computed"]["rho_dev"]["value"] == abs((12.345 / 4.567) - 7.874)


class TestComputeAndResults:
    def test_live_compute_not_saved(self, with_density):
        r = with_density.post(
            "/api/reports/dens/compute",
            json={"inputs": {"m": 12.345, "V": 4.567}, "tables": {}},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["computed"]["rho"]["value"] == 12.345 / 4.567
        assert body["computed"]["rho"]["display"] == "2.70"
        # compute は保存しない
        assert with_density.get("/api/reports/dens/results").status_code == 404

    def test_save_and_get_results(self, with_density):
        r = with_density.put(
            "/api/reports/dens/results",
            json={"inputs": {"m": 12.345, "V": 4.567}, "tables": {}},
        )
        assert r.status_code == 200
        saved = with_density.get("/api/reports/dens/results").json()
        assert saved["inputs"]["m"] == 12.345
        assert saved["computed"]["rho"]["value"] == 12.345 / 4.567

    def test_partial_input(self, with_density):
        r = with_density.post(
            "/api/reports/dens/compute", json={"inputs": {"m": 1.0}, "tables": {}}
        )
        assert r.json()["computed"]["rho"]["value"] is None
        assert r.json()["computed"]["rho"]["display"] == "—"

    def test_compute_returns_range_warnings(self, with_density):
        r = with_density.post(
            "/api/reports/dens/compute",
            json={"inputs": {"m": 12.0, "V": 9999.0}, "tables": {}},
        )
        rw = r.json()["range_warnings"]
        assert "V" in rw["inputs"]           # 入力が範囲外
        assert "rho" in rw["derived"]        # 導出量も範囲外
        # 定義にも range が含まれる(GUI がヒント表示に使う)
        definition = with_density.get("/api/reports/dens").json()["definition"]
        assert definition["inputs"][0]["range"] is not None

    def test_adhoc_fit(self, client, free_fall_data):
        client.post("/api/reports", json={"id": "ff", "template": "free_fall"})
        r = client.post(
            "/api/reports/ff/compute",
            json={
                "inputs": {},
                "tables": free_fall_data,
                "adhoc_fit": {"table": "drops", "x": "t2", "y": "h"},
            },
        )
        fit = r.json()["adhoc_fit"]
        assert fit["slope"] == pytest.approx(4.9, rel=0.05)
        assert abs(fit["rvalue"]) > 0.999

    def test_export_json_and_md(self, with_density):
        with_density.put(
            "/api/reports/dens/results",
            json={"inputs": {"m": 12.345, "V": 4.567}, "tables": {}},
        )
        j = with_density.get("/api/reports/dens/export?format=json").json()
        assert j["derived"]["rho"]["display"] == "2.70"
        md = with_density.get("/api/reports/dens/export?format=md").text
        assert "| rho | 2.70 |" in md

        r = with_density.get("/api/reports/dens/export?format=csv")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        assert "attachment" in r.headers["content-disposition"]
        import csv
        import io
        text = r.text.lstrip("\ufeff")  # Excel 用 BOM を取り除いてから解析
        rows = list(csv.reader(io.StringIO(text)))
        assert ["■ 導出量"] in rows
        rho_row = next(x for x in rows if x and x[0] == "rho")
        assert rho_row[2] == "2.70"                  # 表示値
        assert rho_row[4] == repr(12.345 / 4.567)    # フル精度値


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "resultsheet" in r.text
