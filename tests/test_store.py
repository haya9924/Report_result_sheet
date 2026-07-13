import json

import pytest

from resultsheet.errors import StoreError
from resultsheet.store import ReportStore, get_template, list_templates


@pytest.fixture
def store(tmp_path):
    return ReportStore(tmp_path / "reports")


@pytest.fixture
def density_store(store):
    store.create("my_density", get_template("density"))
    return store


class TestCrud:
    def test_create_and_load(self, density_store):
        report = density_store.load("my_density")
        assert report.definition.id == "density"
        assert report.results is None

    def test_create_duplicate(self, density_store):
        with pytest.raises(StoreError, match="既に存在"):
            density_store.create("my_density", get_template("density"))

    def test_create_invalid_yaml_rejected(self, store):
        with pytest.raises(Exception):
            store.create("bad", "meta: {id: t}")  # title 欠落
        assert store.list_reports() == []  # ディレクトリが残らない

    def test_invalid_id(self, store):
        with pytest.raises(StoreError, match="レポートID"):
            store.create("../escape", get_template("density"))

    def test_load_missing(self, store):
        with pytest.raises(StoreError, match="存在しません"):
            store.load("nope")

    def test_update_definition(self, density_store):
        text = density_store.definition_text("my_density").replace(
            "金属試料の密度測定", "改訂版"
        )
        report = density_store.update_definition("my_density", text)
        assert report.definition.title == "改訂版"

    def test_delete(self, density_store):
        density_store.save_results("my_density", {"m": 1.0, "V": 2.0}, {})
        density_store.delete("my_density")
        assert density_store.list_reports() == []

    def test_list(self, density_store):
        entries = density_store.list_reports()
        assert len(entries) == 1
        assert entries[0]["id"] == "my_density"
        assert entries[0]["title"] == "金属試料の密度測定"
        assert entries[0]["has_results"] is False


class TestResults:
    def test_save_and_roundtrip(self, density_store):
        payload = density_store.save_results("my_density", {"m": 12.345, "V": 4.567}, {})
        assert payload["computed"]["rho"]["value"] == 12.345 / 4.567
        assert payload["computed"]["rho"]["display"] == "2.70"

        # ディスク往復で float が完全に保存されること
        reloaded = density_store.load("my_density").results
        assert reloaded["computed"]["rho"]["value"] == 12.345 / 4.567
        assert reloaded["inputs"]["m"] == 12.345
        assert reloaded["definition_sha256"] == density_store.load(
            "my_density"
        ).definition.sha256

    def test_float_json_roundtrip_lossless(self):
        v = 12.345 / 4.567
        assert json.loads(json.dumps({"v": v}))["v"] == v

    def test_verify_ok(self, density_store):
        density_store.save_results("my_density", {"m": 12.345, "V": 4.567}, {})
        assert density_store.verify("my_density") == []

    def test_verify_no_results(self, density_store):
        assert any("保存されていません" in p for p in density_store.verify("my_density"))

    def test_verify_detects_tampered_value(self, density_store, tmp_path):
        density_store.save_results("my_density", {"m": 12.345, "V": 4.567}, {})
        path = density_store.reports_dir / "my_density" / "results.json"
        data = json.loads(path.read_text())
        data["computed"]["rho"]["value"] = 2.7  # 丸め値で上書き(典型的なAIのミス)
        path.write_text(json.dumps(data, ensure_ascii=False))
        problems = density_store.verify("my_density")
        assert any("一致しません" in p for p in problems)

    def test_verify_detects_definition_change(self, density_store):
        density_store.save_results("my_density", {"m": 12.345, "V": 4.567}, {})
        text = density_store.definition_text("my_density") + "\n# 変更\n"
        density_store.update_definition("my_density", text)
        problems = density_store.verify("my_density")
        assert any("変更されています" in p for p in problems)

    def test_table_results_saved(self, store, free_fall_data):
        store.create("ff", get_template("free_fall"))
        payload = store.save_results("ff", {}, free_fall_data)
        assert payload["tables"]["drops"]["columns"] == ["h", "t"]
        assert len(payload["tables"]["drops"]["rows"]) == 5
        assert len(payload["computed_columns"]["drops"]["t2"]) == 5
        assert store.verify("ff") == []


def test_templates_available():
    ids = [t["id"] for t in list_templates()]
    assert "density" in ids and "free_fall" in ids
    assert all(t["title"] for t in list_templates())
