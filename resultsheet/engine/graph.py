"""計算式の依存グラフ: 依存抽出・トポロジカルソート・循環検出。"""

from __future__ import annotations

from resultsheet.engine.safe_eval import extract_references
from resultsheet.errors import CycleError


def topological_order(exprs: dict[str, str], known: set[str]) -> list[str]:
    """exprs (name -> 式) を評価可能な順に並べる。

    known は式の外で与えられる名前(constants / inputs / table.col など)。
    exprs 内の名前同士の依存だけを辺として Kahn 法でソートし、
    循環があれば循環パス付きの CycleError を送出する。

    未定義参照はここでは検出しない(schema.py が全スコープを知ったうえで行う)。
    """
    deps: dict[str, set[str]] = {}
    for name, expr in exprs.items():
        refs = extract_references(expr)
        deps[name] = {r for r in refs if r in exprs and r != name} | (
            {name} if name in refs else set()
        )

    order: list[str] = []
    remaining = dict(deps)
    while remaining:
        ready = sorted(n for n, d in remaining.items() if not (d & remaining.keys()))
        if not ready:
            raise CycleError(_cycle_message(remaining))
        order.extend(ready)
        for n in ready:
            del remaining[n]
    return order


def _cycle_message(remaining: dict[str, set[str]]) -> str:
    """残ったノードから循環パスを一つ見つけてメッセージ化する。"""
    start = next(iter(remaining))
    path = [start]
    seen = {start}
    node = start
    while True:
        nxt = next(iter(sorted(d for d in remaining[node] if d in remaining)), None)
        if nxt is None:
            break
        if nxt in seen:
            cycle = path[path.index(nxt):] + [nxt]
            return "計算式に循環依存があります: " + " → ".join(cycle)
        path.append(nxt)
        seen.add(nxt)
        node = nxt
    return "計算式に循環依存があります: " + ", ".join(sorted(remaining))
