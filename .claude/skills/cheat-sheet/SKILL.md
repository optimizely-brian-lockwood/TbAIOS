---
name: cheat-sheet
description: "Display the three-system reference card — AI OS vs. Action tracker vs. External systems, what goes in each, and how external systems connect to the OS. Triggers on \"/cheat-sheet\", \"show cheat sheet\", \"three systems\", \"what goes where\"."
---

Display the following reference card verbatim:

---

### Three-system cheat sheet

| System | Job | Answers the question |
|--------|-----|----------------------|
| **AI OS** (this repo) | Knowledge & memory | *What was decided? Why? What did we learn?* |
| **Action tracker** (e.g., ClickUp / Jira / Asana) | Action & accountability | *Who does what? By when? What's blocked?* |
| **External systems** (CRM / collaboration / docs / etc.) | Corporate source of truth | *What is the current state of our systems, people, and customers?* |

**AI OS — what goes in:** Decisions with rationale, risks with mitigation, stakeholder intelligence, progress items, raw source inputs, wave analysis artifacts, distribution artifacts.  
**AI OS — what does NOT go in:** Task assignment or deadline tracking (→ action tracker), live system data (→ `/corp-data`), original source documents (→ stay in their system, referenced here).

**Action tracker — what goes in:** Human-led action items with owners and due dates, agentic team deliverables with status, mandate asks with deadlines, cross-initiative operational tasks.  
**Action tracker — what does NOT go in:** Decision rationale or evidence (→ OS decision log), stakeholder intelligence (→ OS stakeholder map), historical record (→ OS inputs).

**How external systems connect to the OS:**

| System type | What it holds | How it enters the OS |
|-------------|--------------|----------------------|
| Document storage (e.g., SharePoint / Google Drive / Confluence) | Corporate docs, strategy decks, org charts | Referenced in input records; key decisions extracted via `/ingest` |
| Collaboration platform (e.g., Teams / Slack) | Meeting chats, async decisions, stakeholder signals | Harvested via `/morning-briefing` or `/corp-data`; key content ingested |
| CRM (e.g., Salesforce / HubSpot) | Customer data, pipeline, account health | Referenced in analysis; excerpts ingested when evidence-grade |
| Customer success platform (e.g., Gainsight / Totango) | Health scores, engagement signals | Referenced in analysis; raw data stays in platform |
| Support platform (e.g., Zendesk / Intercom) | Ticket analysis, support trends | Analysis output ingested; raw tickets stay in platform |
