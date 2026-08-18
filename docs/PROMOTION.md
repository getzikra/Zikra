# Zikra Promotion Kit

This is the reusable public launch kit for Zikra. Use it when submitting Zikra
to directories, communities, newsletters, podcasts, awesome lists, and launch
platforms.

## Canonical links

- Website: https://zikra.dev
- GitHub: https://github.com/GetZikra/zikra
- Install guide: https://zikra.dev/install.html
- Screenshots: https://zikra.dev/screenshots.html
- Architecture: https://github.com/GetZikra/zikra/blob/main/docs/architecture.md
- License: MIT

## Core positioning

### One-line

Zikra is open-source governed project memory for teams of AI agents.

### Short description

Zikra gives Claude Code, Codex, Gemini, Cursor, and custom agents one shared
memory layer for project decisions, requirements, prompts, errors, and run
history, with MCP, HTTP, roles, project scoping, and self-hosted storage.

### Long description

Zikra is an open-source memory layer for AI-native teams. It lets multiple AI
agents and multiple people share the same project context across sessions,
machines, and tools. Claude Code can connect through MCP, while Codex, Gemini,
shell hooks, and custom agents can use the HTTP command API. Zikra stores typed
memories such as decisions, requirements, prompts, errors, notes, and run logs,
then retrieves them with hybrid search, ranking, token budgeting, and graph
links. It is self-hosted, MIT licensed, and runs locally with SQLite or on a team
server with PostgreSQL.

## Taglines

- Governed project memory for teams of AI agents.
- One shared memory layer. Every agent. Every project.
- Persistent memory for Claude Code, Codex, Gemini, Cursor, and custom agents.
- Requirements, decisions, prompts, and run history for AI-native teams.
- MCP-native memory that works outside MCP too.

## Category

Use whichever category the platform supports:

- Developer tools
- AI agents
- Open source
- Productivity
- Knowledge management
- Infrastructure
- MCP server
- Search and retrieval

## Keywords

`AI agents`, `agent memory`, `MCP server`, `Claude Code memory`,
`persistent memory`, `project memory`, `developer tools`, `open source AI`,
`Codex`, `Gemini CLI`, `Cursor`, `RAG`, `semantic search`, `team memory`,
`self-hosted`, `PostgreSQL`, `SQLite`, `pgvector`, `sqlite-vec`

## Submission form answers

| Field | Answer |
| --- | --- |
| Product name | Zikra |
| Website | https://zikra.dev |
| GitHub | https://github.com/GetZikra/zikra |
| Pricing | Free, open source, MIT licensed |
| Platform | Self-hosted Python server |
| Audience | Developers, AI agent builders, AI-native teams, open-source maintainers |
| Main benefit | Shared governed project memory across agents, people, sessions, and machines |
| Integrations | MCP, Claude Code, Cursor, Codex CLI, Gemini CLI, HTTP API, shell hooks |
| Storage | SQLite + sqlite-vec locally, PostgreSQL + pgvector for teams |
| Contact | Use GitHub issues unless a direct contact is required |

## Product Hunt

### Tagline

Open-source governed memory for teams of AI agents.

### Description

Zikra gives Claude Code, Codex, Gemini, Cursor, and custom agents one shared
memory layer for decisions, requirements, prompts, errors, and run history. It is
self-hosted, MCP-native, HTTP-friendly, project-scoped, and MIT licensed.

### First comment

I built Zikra because my agents kept losing the project context that my team and
I had already worked out. Claude Code, Gemini, Codex, and other tools were all
useful, but they lived in separate memory silos.

Zikra turns that into one governed project memory layer. Agents can save and
search decisions, requirements, prompts, errors, notes, and run summaries across
sessions and machines. MCP clients use `/mcp`; hooks and custom agents can use
the HTTP command API. It runs locally with SQLite or on a team server with
PostgreSQL.

The goal is not another note app. The goal is durable project memory for teams
of agents.

## Hacker News

### Title

Show HN: Zikra, open-source governed memory for teams of AI agents

### Post

I built Zikra after repeatedly losing project context between AI coding sessions.
Claude Code, Gemini, Codex, Cursor, and custom agents are all useful, but their
memory is fragmented.

Zikra is an open-source memory layer that gives agents one shared project memory
pool. It stores typed memories: requirements, decisions, prompts, errors, notes,
and run logs. Agents can connect through MCP at `/mcp` or through a simple HTTP
command API at `/webhook/zikra`.

The part I care most about is governance. This is not just personal chat memory:
tokens have roles, tokens can be scoped to projects, and the same server can
support multiple people, agents, and projects.

It runs locally with SQLite + sqlite-vec and can use PostgreSQL + pgvector for
team deployments.

Website: https://zikra.dev
GitHub: https://github.com/GetZikra/zikra

Would appreciate technical feedback, especially from people building with MCP,
agent frameworks, or multi-agent coding workflows.

## Reddit

### Technical communities

Title:

`I built Zikra: open-source governed project memory for AI agents`

Post:

I built Zikra because my AI coding tools kept losing context between sessions
and across tools. Claude Code might know something, Gemini would not, Codex
would not, and a teammate's agent would have no idea what had already been
decided.

Zikra is a self-hosted memory layer for agents. It stores typed project memory:
requirements, decisions, prompts, errors, notes, and run history. MCP clients can
connect through `/mcp`, while hooks and custom agents can call the HTTP API.

The twist is governance: roles, project-scoped tokens, typed memories, run
telemetry, and a web UI for browsing graph links, requirements, prompts, and
runs.

It is MIT licensed:
https://github.com/GetZikra/zikra

Website:
https://zikra.dev

I am looking for technical feedback from people using Claude Code, Codex, Gemini
CLI, Cursor, MCP, or custom agent workflows.

### Short side-project version

I built Zikra, an open-source memory layer that lets Claude Code, Codex, Gemini,
Cursor, and custom agents share project memory across sessions and machines.

It stores requirements, decisions, prompts, errors, notes, and run history. It is
self-hosted, MCP-native, HTTP-friendly, and MIT licensed.

https://zikra.dev
https://github.com/GetZikra/zikra

## LinkedIn

I built Zikra, an open-source governed memory layer for teams of AI agents.

The problem: AI coding tools are useful, but their memory is fragmented. A
decision made in one Claude Code session is invisible to Gemini, Codex, Cursor,
or a teammate's agent.

Zikra gives agents a shared project memory pool for requirements, decisions,
prompts, errors, notes, and run history. It supports MCP, a direct HTTP API,
project-scoped tokens, role-based access, SQLite for local use, PostgreSQL for
teams, and a web UI for browsing memory.

The goal is simple: project context should survive the session, the tool, and
the machine.

Website: https://zikra.dev
GitHub: https://github.com/GetZikra/zikra

## X / Twitter

### Launch thread

1. I built Zikra: open-source governed memory for teams of AI agents.

Claude Code, Codex, Gemini, Cursor, and custom agents can finally share the same
project memory across sessions, machines, and tools.

https://zikra.dev

2. Zikra stores typed project memory:

- requirements
- decisions
- prompts
- errors
- notes
- run history

Not just chat history. Project memory.

3. Agents connect through MCP at `/mcp` or through a simple HTTP command API at
`/webhook/zikra`.

Local setup uses SQLite + sqlite-vec. Team setup can use PostgreSQL + pgvector.

4. The twist is governance:

- roles
- project-scoped tokens
- typed memories
- run telemetry
- memory graph
- web UI

This is memory infrastructure for teams, not only personal recall.

5. It is MIT licensed and open source:

https://github.com/GetZikra/zikra

I would love feedback from people building with MCP, Claude Code, Codex, Gemini
CLI, Cursor, or agent workflows.

### Single post

I built Zikra: open-source governed project memory for teams of AI agents.

Claude Code, Codex, Gemini, Cursor, and custom agents share requirements,
decisions, prompts, errors, notes, and run history through MCP or HTTP.

MIT licensed.

https://zikra.dev

## Directory submission targets

Use this as a submission tracker.

| Site | URL | Fit | Status |
| --- | --- | --- | --- |
| Product Hunt | https://www.producthunt.com/posts/new | High | Not submitted |
| Hacker News | https://news.ycombinator.com/submit | High | Not submitted |
| AlternativeTo | https://alternativeto.net/software/new/ | Medium | Not submitted |
| Dev Hunt | https://devhunt.org/submit | High | Not submitted |
| Uneed | https://www.uneed.best/submit-a-tool | Medium | Not submitted |
| Toolsland.ai | https://www.toolsland.ai/submit-ai-tool-free | Medium | Not submitted |
| AI SuperHub | https://aisuperhub.io/ai-tools/submit | Medium | Not submitted |
| Submit AI Tools | https://submitaitools.org/ | Medium | Not submitted |
| AI Directory | https://www.ai-directory.io/ | Medium | Not submitted |
| The Next AI | https://www.thenextai.com/submit-ai-tool/ | Medium | Not submitted |
| AIToolsIndex | https://aitoolsindex.org/submit | Medium | Not submitted |
| GitHub awesome-mcp lists | Search GitHub for awesome-mcp | High | Not submitted |
| GitHub awesome-ai-agents lists | Search GitHub for awesome-ai-agents | High | Not submitted |
| Reddit r/LocalLLaMA | https://www.reddit.com/r/LocalLLaMA/submit | High | Not submitted |
| Reddit r/opensource | https://www.reddit.com/r/opensource/submit | Medium | Not submitted |
| Reddit r/SideProject | https://www.reddit.com/r/SideProject/submit | Medium | Not submitted |
| Reddit r/AI_Agents | https://www.reddit.com/r/AI_Agents/submit | High | Not submitted |
| Dev.to | https://dev.to/new | Medium | Not submitted |
| Hashnode | https://hashnode.com/ | Medium | Not submitted |

## Awesome-list pull request text

Title:

`Add Zikra, governed project memory for AI agents`

Body:

This PR adds Zikra, an MIT-licensed memory layer for AI agents. Zikra provides
shared project memory across Claude Code, Codex, Gemini, Cursor, and custom
agents through MCP and HTTP. It stores typed memories such as requirements,
decisions, prompts, errors, notes, and run logs, with roles and project-scoped
tokens for team use.

Website: https://zikra.dev
GitHub: https://github.com/GetZikra/zikra

## Launch checklist

- [ ] Confirm `README.md` quickstart works from a clean clone.
- [ ] Confirm `zikra.dev` has current MCP endpoint `/mcp`.
- [ ] Confirm screenshots page shows current UI.
- [ ] Pin a GitHub issue asking for feedback from MCP users.
- [ ] Add GitHub topics.
- [ ] Submit Hacker News first.
- [ ] Submit Product Hunt with screenshots and architecture image.
- [ ] Submit 5 high-fit directories.
- [ ] Open 3 awesome-list PRs.
- [ ] Post one technical writeup on Dev.to or Hashnode.
