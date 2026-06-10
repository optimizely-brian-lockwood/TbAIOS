---
name: corp-data
description: Corporate data conduit. Routes requests for company data (Microsoft Teams, SharePoint, Outlook, Salesforce) through a Claude CLI subprocess authenticated with the corporate Anthropic account. Use when any agent needs data from corporate platforms. Triggers on "get from Teams", "check SharePoint", "look up in Salesforce", "corporate data", "company data".
---

## What this skill does

Spawns a Claude CLI subprocess authenticated with the corporate Anthropic account to handle
requests that require access to corporate platforms — Microsoft Teams, Outlook, SharePoint,
OneDrive, Salesforce, etc.

**Architecture:**
- This Claude Code session runs on the personal account / Vertex AI.
- Corporate data requests spawn a separate `claude -p` subprocess using
  `CLAUDE_CONFIG_DIR=~/.claude-corporate` with the corporate Claude AI OAuth credentials.
- The subprocess always uses **Sonnet** model to conserve corporate plan tokens.
- Vertex AI env vars are explicitly unset in the subprocess so it uses Claude AI auth.

**Configuration:** Each user sets their own corporate email in a `.env` file (gitignored).
The email is never committed to the repo — it belongs to the individual, not the project.

## Prerequisites

**1. Set your corporate email.** If `.env` doesn't exist yet, copy the template:
```
cp .env.example .env
```
Then edit `.env` and set `CORPORATE_EMAIL=you@yourcompany.com`.

**2. Authenticate once.** If `~/.claude-corporate/.credentials.json` doesn't exist:
```
bash scripts/setup-corporate-auth.sh
```
This reads your email from `.env` and opens a browser to authenticate.

**Reading CORPORATE_EMAIL at runtime:** Before executing a subprocess call, read the value
from `.env` if it isn't already in the environment:

```bash
# Bash (macOS / Linux / Git Bash)
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi
# CORPORATE_EMAIL is now available as $CORPORATE_EMAIL

# PowerShell (Windows)
if (Test-Path .env) {
  Get-Content .env | Where-Object { $_ -notmatch '^#' -and $_ -match '=' } |
    ForEach-Object { $k,$v = $_ -split '=',2; [System.Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim()) }
}
# CORPORATE_EMAIL is now available as $env:CORPORATE_EMAIL
```

If `CORPORATE_EMAIL` is empty after this step, tell the user:
> Add `CORPORATE_EMAIL=you@yourcompany.com` to your `.env` file (copy `.env.example` to get started).

## Execution

### Step 1: Classify the request

Determine:
1. **Which service** is needed (Teams, Outlook, SharePoint, OneDrive, Salesforce)
2. **What data** is needed (specific message, search, document, summary, etc.)
3. **Output format** the caller needs (list, table, full content, summary)

If the request is ambiguous, ask ONE clarifying question.

### Step 2: Build the prompt

Write a self-contained prompt for the corporate subprocess. The subprocess has NO context
from this conversation — the prompt must include everything needed. Be specific about:
- **Which MCP tool to use** — name it explicitly. Without this, the subprocess may narrate
  what it *would* do instead of calling the tool. See the tool reference table below.
- What to search for or retrieve
- Date ranges, filters, keywords
- Desired output format and level of detail
- Any constraints (e.g., "only from #general channel", "last 7 days")

**MCP tool reference (name the tool in your prompt):**

| Need | MCP tool name |
|------|---------------|
| Teams messages / chats | `mcp__claude_ai_Microsoft_365__chat_message_search` |
| Outlook emails | `mcp__claude_ai_Microsoft_365__outlook_email_search` |
| Outlook calendar | `mcp__claude_ai_Microsoft_365__outlook_calendar_search` |
| Meeting availability | `mcp__claude_ai_Microsoft_365__find_meeting_availability` |
| SharePoint search | `mcp__claude_ai_Microsoft_365__sharepoint_search` |
| SharePoint folders | `mcp__claude_ai_Microsoft_365__sharepoint_folder_search` |
| Read a specific resource | `mcp__claude_ai_Microsoft_365__read_resource` |
| Jira issues (JQL) | `mcp__claude_ai_Atlassian__searchJiraIssuesUsingJql` |
| Jira issue details | `mcp__claude_ai_Atlassian__getJiraIssue` |
| Confluence pages | `mcp__claude_ai_Atlassian__searchConfluenceUsingCql` |

### Step 3: Execute via corporate CLI

```bash
CLAUDE_CODE_USE_VERTEX="" \
ANTHROPIC_VERTEX_PROJECT_ID="" \
CLAUDE_CONFIG_DIR="$HOME/.claude-corporate" \
claude -p "<the prompt>" \
  --model sonnet \
  --print \
  --no-session-persistence \
  --dangerously-skip-permissions
```

**Flags explained:**
- `--model sonnet` — conserves corporate plan tokens
- `--print` / `-p` — non-interactive, returns output and exits
- `--no-session-persistence` — don't save the corporate session to disk
- `--dangerously-skip-permissions` — **required** because the subprocess runs
  non-interactively and cannot prompt for MCP tool approvals
- Unsetting Vertex env vars ensures Claude AI auth is used, not Vertex

**Timeout:** 180 seconds per call. MCP tool round-trips can take 30–60 seconds each.

### Step 4: Process and return

1. Parse the subprocess output
2. Extract the relevant data
3. Format it for the caller (user or invoking agent)
4. If the subprocess returned an error or no data, report what happened and suggest alternatives

## When invoked by other agents

Other agents call the corporate conduit via `Agent(subagent_type='corp-data-agent')`.
The agent wraps this same flow. See `.claude/agents/corp-data-agent.md`.

## Critical rules

1. **Every corporate request goes through the subprocess.** Never access corporate APIs
   from the current session.
2. **Always use Sonnet.** Never override the model to Opus or another model.
3. **Never persist corporate data to project files** unless the user explicitly asks.
4. **Always unset Vertex env vars** in the subprocess command.
5. **Prompts must be self-contained.** The subprocess has zero context from this conversation.
6. **Label the source.** When presenting results, note the data came from the corporate account.
7. **Minimize round-trips.** Batch related requests into a single subprocess call when possible.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Returns guidance text instead of data | Missing `--dangerously-skip-permissions` | Add the flag |
| Narrates but doesn't call tools | Prompt didn't name the specific MCP tool | Rewrite prompt with explicit tool name |
| "not logged in" error | Corporate config not set up | Run setup script |
| Auth shows "vertex" | Vertex env vars not unset | Check unset commands in Bash call |
| Token/rate limit errors | Corporate plan limits | Wait and retry, or reduce query scope |
| "no tools available" | M365 connector not enabled | Check corporate plan's connector settings |
| Timeout | Query too broad | Narrow scope and retry; ensure 180s timeout is set |
