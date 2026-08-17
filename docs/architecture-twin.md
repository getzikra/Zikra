# Architecture Twin

Zikra's Architecture Twin turns project memories into a structured,
evidence-linked view of the software that exists now. It is deliberately not
an HTML generator: Kimi returns a constrained JSON model, Zikra validates and
stores it, and the dashboard renders that model with trusted code.

## Product model

The workspace combines several established ideas:

- C4/Structurizr hierarchy for systems, containers, components, and context.
- IcePanel-style drill-down and runtime flow playback.
- Ardoq-style evidence, confidence, ownership, findings, and change history.
- Graph exploration as a secondary view rather than the primary document.

The result has seven views: Overview, Model, Runtime, Flows, Decisions,
Changes, and Report. The original VeltisAI architecture HTML is visual
inspiration only; it is never imported as authoritative project state.

## Nightly data flow

1. The scheduler selects configured projects at the configured local hour.
2. Zikra reads only searchable memories in that project, prioritizing
   architecture, module, index, verified reference, audit, and investigation
   records before general decisions and conversations.
3. Common credential forms are redacted before any source text is sent to the
   architecture model.
4. Kimi reconciles duplicate, stale, contradictory, proposed, and observed
   claims into the structured schema. Each confident node must cite a real
   source memory ID.
5. Zikra rejects unknown evidence IDs, invalid relationships, unsafe IDs, and
   over-large sections, then computes evidence coverage and change history.
6. The result is saved as a **draft**. It never publishes automatically.
7. An owner or admin reviews the draft in the dashboard and explicitly
   publishes it. Publishing archives the previous published snapshot for the
   same project and environment.

Each project is isolated and has its own snapshot history and run state. Add
projects to the comma-separated configuration value; no code change is needed.

## Configuration

```dotenv
ZIKRA_ARCHITECTURE_ENABLED=1
ZIKRA_ARCHITECTURE_PROJECTS=veltisai
ZIKRA_ARCHITECTURE_MODEL=kimi-for-coding
ZIKRA_ARCHITECTURE_HOUR=2
ZIKRA_ARCHITECTURE_TIMEZONE=America/New_York
ZIKRA_ARCHITECTURE_SOURCE_LIMIT=300
ZIKRA_ARCHITECTURE_MAX_SOURCE_CHARS=180000
```

The worker uses `ZIKRA_ARCHITECTURE_BASE_URL` and
`ZIKRA_ARCHITECTURE_API_KEY` when set. Otherwise it falls back to the existing
Zikra/LiteLLM OpenAI-compatible base URL and key. This lets normal memory
distillation keep its existing model while architecture synthesis selects the
direct `kimi-for-coding` LiteLLM route.

Kimi's coding membership endpoint currently requires `temperature=1`; the
worker sets that explicitly and requests a JSON object response.

## Dashboard API

- `GET /api/ui/architecture?project=<project>&environment=all|dev|prod`
- `POST /api/ui/architecture/generate` with `{project, environment}`
- `POST /api/ui/architecture/<snapshot-id>/publish` with `{project}`

Generation and publishing require owner/admin. Other authenticated roles see
only the published snapshot; owner/admin can preview the newest draft.

## Architecture decisions

`save_decision` writes a typed architecture decision into the existing
memories table. A revision can supersede only a current architecture decision
in the same project and module. The update and supersession are atomic, titles
cannot silently move between modules, and ordinary product decisions or
prompts cannot be altered by an architecture supersession.

Use `get_architecture` for current typed decisions and `module_history` for the
full immutable supersession chain. These decision records are also available
as evidence to the nightly twin.

## Design references

- [C4 model diagrams](https://c4model.com/diagrams)
- [Structurizr workspaces](https://docs.structurizr.com/workspaces)
- [IcePanel diagramming](https://docs.icepanel.io/core-features/diagramming)
- [Ardoq in-view data modeling](https://help.ardoq.com/en/articles/627199-new-ardoq-experience-get-started-with-in-view-data-modeling)
- [Neo4j Bloom](https://neo4j.com/docs/bloom-user-guide/current/about-bloom/)
