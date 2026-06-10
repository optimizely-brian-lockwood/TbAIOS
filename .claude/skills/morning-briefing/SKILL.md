---
name: morning-briefing
description: Harvest Microsoft Teams messages from the last 24 hours, synthesize a prioritized morning briefing, save to file, and push-notify the user. Triggers on "morning briefing", "catch me up", "overnight summary", "what did I miss", "teams briefing", "daily digest", or any request for a consolidated Teams summary.
---

## What this skill does

Pulls all Teams messages the configured user was involved in over the last 24 hours,
categorizes them by urgency, and produces a morning briefing. Output is:

1. Written to `reports/morning-briefing-{YYYY-MM-DD}.md`
2. Displayed in conversation (when interactive)
3. Push notification sent (when running as a scheduled agent)

## Prerequisites

1. **Corporate auth must be configured.** Check for `~/.claude-corporate/.credentials.json`. If missing:
   > Run `bash scripts/setup-corporate-auth.sh` to set up corporate auth first.

2. **User profile must be configured.** This skill reads `context/human-team.md` to get:
   - The primary user's full name
   - The user's direct reports (for coverage in searches)
   - Active initiatives to prioritize
   - The corporate email address (set in root `CLAUDE.md`)

   If this file doesn't exist or doesn't list these fields, prompt the user to fill them in.

## Performance budget

This skill targets **under 5 minutes** end-to-end. The primary cost is MCP round-trips to
Microsoft Graph (30-60s each). The skill uses **3 parallel subprocess calls** with **2 MCP
searches each** (6 total). Subprocess prompts request **compact output** (sender, timestamp,
1-line summary) not full message bodies.

| Component | Target |
|-----------|--------|
| Subprocess calls | 3 parallel |
| MCP searches per call | 2 |
| Token return per call | ~2K (compact) |
| Wall-clock time | 3–5 min |

## Execution

### Step 1: Load user context

Read `context/human-team.md` to identify:
- **Primary user:** Full name and corporate email (also in root `CLAUDE.md`)
- **Direct reports:** Names for search coverage
- **Active initiatives:** Context for thread categorization

Divide the direct reports list into two halves — one for Call B, one for Call C. If fewer
than 4 direct reports, use 2 per call; if fewer than 2, combine into Call B and leave Call C
focused on initiative channels.

If `context/human-team.md` is not populated, tell the user:
> `context/human-team.md` is not configured. Please add the primary user, their direct reports,
> and active initiatives before running `/morning-briefing`.

### Step 2: Harvest Teams messages (3 parallel subprocess calls)

Run **three Bash calls in parallel** (not sequentially). Each subprocess runs a focused,
constrained search and returns **compact output**.

**CRITICAL: Run all three Bash calls in a single message so they execute concurrently.**

**CRITICAL: Use `CLAUDE_CONFIG_DIR="$HOME/.claude-corporate"` and unset the Vertex env vars.**

Substitute `{PRIMARY_USER_FIRST}` and `{PRIMARY_USER_LAST}` with the user's actual name
from the context loaded in Step 1. Substitute `{DIRECT_REPORT_1}`, `{DIRECT_REPORT_2}`, etc.
with the actual names.

#### Call A — Primary user's direct messages and mentions (highest priority)

```bash
CLAUDE_CODE_USE_VERTEX="" \
ANTHROPIC_VERTEX_PROJECT_ID="" \
CLAUDE_CONFIG_DIR="$HOME/.claude-corporate" \
claude -p "Use the mcp__claude_ai_Microsoft_365__chat_message_search tool to run exactly TWO searches, no more:

Search 1: Search for '{PRIMARY_USER_FIRST} {PRIMARY_USER_LAST}' in messages from the last 24 hours.
Search 2: Search for '{PRIMARY_USER_FIRST}' in messages from the last 24 hours.

For each message found, return ONLY this compact format — one line per message:
TIMESTAMP | SENDER | CHAT_NAME | ONE_LINE_SUMMARY | LINK

Where ONE_LINE_SUMMARY is your 10-15 word summary of the message content — do NOT return the full message body.
LINK is the webUrl or deeplink URL from the message metadata. If no link is available, use 'NO_LINK'.

Group by chat/thread. Deduplicate across the two searches. Do NOT run additional searches beyond these two." \
  --model sonnet \
  --print \
  --no-session-persistence \
  --dangerously-skip-permissions
```

#### Call B — First half of direct reports

```bash
CLAUDE_CODE_USE_VERTEX="" \
ANTHROPIC_VERTEX_PROJECT_ID="" \
CLAUDE_CONFIG_DIR="$HOME/.claude-corporate" \
claude -p "Use the mcp__claude_ai_Microsoft_365__chat_message_search tool to run exactly TWO searches, no more:

Search 1: Search for '{DIRECT_REPORT_1}' in messages from the last 24 hours.
Search 2: Search for '{DIRECT_REPORT_2}' in messages from the last 24 hours.

For each message found, return ONLY this compact format — one line per message:
TIMESTAMP | SENDER | CHAT_NAME | ONE_LINE_SUMMARY | LINK

Where ONE_LINE_SUMMARY is your 10-15 word summary of the message content — do NOT return the full message body.
LINK is the webUrl or deeplink URL from the message metadata. If no link is available, use 'NO_LINK'.

Group by chat/thread. Deduplicate across the two searches. Skip any messages where {PRIMARY_USER_FIRST} {PRIMARY_USER_LAST} is the sender — those are captured by another search. Do NOT run additional searches beyond these two." \
  --model sonnet \
  --print \
  --no-session-persistence \
  --dangerously-skip-permissions
```

#### Call C — Second half of direct reports / org activity

```bash
CLAUDE_CODE_USE_VERTEX="" \
ANTHROPIC_VERTEX_PROJECT_ID="" \
CLAUDE_CONFIG_DIR="$HOME/.claude-corporate" \
claude -p "Use the mcp__claude_ai_Microsoft_365__chat_message_search tool to run exactly TWO searches, no more:

Search 1: Search for '{DIRECT_REPORT_3}' in messages from the last 24 hours.
Search 2: Search for '{DIRECT_REPORT_4}' in messages from the last 24 hours.

For each message found, return ONLY this compact format — one line per message:
TIMESTAMP | SENDER | CHAT_NAME | ONE_LINE_SUMMARY | LINK

Where ONE_LINE_SUMMARY is your 10-15 word summary of the message content — do NOT return the full message body.
LINK is the webUrl or deeplink URL from the message metadata. If no link is available, use 'NO_LINK'.

Group by chat/thread. Deduplicate across the two searches. Skip any messages where {PRIMARY_USER_FIRST} {PRIMARY_USER_LAST} is the sender — those are captured by another search. Do NOT run additional searches beyond these two." \
  --model sonnet \
  --print \
  --no-session-persistence \
  --dangerously-skip-permissions
```

**Timeout:** 180 seconds per call. If one times out, continue with the other two — partial data
is better than no briefing.

**DO NOT use the Agent tool for harvesting.** The Agent tool spawns a corp-data-agent that
runs its own search strategy (fan-out, 13+ queries). Instead, run the three Bash calls directly
— this gives you control over exactly how many MCP searches execute.

### Step 3: Categorize and synthesize

Merge the results from all three calls. Deduplicate threads that appear in multiple searches
(same chat name + similar timestamp = same thread).

Sort every message thread into exactly one of three buckets:

#### Bucket 1: Needs Your Response
Threads where:
- The primary user was directly @mentioned or asked a question
- Someone is waiting on the user's input, approval, or decision
- A direct report sent the user a DM requesting something
- A commitment the user made has a follow-up due

Format each item with: **what** needs doing (linked to the thread), **who** is waiting,
**context** (1-2 sentences), **action** in bold.

#### Bucket 2: Active Threads (Stay Close)
Threads where:
- The user is an active participant but no immediate action is required
- Decisions are being made in spaces the user contributes to
- Work is in progress on the user's active initiatives
- Someone on the user's team is driving something the user should track

Format each item with: **thread name** (linked), **key participants**, **what's happening**,
**why it matters**.

#### Bucket 3: Noteworthy (No Action)
Threads where:
- Company wins, celebrations, announcements
- Org-wide updates the user should know about
- Activity in channels the user belongs to but doesn't need to act on
- FYI items that provide useful context

Format each item with: **headline** (linked if available) and **1-sentence summary**.

### Step 4: Assemble the briefing

```markdown
# Morning Briefing — {today's date, e.g. May 15, 2026}

**Messages scanned:** {count} across {channel_count} chats
**Source:** Corporate Teams ({corporate email from CLAUDE.md})
**Generated:** {timestamp}

---

## Needs Your Response

**1. [{Title}]({teams_link}) — {Person}**
{Context in 1-2 sentences.} **Action: {what to do}.**

{...repeat for each item...}

---

## Active Threads (Stay Close)

**{N}. [{Thread name}]({teams_link})**
{Key participants}. {What's happening and why it matters.}

{...repeat...}

---

## Noteworthy (No Action)

**{N}. [{Headline}]({teams_link})**
{One-sentence summary.}

{...repeat...}
```

### Step 5: Save and notify

1. **Write the briefing** to `reports/morning-briefing-{YYYY-MM-DD}.md`
2. **Send a push notification** (use PushNotification tool):
   > "Morning briefing ready — {X} items need response, {Y} active threads."
3. **Display the briefing** in conversation if interactive.

### Step 6: Cleanup (optional)

If more than 14 briefing files exist in `reports/`, delete the oldest ones beyond 14 to
prevent unbounded growth.

## Categorization heuristics

| Signal | Bucket |
|--------|--------|
| User was asked a direct question | Needs Response |
| DM from a direct report with a request | Needs Response |
| "Can you..." / "Would you..." / "Please..." directed at user | Needs Response |
| User made a commitment with a deadline | Needs Response |
| User is in the thread and decisions are being made | Active Thread |
| User's direct reports are driving work they should know about | Active Thread |
| Active initiative the user contributes to | Active Thread |
| Company announcement, win, celebration | Noteworthy |
| Channel-wide FYI with no action for user | Noteworthy |

## Critical rules

1. **All Teams data access goes through the corporate subprocess.** Never access Teams directly.
2. **Always use Sonnet** for the subprocess. Never Opus.
3. **Always unset Vertex env vars** in subprocess commands.
4. **Subprocess prompts must be self-contained** — include actual names, not placeholders.
5. **Don't invent action items.** Only surface items clearly stated or strongly implied.
6. **Don't editorialize.** Report what was said, not what the user should think about it.
7. **Keep it scannable.** The whole briefing should take <3 minutes to read.
8. **Label the source** on every output.
9. **Push notification under 200 chars.** Lead with counts, not prose.
10. **No duplicate items.** If the same topic appears in multiple threads, consolidate into
    the highest-priority bucket.
11. **Exactly 6 MCP searches total.** Do not fan out beyond the 3×2 pattern.
12. **Run all 3 Bash calls in a single message.** Parallelism is the primary speed lever.
13. **Compact output only.** Subprocess prompts request 1-line summaries, never full bodies.
14. **Do NOT use the Agent tool for harvesting.** Direct Bash calls give you control over search
    count. The Agent tool spawns a corp-data-agent with its own unbounded search strategy.
15. **Thread links required.** Every briefing item must include a clickable Teams link when
    available. Use the webUrl/deeplink from the message metadata. If no link was returned,
    use plain text instead.

## Configuration template

Add this block to `context/human-team.md` for the primary user of this skill:

```markdown
## Morning Briefing Configuration

**Primary user:** {First Last}
**Corporate email:** {email}
**Direct reports:**
- {Name 1}
- {Name 2}
- {Name 3}
- {Name 4}

**Active initiatives to prioritize:**
- {Initiative 1}
- {Initiative 2}
```
