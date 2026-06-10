# Initiative Registry

This is the master index of all initiatives managed by this AI OS instance.
Each initiative has its own entry and records structure. Initiatives must never be blended.

---

## Active initiatives

| ID | Name | Status | Records path | Phase |
|---|---|---|---|---|
| *(Add initiatives here as they are onboarded)* | | | | |

---

## Initiative onboarding

To onboard a new initiative:

1. Copy `initiatives/_template/` to `initiatives/[id]-[name]/`
2. Fill in `initiative-brief.md` with the initiative definition
3. Add an entry to this registry table
4. Add an entry to the initiative registry in root `CLAUDE.md`
5. Create the records structure: `mkdir -p docs/records/{program,pending,waves,milestones,inputs,data,reference}`
6. Run `/challenge-me` on the initiative brief before the first discovery session

---

## Closed initiatives

| ID | Name | Closed date | Outcome |
|---|---|---|---|
| *(Moved here when an initiative completes or is cancelled)* | | | |
