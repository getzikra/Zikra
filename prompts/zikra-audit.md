> This prompt is for Claude Code only.
> Run it from any project that has Zikra configured in CLAUDE.md.
> It audits your Zikra instance — it does not modify anything unless you confirm.

# zikra-audit
Audit Zikra memories for project drift, type misclassification, ghost projects,
and emerging-project signals. Outputs a structured findings report with
optional remediation commands.

Follow every step in order. Run all bash commands exactly as shown.
Proceed without asking for confirmation between steps until Step 4.

---

## Configuration

Read these values from the current project or global `CLAUDE.md`:
- `zikra_endpoint` — the Zikra webhook URL (e.g. `http://localhost:8100/webhook/zikra`)
- `zikra_token` — the bearer token (strip the `Bearer ` prefix for curl)
- `## Projects` block — the canonical list of valid project names

If either is missing, check `~/.claude/CLAUDE.md` for a `Webhook:` and `Bearer:` line.
If still not found, ask the user for the values before proceeding.

Store locally for this session:
```bash
ZIKRA_ENDPOINT="<value from CLAUDE.md>"
ZIKRA_TOKEN="<value from CLAUDE.md>"
```

Parse the `## Projects` section into a canonical list. Example:
```
veltisai, forgenexus, zikra, global
```
This list is the ground truth for CHECK 1. Any project name in the DB not on this list is a ghost.

---

## Step 1 — Inventory: get all projects and their memory-type breakdown

Try direct DB access first (most accurate). Fall back to curl if unavailable.

### Path A — Direct DB (preferred)
```bash
# Detect DB container name from docker-compose or docker ps
DB_CONTAINER=$(docker ps --format '{{.Names}}' | grep -E 'postgres|mysql|db' | head -1)
DB_USER=$(grep -r 'DB_USER\|POSTGRES_USER' /opt/docker/compose/ 2>/dev/null | head -1 | cut -d= -f2 | tr -d ' "')
DB_NAME=$(grep -r 'DB_NAME\|POSTGRES_DB' /opt/docker/compose/ 2>/dev/null | head -1 | cut -d= -f2 | tr -d ' "')

docker exec $DB_CONTAINER psql -U $DB_USER -d $DB_NAME -c "
SELECT
  project,
  memory_type,
  COUNT(*)                    AS cnt,
  MAX(created_at)::date       AS newest,
  MIN(created_at)::date       AS oldest
FROM memories
GROUP BY project, memory_type
ORDER BY project, cnt DESC;
"
```

### Path B — Curl fallback
If DB access fails, search each known project with `limit=1` to get totals:
```bash
for PROJECT in $CANONICAL_PROJECTS; do
  TOTAL=$(curl -s -X POST "$ZIKRA_ENDPOINT" \
    -H "Authorization: Bearer $ZIKRA_TOKEN" \
    -H "User-Agent: curl/7.81.0" \
    -H "Content-Type: application/json" \
    -d "{\"command\":\"search\",\"query\":\"status\",\"project\":\"$PROJECT\",\"limit\":1}" \
    | python3 -c "import json,sys; print(json.load(sys.stdin).get('total',0))")
  echo "$PROJECT: $TOTAL"
done
```

Build an inventory table from either path. You will need it for every check below.

---

## Step 2 — Run all audit checks

Work through each check. Record findings as: **[CRITICAL]**, **[WARNING]**, or **[INFO]**.
A check with no findings = PASS — note it as ✓ PASS in the report.

---

### CHECK 1 — Ghost projects
**Signal:** Agent used the wrong project name, or a migration left residual records.

Compare every project name in the DB inventory against the canonical list.
Flag anything not on the list — include the count and newest entry date.

Common causes to call out explicitly:
- Capitalisation drift: `Veltis AI` should be `veltisai`
- Residual from rename: `molten8.ai` after molten8 → forgenexus migration
- Typo: `veltisai_` or `velstisai`
- Entirely new project the agent invented without telling anyone

**Severity:** CRITICAL if count > 0

---

### CHECK 2 — Conversation-type dominance
**Signal:** Agent is using `conversation` as a lazy catch-all instead of the correct type.

For each project compute: `conversation_pct = conversation_count / total * 100`

Flag at:
- `conversation_pct > 60%` → **WARNING** (likely drift)
- `conversation_pct > 85%` → **CRITICAL** (systematic misuse)
- `conversation_count > 200 AND conversation_pct > 80%` → **CRITICAL** (volume confirms it's not intentional)

`conversation` should be the minority type in an active project. If it dominates, recent agent
runs are almost certainly filing things in the wrong bucket.

---

### CHECK 3 — Non-standard memory types
**Signal:** Agent invented a new type name instead of using the canonical set.

Canonical types: `conversation`, `decision`, `prompt`, `diary`, `mockup`, `reference`, `requirement`, `bug`, `knowledge`

Flag any type in the DB inventory not on this list.
For each non-standard type, suggest the closest canonical substitute:

| Non-standard type | Correct type | Reason |
|---|---|---|
| `run_diary` | `diary` | variant name |
| `handoff` | `decision` or `reference` | handoffs are documented outcomes |
| `investigation` | `decision` | set the `resolution` field to capture outcome |
| `memory` | depends on content | meta-confusion — agent saved a memory about memory |
| `note` | `conversation` or `decision` | too vague |
| `session` | `diary` | same concept |

**Severity:** WARNING

---

### CHECK 4 — Cross-project contamination
**Signal:** A memory is filed under project X but its title or content clearly belongs to project Y.

For each project P, search for each other canonical project name Q:
```bash
curl -s -X POST "$ZIKRA_ENDPOINT" \
  -H "Authorization: Bearer $ZIKRA_TOKEN" \
  -H "User-Agent: curl/7.81.0" \
  -H "Content-Type: application/json" \
  -d "{\"command\":\"search\",\"query\":\"$Q\",\"project\":\"$P\",\"limit\":5}" \
  | python3 -c "
import json, sys
data = json.load(sys.stdin)
for r in data.get('results', []):
    print(r['id'], '|', r['memory_type'], '|', r['title'][:80])
    print('  snippet:', r['snippet'][:120])
    print()
"
```

Flag results where:
- The memory title starts with another project's name: `forgenexus: <title>` found in `veltisai`
- The snippet is dominated by another project's terminology (product names, domain names)
- Score >= 0.97 (very high semantic match means the content is strongly about the other project)

**Severity:** WARNING (cross-references can be legitimate), CRITICAL if title pattern makes wrong project obvious

---

### CHECK 5 — Emerging project signals
**Signal:** A new product, domain, or initiative is clustering in recent memories without a formal project entry.

Search for memories created in the last 30 days:
```bash
curl -s -X POST "$ZIKRA_ENDPOINT" \
  -H "Authorization: Bearer $ZIKRA_TOKEN" \
  -H "User-Agent: curl/7.81.0" \
  -H "Content-Type: application/json" \
  -d '{"command":"search","query":"new project launch site domain","project":"global","limit":20}'
```

Also scan each project's recent memories for:
1. `.com`, `.ai`, `.io` domain names not in the canonical project list
2. Title patterns like `[NewName]: ...` or `NewName — ...` appearing 3+ times
3. Repeated proper nouns that aren't known brand names

If a candidate appears in 3 or more recent memories, flag it as a possible new project
that should either get its own project entry or be explicitly assigned to an existing one.

**Severity:** INFO

---

### CHECK 6 — Decision memories without date prefix
**Signal:** Decisions are not following the `YYYYMMDD: <title>` convention — makes audit trail unreliable.

Fetch recent decisions for each project:
```bash
curl -s -X POST "$ZIKRA_ENDPOINT" \
  -H "Authorization: Bearer $ZIKRA_TOKEN" \
  -H "User-Agent: curl/7.81.0" \
  -H "Content-Type: application/json" \
  -d "{\"command\":\"search\",\"query\":\"decision\",\"project\":\"$PROJECT\",\"limit\":50}" \
  | python3 -c "
import json, sys, re
data = json.load(sys.stdin)
date_re = re.compile(r'^20\d{6}:')
for r in data.get('results', []):
    if r['memory_type'] == 'decision' and not date_re.match(r['title']):
        print('MISSING DATE:', r['id'], '|', r['title'][:80])
"
```

**Severity:** WARNING

---

### CHECK 7 — Probable duplicates
**Signal:** Two or more memories in the same project with near-identical titles — agent saved the same thing twice (common on retried runs).

From the DB inventory, look for titles where:
- The `YYYYMMDD:` prefix matches AND the remaining title is within 10 characters (edit distance)
- Or the entire title is an exact match

If DB access is available:
```bash
docker exec $DB_CONTAINER psql -U $DB_USER -d $DB_NAME -c "
SELECT a.id, b.id, a.project, a.title, b.title
FROM memories a
JOIN memories b ON a.project = b.project
  AND a.id < b.id
  AND a.memory_type = b.memory_type
  AND (
    a.title = b.title
    OR (LEFT(a.title, 8) = LEFT(b.title, 8) AND LEFT(a.title, 8) ~ '^20[0-9]{6}')
  )
ORDER BY a.project, a.title;
"
```

**Severity:** WARNING

---

### CHECK 8 — Search index drift
**Signal:** The vector search index is out of sync with the DB row count (stale embeddings → degraded search).

For each project, compare:
- DB count: from the Step 1 inventory
- Search total: from the `total` field in any search response

```bash
curl -s -X POST "$ZIKRA_ENDPOINT" \
  -H "Authorization: Bearer $ZIKRA_TOKEN" \
  -H "User-Agent: curl/7.81.0" \
  -H "Content-Type: application/json" \
  -d "{\"command\":\"search\",\"query\":\"recent\",\"project\":\"$PROJECT\",\"limit\":1}" \
  | python3 -c "import json,sys; print(json.load(sys.stdin).get('total',0))"
```

Flag if `abs(search_total - db_count) / db_count > 0.10` (>10% drift).

**Severity:** WARNING

---

## Step 3 — Output the report

Print the full report in this structure:

```
╔══════════════════════════════════════════════════════════════╗
║  ZIKRA MEMORY AUDIT — <YYYY-MM-DD> — <endpoint hostname>    ║
╚══════════════════════════════════════════════════════════════╝

INVENTORY
  <project>   <total> memories   types: <type(count) …>   newest: <date>
  …

──────────────────────────────────────────────────────────────
FINDINGS
──────────────────────────────────────────────────────────────

[CRITICAL] CHECK 1 — Ghost projects
  <project_name>   <count> memories   newest: <date>   → should be: <canonical_name>

[CRITICAL] CHECK 2 — Conversation-type dominance
  <project>   <count>/<total> = <pct>%   (threshold: 85%)

[WARNING]  CHECK 3 — Non-standard memory types
  <project>: <type>(<count>) → should be '<canonical_type>'

[WARNING]  CHECK 4 — Cross-project contamination
  <id> in <project> references <other_project>: <title>

[INFO]     CHECK 5 — Emerging project signals
  '<candidate_name>' appears in <n> recent memories — consider formalising as a project

[WARNING]  CHECK 6 — Decisions without date prefix
  <id> | <title>

[WARNING]  CHECK 7 — Probable duplicates
  <id_a> ≈ <id_b> | <title>

[INFO]     CHECK 8 — Index drift
  <project>: search=<n> db=<n> drift=<pct>%

──────────────────────────────────────────────────────────────
SUMMARY
  Critical: <n>   Warning: <n>   Info: <n>
  Action required: YES / NO
──────────────────────────────────────────────────────────────
```

If a check finds nothing, print `  ✓ PASS` on one line and move on.

---

## Step 4 — Remediation (interactive — do not auto-run)

If any CRITICAL findings exist, print the remediation commands and ask:
> "Run these fixes? Reply y (this one), n (skip), a (all), or q (quit)."

Wait for the user's response before executing anything.

**Ghost project fix** (no built-in move command — must save-then-delete):
```bash
# 1. Fetch the memory
MEMORY=$(curl -s -X POST "$ZIKRA_ENDPOINT" \
  -H "Authorization: Bearer $ZIKRA_TOKEN" \
  -H "User-Agent: curl/7.81.0" \
  -H "Content-Type: application/json" \
  -d '{"command":"get_memory","id":"<UUID>"}')

# 2. Re-save under correct project (preserve all fields)
# 3. Confirm new ID
# 4. Delete original
curl -s -X POST "$ZIKRA_ENDPOINT" \
  -H "Authorization: Bearer $ZIKRA_TOKEN" \
  -H "User-Agent: curl/7.81.0" \
  -H "Content-Type: application/json" \
  -d '{"command":"delete_memory","id":"<UUID>"}'
```

**Non-standard type fix** (via DB if available — update is faster than save+delete):
```bash
docker exec $DB_CONTAINER psql -U $DB_USER -d $DB_NAME -c "
UPDATE memories SET memory_type = '<canonical_type>' WHERE id = '<UUID>';
"
```

---

## Step 5 — Log the audit

Save a diary entry summarising what was found:
```bash
curl -s -X POST "$ZIKRA_ENDPOINT" \
  -H "Authorization: Bearer $ZIKRA_TOKEN" \
  -H "User-Agent: curl/7.81.0" \
  -H "Content-Type: application/json" \
  -d "{
    \"command\": \"save_memory\",
    \"project\": \"zikra\",
    \"memory_type\": \"diary\",
    \"title\": \"$(date +%Y%m%d): Memory audit — <one-line summary of findings>\",
    \"content_md\": \"<paste the FINDINGS block>\",
    \"tags\": null
  }" | python3 -m json.tool
```

---

## Notes for GitHub users

### Required: CLAUDE.md configuration

Add this to your project or global `CLAUDE.md`:
```markdown
## Zikra
zikra_endpoint: http://localhost:8100/webhook/zikra
zikra_token: Bearer <your-token>

## Projects
- project-a — description
- project-b — description
- global    — cross-system prompts only
```

The `## Projects` list is the canonical source of truth for CHECK 1.
Any project name in the DB not on this list is flagged as a ghost.

### Canonical memory types

Default canonical set: `conversation`, `decision`, `prompt`, `diary`, `mockup`, `reference`, `requirement`, `bug`, `knowledge`

To extend for your installation, add to CLAUDE.md:
```markdown
## Zikra canonical types
conversation, decision, prompt, diary, mockup, reference, requirement, bug, knowledge, <your-extra-type>
```

### Running on a schedule

```
/schedule every Monday 09:00 run prompt: zikra-audit
```

Or save this file as a Zikra prompt and run it via `get_prompt`:
```bash
curl -s -X POST $ZIKRA_ENDPOINT \
  -H "Authorization: Bearer $ZIKRA_TOKEN" \
  -H "User-Agent: curl/7.81.0" \
  -H "Content-Type: application/json" \
  -d '{"command":"get_prompt","prompt_name":"zikra-audit","project":"zikra","runner":"<hostname>"}'
```
