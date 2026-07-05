#!/usr/bin/env python3
"""
sync-tool-configs.py — Universal tool-config generator for the OS.

Single source of truth: `.claude/agents/**/*.md` (Claude Code subagents).
This script regenerates the equivalent native agent definitions for every other
supported tool, plus the auto-managed roster block in AGENTS.md, so that adding /
changing / removing a Claude Code agent propagates everywhere automatically.

GENERATED, NEVER HAND-EDITED:
  .cursor/agents/<name>.md      Cursor subagents
  .codex/agents/<name>.toml     Codex custom subagents
  AGENTS.md  (roster block between BEGIN/END GENERATED markers)

Modes:
  (no args)        Regenerate everything, print a summary of what changed.
  --check          Verify outputs are in sync with source. Exit 1 if stale
                   (for CI / pre-commit). Writes nothing.
  --hook           Hook mode: reads the tool-call JSON on stdin. If the edited
                   file is a source file (.claude/agents|skills, CLAUDE.md,
                   AGENTS.md structure), regenerate quietly; otherwise no-op.
                   Never fails the parent tool call.
  --quiet          Suppress the summary (still writes / checks).

The config-steward agent owns this script. See docs/multi-tool-support.md.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO / ".claude" / "agents"
CURSOR_AGENTS = REPO / ".cursor" / "agents"
CODEX_AGENTS = REPO / ".codex" / "agents"
AGENTS_MD = REPO / "AGENTS.md"

ROSTER_BEGIN = "<!-- BEGIN GENERATED: agent-roster (managed by scripts/sync-tool-configs.py — do not edit by hand) -->"
ROSTER_END = "<!-- END GENERATED: agent-roster -->"

# Claude Code tool names -> portable capability set. CC-specific orchestration
# tools (Agent, Task*, Artifact, NotebookEdit, ExitPlanMode) have no cross-tool
# equivalent and are dropped; the target tool grants its own defaults instead.
PORTABLE_TOOLS = {
    "Read": "Read",
    "Write": "Write",
    "Edit": "Edit",
    "Glob": "Glob",
    "Grep": "Grep",
    "Bash": "Bash",
    "PowerShell": "Bash",   # both are "run a shell command" on the target tool
    "WebSearch": "WebSearch",
    "WebFetch": "WebFetch",
}
# "Read-only role" = no file-mutation tools. Bash/PowerShell are for running
# commands (tests, git) and don't by themselves make a role a file author.
MUTATE_TOOLS = {"Write", "Edit"}

GEN_NOTE = "AUTO-GENERATED from {src} by scripts/sync-tool-configs.py. DO NOT EDIT — change the source and re-run."


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
class Agent:
    def __init__(self, path: Path):
        self.path = path
        self.rel = path.relative_to(REPO).as_posix()
        self.group = path.parent.name if path.parent != AGENTS_DIR else "core"
        text = path.read_text(encoding="utf-8")
        self.frontmatter, self.body = _split_frontmatter(text)
        self.name = self.frontmatter.get("name", path.stem).strip()
        self.description = self.frontmatter.get("description", "").strip()
        raw_tools = self.frontmatter.get("tools", "")
        self.source_tools = [t.strip() for t in raw_tools.split(",") if t.strip()]
        self.model = self.frontmatter.get("model", "").strip()

    @property
    def portable_tools(self) -> list[str]:
        out: list[str] = []
        for t in self.source_tools:
            mapped = PORTABLE_TOOLS.get(t)
            if mapped and mapped not in out:
                out.append(mapped)
        return out

    @property
    def read_only(self) -> bool:
        return not any(t in MUTATE_TOOLS for t in self.source_tools)


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Parse a leading --- YAML-ish block (single-line key: value pairs)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    fm: dict[str, str] = {}
    i = 1
    while i < len(lines) and lines[i].strip() != "---":
        line = lines[i]
        if ":" in line:
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip()
        i += 1
    body = "\n".join(lines[i + 1:]).lstrip("\n")
    return fm, body


def load_agents() -> list[Agent]:
    agents = [Agent(p) for p in sorted(AGENTS_DIR.rglob("*.md"))]
    return [a for a in agents if a.name]


# --------------------------------------------------------------------------- #
# Renderers  (each returns {relative_path: content})
# --------------------------------------------------------------------------- #
def render_cursor(agents: list[Agent]) -> dict[str, str]:
    out = {}
    for a in agents:
        meta = f"> **Source of truth:** `{a.rel}` · **Read-only role:** {'yes' if a.read_only else 'no'}"
        if a.source_tools:
            meta += f" · **Source tools:** {', '.join(a.source_tools)}"
        content = (
            "---\n"
            f"name: {a.name}\n"
            f"description: {a.description}\n"
            "---\n"
            f"<!-- {GEN_NOTE.format(src=a.rel)} -->\n"
            f"{meta}\n\n"
            f"{a.body.rstrip()}\n"
        )
        out[f".cursor/agents/{a.name}.md"] = content
    return out


def render_codex(agents: list[Agent]) -> dict[str, str]:
    out = {}
    for a in agents:
        tools = a.portable_tools
        tools_line = ("[" + ", ".join(f'"{t}"' for t in tools) + "]") if tools else "[]"
        # TOML triple-quoted instructions; escape backslashes and any triple quotes.
        body = a.body.rstrip().replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
        content = (
            f"# {GEN_NOTE.format(src=a.rel)}\n"
            f'name = "{a.name}"\n'
            f'description = {json.dumps(a.description, ensure_ascii=False)}\n'
            f"read_only = {'true' if a.read_only else 'false'}\n"
            f"tools = {tools_line}\n"
            f'instructions = """\n{body}\n"""\n'
        )
        out[f".codex/agents/{a.name}.toml"] = content
    return out


_ABBR = {"vs", "etc", "eg", "ie", "inc", "ltd", "no"}


def _first_sentence(desc: str) -> str:
    """First sentence, not fooled by abbreviations like 'build vs.'."""
    parts = desc.split(". ")
    out = parts[0]
    idx = 1
    while idx < len(parts):
        tail = out.rstrip().split()[-1].rstrip(".").lower() if out.strip() else ""
        if tail in _ABBR or len(out) < 25:
            out += ". " + parts[idx]
            idx += 1
        else:
            break
    return out.rstrip(".")


def render_roster_block(agents: list[Agent]) -> str:
    groups: dict[str, list[Agent]] = {}
    for a in agents:
        groups.setdefault(a.group, []).append(a)
    order = ["office", "dev", "core"] + [g for g in sorted(groups) if g not in ("office", "dev", "core")]
    titles = {"office": "AI Office team — `.claude/agents/office/`",
              "dev": "Dev team — `.claude/agents/dev/`",
              "core": "Core / cross-cutting — `.claude/agents/`"}
    lines = [ROSTER_BEGIN,
             f"<!-- {len(agents)} agents. Regenerate with: python scripts/sync-tool-configs.py -->",
             ""]
    for g in order:
        if g not in groups:
            continue
        lines.append(f"### {titles.get(g, g)}")
        for a in sorted(groups[g], key=lambda x: x.name):
            ro = " _(read-only)_" if a.read_only else ""
            lines.append(f"- **`{a.name}`**{ro} — {_first_sentence(a.description)}.")
        lines.append("")
    lines.append(ROSTER_END)
    return "\n".join(lines)


def apply_roster(current: str, block: str) -> str:
    if ROSTER_BEGIN in current and ROSTER_END in current:
        pre = current.split(ROSTER_BEGIN)[0]
        post = current.split(ROSTER_END, 1)[1]
        return pre + block + post
    return current  # no markers -> leave AGENTS.md untouched


# --------------------------------------------------------------------------- #
# Sync engine
# --------------------------------------------------------------------------- #
def compute_targets(agents: list[Agent]) -> dict[str, str]:
    targets: dict[str, str] = {}
    targets.update(render_cursor(agents))
    targets.update(render_codex(agents))
    if AGENTS_MD.exists():
        new_md = apply_roster(AGENTS_MD.read_text(encoding="utf-8"), render_roster_block(agents))
        targets["AGENTS.md"] = new_md
    return targets


def managed_existing() -> set[str]:
    found = set()
    for d, ext in ((CURSOR_AGENTS, "*.md"), (CODEX_AGENTS, "*.toml")):
        if d.exists():
            for p in d.glob(ext):
                found.add(p.relative_to(REPO).as_posix())
    return found


def sync(check: bool, quiet: bool) -> int:
    agents = load_agents()
    targets = compute_targets(agents)

    stale, created, deleted = [], [], []

    # Files that should exist and match.
    for rel, content in targets.items():
        p = REPO / rel
        old = p.read_text(encoding="utf-8") if p.exists() else None
        if old != content:
            (stale if old is not None else created).append(rel)
            if not check:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")

    # Generated agent files whose source agent no longer exists.
    want = set(targets)
    for rel in managed_existing():
        if rel not in want:
            deleted.append(rel)
            if not check:
                (REPO / rel).unlink()

    changed = stale + created + deleted
    if check:
        if changed:
            print("OUT OF SYNC — run: python scripts/sync-tool-configs.py", file=sys.stderr)
            for rel in sorted(changed):
                print(f"  stale: {rel}", file=sys.stderr)
            return 1
        if not quiet:
            print(f"In sync: {len(agents)} agents across cursor + codex + roster.")
        return 0

    if not quiet:
        print(f"Synced {len(agents)} agents -> "
              f"{len(render_cursor(agents))} cursor, {len(render_codex(agents))} codex, AGENTS.md roster.")
        for label, items in (("updated", stale), ("created", created), ("removed", deleted)):
            for rel in sorted(items):
                print(f"  {label}: {rel}")
    return 0


def hook_mode() -> int:
    """Regenerate only when a source file changed. Never fail the parent call."""
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return sync(check=False, quiet=True)  # can't parse -> safe full regen
    path = ""
    for key in ("tool_input", "toolInput", "params"):
        ti = payload.get(key) or {}
        if isinstance(ti, dict):
            path = ti.get("file_path") or ti.get("path") or path
    path = (path or "").replace("\\", "/")
    source_touched = (
        "/.claude/agents/" in path
        or "/.claude/skills/" in path
        or path.endswith(".claude/CLAUDE.md")
        or path.endswith("/CLAUDE.md")
    )
    if not source_touched:
        return 0
    try:
        return sync(check=False, quiet=True)
    except Exception as e:  # a hook must never break the user's edit
        print(f"sync-tool-configs (hook) skipped: {e}", file=sys.stderr)
        return 0


def main() -> int:
    args = set(sys.argv[1:])
    quiet = "--quiet" in args
    if "--hook" in args:
        return hook_mode()
    return sync(check="--check" in args, quiet=quiet)


if __name__ == "__main__":
    raise SystemExit(main())
