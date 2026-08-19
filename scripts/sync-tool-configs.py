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

Bidirectional:
  Forward  (.claude/agents/ -> tools):  the default. Generated files carry an
           AUTO-GENERATED marker; only marker-bearing files are ever overwritten
           or deleted, so a file hand-authored inside a tool is never clobbered.
  Reverse  (tool -> .claude/agents/):   --import. A tool agent file WITHOUT the
           marker was authored in that tool; --import pulls it into
           .claude/agents/imported/ (the source of truth), deletes the tool copy,
           and forward-syncs so the agent then exists in every tool.

Modes:
  (no args)        Regenerate everything, print a summary of what changed.
  --check          Verify sync in BOTH directions. Exit 1 if forward-stale OR if
                   importable (tool-authored) agents exist. Writes nothing.
  --import         Pull tool-authored agents into .claude/, then forward-sync.
                   Name collisions with existing source agents are reported, never
                   overwritten.
  --hook           Hook mode: reads the tool-call JSON on stdin. If the edited
                   file is a source file (.claude/agents|skills, CLAUDE.md,
                   AGENTS.md structure), regenerate quietly; otherwise no-op.
                   Never fails the parent tool call. (Forward only — import is
                   deliberate, never automatic.)
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
# Any generated file contains this marker. A tool agent file WITHOUT it was
# hand-authored in that tool and is an import candidate — never overwritten.
GEN_MARKER = "AUTO-GENERATED from"
# Reverse import: tool tool-names -> Claude Code tool-names.
REVERSE_TOOLS = {"Read": "Read", "Write": "Write", "Edit": "Edit", "Glob": "Glob",
                 "Grep": "Grep", "Bash": "Bash", "WebSearch": "WebSearch", "WebFetch": "WebFetch"}
# Default toolset for an imported agent when the source tool gave none.
IMPORT_DEFAULT_TOOLS = "Read, Glob, Grep, Write, Edit, Bash"
IMPORTED_DIR = AGENTS_DIR / "imported"


def _is_generated(path: Path) -> bool:
    try:
        return GEN_MARKER in path.read_text(encoding="utf-8")[:1500]
    except Exception:
        return False


def _tool_agent_files() -> list[Path]:
    files: list[Path] = []
    for d, ext in ((CURSOR_AGENTS, "*.md"), (CODEX_AGENTS, "*.toml")):
        if d.exists():
            files.extend(sorted(d.glob(ext)))
    return files


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


def _unmanaged_tool_files() -> list[str]:
    """Tool agent files that were hand-authored in the tool (no generated marker)."""
    return [p.relative_to(REPO).as_posix() for p in _tool_agent_files() if not _is_generated(p)]


def sync(check: bool, quiet: bool) -> int:
    agents = load_agents()
    targets = compute_targets(agents)
    want = set(targets)

    stale, created, deleted, unmanaged = [], [], [], []

    # Write generated targets. NEVER clobber a foreign (hand-authored) tool file.
    for rel, content in targets.items():
        p = REPO / rel
        is_tool_agent = rel.startswith(".cursor/agents/") or rel.startswith(".codex/agents/")
        if is_tool_agent and p.exists() and not _is_generated(p):
            unmanaged.append(rel)   # someone authored this in-tool — import it, don't overwrite
            continue
        old = p.read_text(encoding="utf-8") if p.exists() else None
        if old != content:
            (stale if old is not None else created).append(rel)
            if not check:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")

    # Tool files we don't want: delete only if WE generated them; else flag for import.
    for p in _tool_agent_files():
        rel = p.relative_to(REPO).as_posix()
        if rel in want:
            continue
        if _is_generated(p):
            deleted.append(rel)          # source agent was removed -> retire the generated peer
            if not check:
                p.unlink()
        elif rel not in unmanaged:
            unmanaged.append(rel)

    changed = stale + created + deleted
    if check:
        rc = 0
        if changed:
            print("OUT OF SYNC (forward) — run: python scripts/sync-tool-configs.py", file=sys.stderr)
            for rel in sorted(changed):
                print(f"  stale: {rel}", file=sys.stderr)
            rc = 1
        if unmanaged:
            print("IMPORTABLE (reverse) — tool-authored agents not in .claude/; "
                  "run: python scripts/sync-tool-configs.py --import", file=sys.stderr)
            for rel in sorted(unmanaged):
                print(f"  unmanaged: {rel}", file=sys.stderr)
            rc = 1
        if rc == 0 and not quiet:
            print(f"In sync: {len(agents)} agents across cursor + codex + roster.")
        return rc

    if not quiet:
        print(f"Synced {len(agents)} agents -> "
              f"{len(render_cursor(agents))} cursor, {len(render_codex(agents))} codex, AGENTS.md roster.")
        for label, items in (("updated", stale), ("created", created), ("removed", deleted)):
            for rel in sorted(items):
                print(f"  {label}: {rel}")
        for rel in sorted(unmanaged):
            print(f"  IMPORTABLE (run --import): {rel}")
    return 0


# --------------------------------------------------------------------------- #
# Reverse import  (tool-authored agent -> .claude/ source of truth)
# --------------------------------------------------------------------------- #
def _parse_cursor_agent(path: Path):
    fm, body = _split_frontmatter(path.read_text(encoding="utf-8"))
    name = (fm.get("name") or path.stem).strip()
    desc = (fm.get("description") or "").strip()
    tools = fm.get("tools", "").strip()
    return name, desc, tools, body.strip()


def _parse_codex_agent(path: Path):
    import re
    text = path.read_text(encoding="utf-8")
    m_name = re.search(r'(?m)^name\s*=\s*"([^"]*)"', text)
    name = (m_name.group(1) if m_name else path.stem).strip()
    desc = ""
    m_desc = re.search(r'(?m)^description\s*=\s*(.+)$', text)
    if m_desc:
        try:
            desc = json.loads(m_desc.group(1).strip())
        except Exception:
            desc = m_desc.group(1).strip().strip('"')
    tools = ""
    m_tools = re.search(r'(?m)^tools\s*=\s*(\[[^\]]*\])', text)
    if m_tools:
        try:
            tools = ", ".join(json.loads(m_tools.group(1)))
        except Exception:
            pass
    body = ""
    m_body = re.search(r'instructions\s*=\s*"""\n?(.*?)\n?"""', text, re.S)
    if m_body:
        body = m_body.group(1).replace('\\"\\"\\"', '"""').replace("\\\\", "\\")
    return name, desc, tools, body.strip()


def _map_reverse_tools(tools_csv: str) -> str:
    if not tools_csv:
        return IMPORT_DEFAULT_TOOLS
    mapped = []
    for t in [t.strip() for t in tools_csv.split(",") if t.strip()]:
        m = REVERSE_TOOLS.get(t, t)
        if m not in mapped:
            mapped.append(m)
    return ", ".join(mapped) or IMPORT_DEFAULT_TOOLS


def _render_source_agent(name, desc, tools, body, origin_rel) -> str:
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {desc}\n"
        f"tools: {tools}\n"
        "model: sonnet\n"
        "---\n"
        f"<!-- IMPORTED from {origin_rel} by scripts/sync-tool-configs.py --import. "
        "REVIEW: confirm tools/model, then move this file into office/ or dev/ as appropriate. -->\n\n"
        f"{body}\n"
    )


def import_agents(quiet: bool) -> int:
    existing = {a.name for a in load_agents()}
    imported, conflicts, skipped = [], [], []

    for p in _tool_agent_files():
        if _is_generated(p):
            continue
        rel = p.relative_to(REPO).as_posix()
        if p.suffix == ".md":
            name, desc, tools_csv, body = _parse_cursor_agent(p)
        else:
            name, desc, tools_csv, body = _parse_codex_agent(p)
        if not name or not body:
            skipped.append(rel)
            continue
        if name in existing:
            conflicts.append((name, rel))   # collides with a source agent — human must resolve
            continue
        dest = IMPORTED_DIR / f"{name}.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(_render_source_agent(name, desc, _map_reverse_tools(tools_csv), body, rel),
                        encoding="utf-8")
        p.unlink()   # remove the tool copy; forward sync regenerates it WITH the marker
        existing.add(name)
        imported.append((name, rel, dest.relative_to(REPO).as_posix()))

    # Propagate every newly-imported agent out to all tools.
    sync(check=False, quiet=True)

    if not quiet:
        if imported:
            print(f"Imported {len(imported)} tool-authored agent(s) into .claude/agents/imported/:")
            for name, src, dst in imported:
                print(f"  {src}  ->  {dst}  (now generated for all tools)")
            print("REVIEW each: confirm tools/model, then move into office/ or dev/.")
        if conflicts:
            print("\nSKIPPED — name already exists in .claude/agents/ (resolve by hand):", file=sys.stderr)
            for name, src in conflicts:
                print(f"  {src}  (name '{name}' already a source agent)", file=sys.stderr)
        if skipped:
            print("\nSKIPPED — could not parse a name + body:", file=sys.stderr)
            for src in skipped:
                print(f"  {src}", file=sys.stderr)
        if not (imported or conflicts or skipped):
            print("Nothing to import — no tool-authored agents found.")
    return 1 if conflicts or skipped else 0


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
    if "--import" in args:
        return import_agents(quiet=quiet)
    return sync(check="--check" in args, quiet=quiet)


if __name__ == "__main__":
    raise SystemExit(main())
