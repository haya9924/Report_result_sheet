import pytest

from resultsheet.errors import CycleError, DefinitionError
from resultsheet.schema import load_definition

MINIMAL = """
meta: {id: t, title: テスト}
inputs:
  - {name: x, label: X}
derived:
  - {name: y, expr: "x * 2"}
"""


def test_minimal_loads():
    d = load_definition(MINIMAL)
    assert d.id == "t"
    assert d.inputs[0].name == "x"
    assert d.derived[0].expr == "x * 2"


def test_templates_load(density_def, free_fall_def):
    assert density_def.id == "density"
    assert free_fall_def.tables[0].name == "drops"
    assert [c.name for c in free_fall_def.tables[0].columns] == ["h", "t"]


def test_sha256_stable(density_def):
    assert len(density_def.sha256) == 64


@pytest.mark.parametrize(
    "yaml_text, match",
    [
        ("meta: {id: t, title: T}\nunknown_key: 1", "未知のキー"),
        ("meta: {id: t, title: T}\ninputs:\n  - {name: x, label: X, unitt: m}", "未知のキー"),
        ("meta: {id: 'bad id', title: T}", "meta.id"),
        ("meta: {title: T}", "meta.id"),
        ("meta: {id: t, title: T}\ninputs:\n  - {label: X}", "name"),
        (
            "meta: {id: t, title: T}\n"
            "inputs:\n  - {name: x, label: A}\n  - {name: x, label: B}",
            "重複",
        ),
        (
            "meta: {id: t, title: T}\n"
            "inputs:\n  - {name: pi, label: P}",
            "衝突",
        ),
        (
            "meta: {id: t, title: T}\n"
            "derived:\n  - {name: y, expr: 'nothere + 1'}",
            "定義されていません",
        ),
        (
            "meta: {id: t, title: T}\n"
            "derived:\n  - {name: y, expr: 'tbl.col'}",
            "定義されていません",
        ),
        (
            "meta: {id: t, title: T}\n"
            "inputs:\n  - {name: x, label: X, display: {sigfigs: 3, decimals: 2}}",
            "どちらか一方",
        ),
        (
            "meta: {id: t, title: T}\n"
            "inputs:\n  - {name: x, label: X, display: {sigfigs: 0}}",
            "1 以上",
        ),
        (
            "meta: {id: t, title: T}\n"
            "derived:\n  - {name: y, expr: '__import__(\"os\")'}",
            "未知の関数",
        ),
        ("not: [valid", "YAML"),
        ("- a\n- b", "マッピング"),
    ],
)
def test_rejects(yaml_text, match):
    with pytest.raises(DefinitionError, match=match):
        load_definition(yaml_text)


def test_cycle_detected():
    with pytest.raises(CycleError):
        load_definition(
            "meta: {id: t, title: T}\n"
            "derived:\n"
            "  - {name: a, expr: 'b + 1'}\n"
            "  - {name: b, expr: 'a + 1'}\n"
        )


def test_derived_column_cannot_use_table_reference():
    with pytest.raises(DefinitionError, match="テーブル参照は使えません"):
        load_definition(
            "meta: {id: t, title: T}\n"
            "tables:\n"
            "  - name: tb\n"
            "    label: T\n"
            "    columns: [{name: v, label: V}]\n"
            "    derived_columns:\n"
            "      - {name: w, expr: 'mean(tb.v)'}\n"
        )


def test_derived_column_can_use_inputs_and_constants():
    d = load_definition(
        "meta: {id: t, title: T}\n"
        "constants:\n"
        "  k: {value: 2.5}\n"
        "inputs:\n"
        "  - {name: offset, label: O}\n"
        "tables:\n"
        "  - name: tb\n"
        "    label: T\n"
        "    columns: [{name: v, label: V}]\n"
        "    derived_columns:\n"
        "      - {name: w, expr: 'k * v + offset'}\n"
    )
    assert d.tables[0].derived_columns[0].name == "w"


def test_duplicate_column_name():
    with pytest.raises(DefinitionError, match="重複"):
        load_definition(
            "meta: {id: t, title: T}\n"
            "tables:\n"
            "  - name: tb\n"
            "    label: T\n"
            "    columns: [{name: v, label: A}, {name: v, label: B}]\n"
        )
