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


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "resultsheet" in r.text
