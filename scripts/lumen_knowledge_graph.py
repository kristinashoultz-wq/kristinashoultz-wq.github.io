"""
lumen_knowledge_graph.py — Local Knowledge Graph Engine

Background daemon that scans all scripts in your stack,
extracts semantic connections (shared ports, flags, member refs),
builds a live topology graph, and exposes it via:

  1. lumen_topology.json    — machine-readable graph (BASE dir)
  2. Ecosystem Map.md       — human-readable Markdown (Obsidian vault)
  3. TCP query socket :7910 — members can ask "who uses port 8765?"

QUERY PROTOCOL (newline-delimited JSON over TCP)
  {"query": "port",    "value": "8765"}
  {"query": "flag",    "value": "emergency_trip.flag"}
  {"query": "member",  "value": "Person1"}
  {"query": "script",  "value": "orchestrator.py"}
  {"query": "all"}

HOW TO START
  py -3.12 lumen_knowledge_graph.py
  Ctrl+C to stop.

OPTIONS (env vars)
  GRAPH_INTERVAL — seconds between scans, default 300 (5 min)
  GRAPH_PORT     — TCP query port, default 7910
"""

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("lumen_kg")

# ─────────────────────────────────────────────
# CONFIG — mirrors orchestrator.py layout
# ─────────────────────────────────────────────
BASE     = Path(r"C:\path\to\your\home")
REEVES   = BASE / "Documents" / "YourFolder"
VAULT    = REEVES  # Obsidian vault root

SCAN_DIRS = [
    BASE,
    REEVES / "sentry",
    REEVES / "ledger-server",
    BASE / "desktop_control",
]

TOPOLOGY_JSON = BASE / "lumen_topology.json"
ECOSYSTEM_MAP = VAULT / "Ecosystem Map.md"

SCAN_INTERVAL = int(os.getenv("GRAPH_INTERVAL", "300"))
QUERY_PORT    = int(os.getenv("GRAPH_PORT", "7910"))

NAMES_TO_TRACK = ["Person1", "Person2", "Person3", "Person4", "Person5"]  # customize to your household

# ─────────────────────────────────────────────
# EXTRACTION PATTERNS
# ─────────────────────────────────────────────

# Catches the port patterns actually used across our stack:
#   os.getenv("X", "7907")   → env-var default
#   create_connection((..., 7907))  → socket tuple
#   start_server(..., "127.0.0.1", 7910)  → asyncio server
#   localhost:7899, localhost/7899  → URL style
#   port 8765, port=7901, port: 8766  → plain text / keyword
_PORT_RX = [
    re.compile(r'os\.getenv\([^,)]+,\s*["\'](\d{4,5})["\']'),
    re.compile(r'create_connection\(\s*\([^)]+,\s*(\d{4,5})\)'),
    re.compile(r'start_server\([^,)]+,\s*[^,)]+,\s*(\d{4,5})'),
    re.compile(r'localhost[:/](\d{4,5})'),
    re.compile(r'\bport\b[^a-zA-Z\d]{0,6}(\d{4,5})', re.IGNORECASE),
]

_FLAG_RX    = re.compile(r'[\w_/-]+\.flag')
_MEMBER_RX = {b: re.compile(r'\b' + b + r'\b', re.IGNORECASE) for b in NAMES_TO_TRACK}


def _extract(content: str) -> dict:
    ports: set[str] = set()
    for rx in _PORT_RX:
        for m in rx.finditer(content):
            val = m.group(1)
            if val:
                ports.add(val)

    flags   = set(_FLAG_RX.findall(content))
    members = [b for b, rx in _MEMBER_RX.items() if rx.search(content)]

    return {
        "ports":   sorted(ports),
        "flags":   sorted(flags),
        "members": members,
    }


def _collect_scripts() -> list[Path]:
    scripts: list[Path] = []
    for d in SCAN_DIRS:
        if d.exists():
            scripts.extend(p for p in d.glob("*.py") if p.is_file())
    return scripts


def _build_graph(scripts: list[Path]) -> dict:
    nodes: dict[str, dict] = {}

    for path in scripts:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            log.warning("Could not read %s: %s", path.name, e)
            continue

        info = _extract(content)
        stat = path.stat()
        nodes[path.name] = {
            "path":       str(path),
            "dir":        str(path.parent),
            "size_bytes": stat.st_size,
            "modified":   datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            **info,
        }

    # Build edges: link any two scripts that share a port or flag
    edges: list[dict] = []
    names = list(nodes.keys())
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = nodes[names[i]], nodes[names[j]]
            shared_ports = set(a["ports"]) & set(b["ports"])
            shared_flags = set(a["flags"]) & set(b["flags"])
            if shared_ports or shared_flags:
                edges.append({
                    "source":       names[i],
                    "target":       names[j],
                    "shared_ports": sorted(shared_ports),
                    "shared_flags": sorted(shared_flags),
                })

    return {
        "generated":    datetime.now().isoformat(timespec="seconds"),
        "script_count": len(nodes),
        "nodes":        nodes,
        "edges":        edges,
    }


# ─────────────────────────────────────────────
# TOPOLOGY JSON
# ─────────────────────────────────────────────

def _save_topology(graph: dict) -> None:
    TOPOLOGY_JSON.write_text(json.dumps(graph, indent=2), encoding="utf-8")
    log.info(
        "Topology saved: %d nodes, %d edges → %s",
        graph["script_count"], len(graph["edges"]), TOPOLOGY_JSON.name,
    )


# ─────────────────────────────────────────────
# ECOSYSTEM MAP (Obsidian Markdown)
# ─────────────────────────────────────────────

def _render_ecosystem_map(graph: dict) -> str:
    nodes  = graph["nodes"]
    edges  = graph["edges"]
    ts     = graph["generated"]
    n_scripts = graph["script_count"]
    n_edges   = len(edges)

    lines = [
        "# Ecosystem Map",
        f"*Auto-generated by Knowledge Graph · {ts}*",
        f"*{n_scripts} scripts · {n_edges} connections*",
        "",
        "---",
        "",
        "## Script Directory",
        "",
        "| Script | Dir | Ports | Flags | Members |",
        "|--------|-----|-------|-------|---------|",
    ]
    for name, info in sorted(nodes.items()):
        dir_label = Path(info["dir"]).name
        ports    = ", ".join(info["ports"]) or "—"
        flags    = ", ".join(f"`{f}`" for f in info["flags"]) or "—"
        members  = ", ".join(info["members"]) or "—"
        lines.append(f"| `{name}` | {dir_label} | {ports} | {flags} | {members} |")

    # Port → scripts index
    port_map: dict[str, list[str]] = {}
    for name, info in nodes.items():
        for p in info["ports"]:
            port_map.setdefault(p, []).append(name)

    lines += [
        "",
        "---",
        "",
        "## Port Map",
        "",
        "| Port | Used By |",
        "|------|---------|",
    ]
    for port in sorted(port_map, key=lambda x: int(x)):
        scripts = ", ".join(f"`{s}`" for s in sorted(port_map[port]))
        lines.append(f"| {port} | {scripts} |")

    # Flag → scripts index (only flags shared by 2+ scripts are interesting)
    flag_map: dict[str, list[str]] = {}
    for name, info in nodes.items():
        for f in info["flags"]:
            flag_map.setdefault(f, []).append(name)

    shared_flags = {f: s for f, s in flag_map.items() if len(s) > 1}
    if shared_flags:
        lines += [
            "",
            "---",
            "",
            "## Shared Flags",
            "",
            "| Flag | Scripts |",
            "|------|---------|",
        ]
        for flag, scripts in sorted(shared_flags.items()):
            s = ", ".join(f"`{x}`" for x in sorted(scripts))
            lines.append(f"| `{flag}` | {s} |")

    # Connection edges
    if edges:
        lines += [
            "",
            "---",
            "",
            "## Connections",
            "",
            "| Script A | Script B | Shared Ports | Shared Flags |",
            "|----------|----------|--------------|--------------|",
        ]
        for e in sorted(edges, key=lambda x: (x["source"], x["target"])):
            ports = ", ".join(e["shared_ports"]) or "—"
            flags = ", ".join(f"`{f}`" for f in e["shared_flags"]) or "—"
            lines.append(
                f"| `{e['source']}` | `{e['target']}` | {ports} | {flags} |"
            )

    lines.append("")
    return "\n".join(lines)


def _save_ecosystem_map(graph: dict) -> None:
    content = _render_ecosystem_map(graph)
    try:
        ECOSYSTEM_MAP.write_text(content, encoding="utf-8")
        log.info("Ecosystem Map written → %s", ECOSYSTEM_MAP)
    except Exception as e:
        log.error("Could not write Ecosystem Map: %s", e)


# ─────────────────────────────────────────────
# QUERY SERVER
# ─────────────────────────────────────────────

_current_graph: dict = {}


def _handle_query(req: dict) -> dict:
    g = _current_graph
    if not g:
        return {"error": "graph not ready — first scan still running"}

    query  = req.get("query", "").lower()
    value  = str(req.get("value", "")).lower()
    nodes  = g.get("nodes", {})
    edges  = g.get("edges", [])

    if query == "all":
        return g

    if query == "port":
        matching = {n: d for n, d in nodes.items() if value in d["ports"]}
        related  = [e for e in edges if value in e["shared_ports"]]
        return {"query": "port", "value": value, "scripts": matching, "edges": related}

    if query == "flag":
        matching = {n: d for n, d in nodes.items()
                    if any(value in f for f in d["flags"])}
        related  = [e for e in edges
                    if any(value in f for f in e["shared_flags"])]
        return {"query": "flag", "value": value, "scripts": matching, "edges": related}

    if query == "member":
        matching = {n: d for n, d in nodes.items()
                    if any(value == b.lower() for b in d["members"])}
        return {"query": "member", "value": value, "scripts": matching}

    if query == "script":
        name  = value if value.endswith(".py") else value + ".py"
        node  = {k: v for k, v in nodes.items() if k.lower() == name.lower()}
        related = [e for e in edges
                   if e["source"].lower() == name.lower()
                   or e["target"].lower() == name.lower()]
        return {"query": "script", "value": name, "scripts": node, "edges": related}

    return {
        "error": f"unknown query {query!r} — use: port, flag, member, script, all"
    }


async def _handle_client(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    try:
        raw    = await asyncio.wait_for(reader.readline(), timeout=10)
        req    = json.loads(raw)
        result = _handle_query(req)
        writer.write((json.dumps(result) + "\n").encode())
        await writer.drain()
    except Exception as e:
        try:
            writer.write((json.dumps({"error": str(e)}) + "\n").encode())
            await writer.drain()
        except Exception:
            pass
    finally:
        writer.close()


# ─────────────────────────────────────────────
# SCAN LOOP
# ─────────────────────────────────────────────

async def _scan_loop() -> None:
    global _current_graph
    while True:
        start = time.monotonic()
        try:
            scripts = _collect_scripts()
            graph   = _build_graph(scripts)
            _current_graph = graph
            _save_topology(graph)
            _save_ecosystem_map(graph)
            elapsed = time.monotonic() - start
            log.info("Scan complete in %.1fs — next in %ds", elapsed, SCAN_INTERVAL)
        except Exception as e:
            log.error("Scan error: %s", e)
        await asyncio.sleep(SCAN_INTERVAL)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

async def main() -> None:
    server = await asyncio.start_server(_handle_client, "127.0.0.1", QUERY_PORT)
    log.info(
        "Knowledge Graph online | query port: %d | scan interval: %ds",
        QUERY_PORT, SCAN_INTERVAL,
    )
    log.info("Scanning %d dirs: %s", len(SCAN_DIRS), ", ".join(d.name for d in SCAN_DIRS))

    async with server:
        asyncio.create_task(_scan_loop())
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Knowledge Graph offline.")
