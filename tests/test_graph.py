import pytest

from resultsheet.engine.graph import topological_order
from resultsheet.errors import CycleError


def test_simple_chain():
    exprs = {"c": "b + 1", "b": "a * 2", "a": "x + y"}
    order = topological_order(exprs, {"x", "y"})
    assert order.index("a") < order.index("b") < order.index("c")


def test_table_column_deps_do_not_create_edges():
    exprs = {"g": "2 * a", "a": "slope(drops.t2, drops.h)"}
    order = topological_order(exprs, {"drops.t2", "drops.h"})
    assert order.index("a") < order.index("g")


def test_independent_nodes_sorted_deterministically():
    exprs = {"b": "x", "a": "x", "c": "x"}
    assert topological_order(exprs, {"x"}) == ["a", "b", "c"]


def test_self_reference_detected():
    with pytest.raises(CycleError, match="循環"):
        topological_order({"a": "a + 1"}, set())


def test_mutual_cycle_detected_with_path():
    with pytest.raises(CycleError) as exc:
        topological_order({"a": "b + 1", "b": "a * 2"}, set())
    msg = str(exc.value)
    assert "a" in msg and "b" in msg and "→" in msg


def test_three_node_cycle():
    with pytest.raises(CycleError):
        topological_order({"a": "c", "b": "a", "c": "b"}, set())
