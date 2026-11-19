"""Flow diagrams for plan.html: nodes and edges from plan.json drawn as inline SVG (no library, works offline).

    {"nodes": [{"id": "open", "label": "Mở 編集", "kind": "start"},
               {"id": "memo", "label": "buildMemo()", "kind": "step", "state": "changed"}],
     "edges": [{"from": "open", "to": "memo", "label": "estimate loaded"}]}

Kinds: start, end, step, decision, data, external. States: same (default), new, changed, removed.
Layout: nodes are placed in layers top to bottom by their longest path from a start; edges are drawn as
orthogonal elbows; an edge back to an earlier layer (a loop) runs along the right margin. Colours come from
the page's CSS variables, so light and dark themes both work.
"""

from __future__ import annotations

import hashlib
import html
import json
import unicodedata
from typing import Any

NODE_KINDS = ("start", "end", "step", "decision", "data", "external")
NODE_STATES = ("same", "new", "changed", "removed")
NODE_WIDTH = 250
LINE_HEIGHT = 17
NODE_PADDING = 12
LAYER_GAP = 44
COLUMN_GAP = 34
MARGIN = 20
LOOP_LANE = 26
MAX_LABEL_UNITS = 30  # half-width characters per line; CJK counts double


def validate_diagram(diagram: Any, where: str) -> list[str]:
    """Problems in one diagram object (empty list = drawable)."""
    if not isinstance(diagram, dict):
        return [f"{where}: must be {{nodes, edges}}"]
    problems: list[str] = []
    nodes = diagram.get("nodes")
    if not isinstance(nodes, list) or len(nodes) < 2:
        return [f"{where}.nodes: at least two nodes"]
    ids: list[str] = []
    for index, node in enumerate(nodes):
        node_where = f"{where}.nodes[{index}]"
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not node["id"]:
            problems.append(f"{node_where}: needs an id")
            continue
        if node["id"] in ids:
            problems.append(f"{node_where}.id: duplicated")
        ids.append(node["id"])
        if not isinstance(node.get("label"), str) or not node["label"].strip():
            problems.append(f"{node_where}.label: required")
        if node.get("kind", "step") not in NODE_KINDS:
            problems.append(f"{node_where}.kind: one of {', '.join(NODE_KINDS)}")
        if node.get("state", "same") not in NODE_STATES:
            problems.append(f"{node_where}.state: one of {', '.join(NODE_STATES)}")
    edges = diagram.get("edges")
    if not isinstance(edges, list) or not edges:
        problems.append(f"{where}.edges: at least one edge")
        return problems
    for index, edge in enumerate(edges):
        if not isinstance(edge, dict) or edge.get("from") not in ids or edge.get("to") not in ids:
            problems.append(f"{where}.edges[{index}]: from/to must be node ids")
    return problems


def _text_units(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in ("W", "F") else 1 for char in text)


def wrap_label(label: str, max_units: int = MAX_LABEL_UNITS) -> list[str]:
    """Split a label into lines of about `max_units` half-width characters; explicit newlines are kept."""
    lines: list[str] = []
    for paragraph in label.split("\n"):
        current = ""
        for word in paragraph.split(" "):
            candidate = f"{current} {word}".strip()
            if _text_units(candidate) <= max_units or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
            while _text_units(current) > max_units:
                cut = 1
                while cut < len(current) and _text_units(current[:cut + 1]) <= max_units:
                    cut += 1
                lines.append(current[:cut])
                current = current[cut:]
        lines.append(current)
    return [line for line in lines if line] or [label]


def _layers(node_ids: list[str], edges: list[dict[str, Any]]) -> tuple[dict[str, int], set[int]]:
    """Layer of each node by longest path, and the indexes of edges that go back (loops)."""
    outgoing: dict[str, list[tuple[int, str]]] = {node_id: [] for node_id in node_ids}
    for index, edge in enumerate(edges):
        outgoing[edge["from"]].append((index, edge["to"]))
    back_edges: set[int] = set()
    state: dict[str, int] = {}

    def visit(node_id: str) -> None:
        state[node_id] = 1
        for index, target in outgoing[node_id]:
            if state.get(target) == 1:
                back_edges.add(index)
            elif target not in state:
                visit(target)
        state[node_id] = 2

    incoming = {edge["to"] for edge in edges}
    for node_id in [node for node in node_ids if node not in incoming] + node_ids:
        if node_id not in state:
            visit(node_id)
    layer = {node_id: 0 for node_id in node_ids}
    for _ in node_ids:
        changed = False
        for index, edge in enumerate(edges):
            if index not in back_edges and layer[edge["to"]] < layer[edge["from"]] + 1:
                layer[edge["to"]] = layer[edge["from"]] + 1
                changed = True
        if not changed:
            break
    return layer, back_edges


def _shape(node: dict[str, Any], x: float, y: float, height: float) -> str:
    kind = node.get("kind", "step")
    css = f'node k-{kind} s-{node.get("state", "same")}'
    width = NODE_WIDTH
    if kind in ("start", "end"):
        return f'<rect class="{css}" x="{x}" y="{y}" width="{width}" height="{height}" rx="{height / 2}"/>'
    if kind == "decision":
        notch = 14
        points = (f"{x + notch},{y} {x + width - notch},{y} {x + width},{y + height / 2} "
                  f"{x + width - notch},{y + height} {x + notch},{y + height} {x},{y + height / 2}")
        return f'<polygon class="{css}" points="{points}"/>'
    if kind == "data":
        return (f'<rect class="{css}" x="{x}" y="{y}" width="{width}" height="{height}" rx="4"/>'
                f'<line class="node-line" x1="{x}" y1="{y + 6}" x2="{x + width}" y2="{y + 6}"/>')
    return f'<rect class="{css}" x="{x}" y="{y}" width="{width}" height="{height}" rx="8"/>'


DUMMY_WIDTH = 18  # slot of an edge passing through a layer, so it runs beside the nodes instead of through them


def _arrange(order: list[str], edges: list[dict[str, Any]], layer: dict[str, int],
             back_edges: set[int]) -> tuple[dict[int, list[str]], dict[int, list[str]]]:
    """Rows per layer (node ids plus dummy slots for long edges) and the waypoints of every long edge.

    Within a layer, nodes follow the average position of what points to them (barycenter), which keeps
    branches under their decision and reduces crossings.
    """
    rows: dict[int, list[str]] = {}
    for node_id in order:
        rows.setdefault(layer[node_id], []).append(node_id)
    parents: dict[str, list[str]] = {node_id: [] for node_id in order}
    chains: dict[int, list[str]] = {}
    for index, edge in enumerate(edges):
        if index in back_edges:
            continue
        previous = edge["from"]
        chain = []
        for middle_layer in range(layer[edge["from"]] + 1, layer[edge["to"]]):
            dummy = f"~{index}~{middle_layer}"
            rows[middle_layer].append(dummy)
            parents[dummy] = [previous]
            chain.append(dummy)
            previous = dummy
        parents[edge["to"]].append(previous)
        chains[index] = chain
    for layer_index in sorted(rows)[1:]:
        above = {item: position for position, item in enumerate(rows[layer_index - 1])} if layer_index - 1 in rows else {}

        def barycenter(item: str, above: dict[str, int] = above) -> float:
            known = [above[parent] for parent in parents.get(item, []) if parent in above]
            return sum(known) / len(known) if known else float("inf")

        rows[layer_index] = sorted(rows[layer_index], key=barycenter)
    return rows, chains


def render_diagram(diagram: dict[str, Any], title: str = "") -> str:
    """Inline SVG for a validated diagram plus a text version of the same flow."""
    nodes = {node["id"]: node for node in diagram["nodes"]}
    order = [node["id"] for node in diagram["nodes"]]
    edges = diagram["edges"]
    layer, back_edges = _layers(order, edges)
    rows, chains = _arrange(order, edges, layer, back_edges)
    lines = {node_id: wrap_label(nodes[node_id]["label"]) for node_id in order}
    heights = {node_id: len(lines[node_id]) * LINE_HEIGHT + 2 * NODE_PADDING for node_id in order}

    def width_of(item: str) -> float:
        return DUMMY_WIDTH if item.startswith("~") else NODE_WIDTH

    row_widths = {index: sum(width_of(item) for item in row) + (len(row) - 1) * COLUMN_GAP for index, row in rows.items()}
    content_width = max(row_widths.values())
    loop_space = LOOP_LANE * (len(back_edges) + 1) if back_edges else 0
    width = content_width + 2 * MARGIN + loop_space
    positions: dict[str, tuple[float, float]] = {}  # top-left of nodes; centre-x of dummies
    layer_top: dict[int, float] = {}
    layer_bottom: dict[int, float] = {}
    top = MARGIN
    for row_index in sorted(rows):
        row = rows[row_index]
        left = MARGIN + (content_width - row_widths[row_index]) / 2
        row_height = max((heights[item] for item in row if not item.startswith("~")), default=LINE_HEIGHT)
        for item in row:
            positions[item] = (left + DUMMY_WIDTH / 2, top) if item.startswith("~") else (left, top)
            left += width_of(item) + COLUMN_GAP
        layer_top[row_index], layer_bottom[row_index] = top, top + row_height
        top += row_height + LAYER_GAP
    height = top - LAYER_GAP + MARGIN
    # One marker per diagram: a page holds many diagrams, and a marker inside a hidden page would not render.
    marker_id = "arrow-" + hashlib.sha1(json.dumps(diagram, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:10]
    geometry = {"positions": positions, "heights": heights, "layer": layer, "layer_top": layer_top,
                "content_width": content_width, "back_edges": sorted(back_edges)}
    parts = [_edge_svg(edge, index, chains.get(index), geometry, marker_id) for index, edge in enumerate(edges)]
    for node_id in order:
        x, y = positions[node_id]
        parts.append(_shape(nodes[node_id], x, y, heights[node_id]))
        text_x = x + NODE_WIDTH / 2
        spans = "".join(f'<tspan x="{text_x}" dy="{LINE_HEIGHT if index else 0}">{html.escape(line)}</tspan>'
                        for index, line in enumerate(lines[node_id]))
        css = "label s-removed" if nodes[node_id].get("state") == "removed" else "label"
        parts.append(f'<text class="{css}" x="{text_x}" y="{y + NODE_PADDING + 12}" text-anchor="middle">{spans}</text>')
    aria = html.escape(title or "flow")
    svg = (f'<svg class="flow" viewBox="0 0 {width:.0f} {height:.0f}" width="{width:.0f}" role="img" aria-label="{aria}" '
           f'xmlns="http://www.w3.org/2000/svg"><defs><marker id="{marker_id}" viewBox="0 0 10 10" refX="9" refY="5" '
           f'markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="arrow"/>'
           f'</marker></defs>{"".join(parts)}</svg>')
    return f'<figure class="flow-figure"><div class="flow-scroll">{svg}</div>{_legend(diagram)}{_text_version(diagram)}</figure>'


def _edge_svg(edge: dict[str, Any], index: int, chain: list[str] | None, geometry: dict[str, Any], marker_id: str) -> str:
    """Orthogonal path of one edge: down through the dummy slots of a long edge, or a loop on the right margin."""
    positions, heights = geometry["positions"], geometry["heights"]
    source_x, source_y = positions[edge["from"]]
    target_x, target_y = positions[edge["to"]]
    if chain is None:
        lane = MARGIN + geometry["content_width"] + LOOP_LANE * (geometry["back_edges"].index(index) + 1)
        start = (source_x + NODE_WIDTH, source_y + heights[edge["from"]] / 2)
        end = (target_x + NODE_WIDTH, target_y + heights[edge["to"]] / 2)
        points = [start, (lane, start[1]), (lane, end[1]), end]
        label_at = (lane, (start[1] + end[1]) / 2)
        css = "edge back"
    else:
        layer_top = geometry["layer_top"]
        start = (source_x + NODE_WIDTH / 2, source_y + heights[edge["from"]])
        points = [start]
        current_x = start[0]
        first_layer = geometry["layer"][edge["from"]] + 1
        waypoints = [positions[dummy][0] for dummy in chain] + [target_x + NODE_WIDTH / 2]
        for offset, next_x in enumerate(waypoints):
            middle = layer_top[first_layer + offset] - LAYER_GAP / 2
            points += [(current_x, middle), (next_x, middle)]
            current_x = next_x
        points.append((current_x, target_y))
        first_middle = points[1][1]
        label_at = ((start[0] + points[2][0]) / 2 if start[0] != points[2][0] else start[0], (start[1] + first_middle) / 2 + 4)
        css = "edge"
    path = " ".join(f"{'M' if position == 0 else 'L'}{x:.1f},{y:.1f}" for position, (x, y) in enumerate(points))
    label = ""
    if edge.get("label"):
        text = html.escape(edge["label"])
        box_width = _text_units(edge["label"]) * 6.4 + 10
        label = (f'<rect class="edge-label-bg" x="{label_at[0] - box_width / 2:.1f}" y="{label_at[1] - 12:.1f}" '
                 f'width="{box_width:.1f}" height="17" rx="4"/><text class="edge-label" x="{label_at[0]:.1f}" '
                 f'y="{label_at[1]:.1f}" text-anchor="middle">{text}</text>')
    return f'<path class="{css}" d="{path}" marker-end="url(#{marker_id})"/>{label}'


def _legend(diagram: dict[str, Any]) -> str:
    states = {node.get("state", "same") for node in diagram["nodes"]}
    kinds = {node.get("kind", "step") for node in diagram["nodes"]}
    entries = [f'<span class="lg s-{state}" data-legend="state-{state}"></span>' for state in NODE_STATES if state in states]
    entries += [f'<span class="lg k-{kind}" data-legend="kind-{kind}"></span>' for kind in ("decision", "data", "external")
                if kind in kinds]
    return f'<figcaption class="legend">{"".join(entries)}</figcaption>' if len(entries) > 1 else ""


def _text_version(diagram: dict[str, Any]) -> str:
    """The same flow as an ordered list, for screen readers, search and copy."""
    labels = {node["id"]: node["label"].replace("\n", " ") for node in diagram["nodes"]}
    items = []
    for node in diagram["nodes"]:
        targets = [edge for edge in diagram["edges"] if edge["from"] == node["id"]]
        arrows = "; ".join(f"→ {html.escape(labels[edge['to']])}" + (f" ({html.escape(edge['label'])})" if edge.get("label") else "")
                           for edge in targets)
        state = node.get("state", "same")
        badge = f' <span class="pill st-{state}" data-legend="state-{state}"></span>' if state != "same" else ""
        items.append(f"<li><b>{html.escape(labels[node['id']])}</b>{badge}{' ' + arrows if arrows else ''}</li>")
    return f'<details class="flow-text"><summary data-legend="as-text"></summary><ol>{"".join(items)}</ol></details>'
