# nxb-081: the context store

2026-09-12. Part two of Rohan's ask after the 48-hour Pact programme: part
one was the caching and context fixes (nxb-079); part two was "find and
implement the service that allows for better context, something like
Obsidian." This is what was explored, what was chosen, what was built, and
what it should be worth in tokens.

## What the measurement left on the table

`docs/CONTEXT-BUDGET-nxb-079.md` decomposed the programme's 1.36 billion
Codex input tokens. After nxb-079 removes polling (633M), carried context
(731M, overlapping) and above-ceiling context (117M), two terms remain that
only a store can attack:

| term | measured | mechanism |
| --- | --- | --- |
| orientation reads: a fresh worker surveying the docs at the start of each task | 18M uncached in the first 15 requests of 185 directive turns, about 99K per task, re-sent on every later request of the task (roughly 200M) | a bounded state note, read first |
| whole replies entering orchestrator contexts on collect | 250 filed replies, 6.3M tokens, median 16K chars, largest 3 MB, each resident until compaction | collect returns summary plus path |

Both are the same failure: bulk content entering a long-lived context. A
store helps only if it changes what enters the context. Built any other way,
with agents dumping everything into a database and reading it back, it adds
tokens. So the caps below are the mechanism, not a nicety.

## What was explored

**Obsidian.** Installed here, with two registered vaults (`~/Vellum`, open,
1.1 GB, 4,414 notes; `~/Cloak`), no community plugins. A vault is a folder
of markdown; agents on this Mac can open those files directly. The Local
REST API plugin, since 5.0 in July 2026, serves MCP itself at
`https://127.0.0.1:27124/mcp/` behind a bearer token, and several Obsidian
MCP servers wrap that plugin ([plugin page](https://community.obsidian.md/plugins/obsidian-local-rest-api),
[repository](https://github.com/coddingtonbear/obsidian-local-rest-api),
[comparison of four servers](https://contextbolt.com/blog/obsidian-mcp-claude/),
[setup guide](https://mcp.directory/blog/obsidian-mcp-complete-guide-2026)).
For local agents that is a network hop, a plugin and a listener in the
operator's Obsidian to reach files they can already read. Not adopted; the
vault built here is plain files any Obsidian can open, and `NXB_VAULT` may
point it into an Obsidian vault of the operator's choosing.

**Hosted memory layers.** mem0 (vector-first, about 6,800 tokens per
retrieval call by its own figures), Zep with Graphiti (temporal knowledge
graph), Letta (an agent runtime that pages its own memory), LangMem
([one comparison](https://ecorpit.com/ai-agent-memory-mem0-zep-letta-cloudflare-comparison-2026/),
[another](https://particula.tech/blog/agent-memory-frameworks-tested-mem0-zep-letta-cognee-2026),
[a third](https://www.developersdigest.tech/blog/best-ai-agent-memory-providers-2026)).
All retrieve **per turn**. Under this project's cost model every retrieval
is a tool round-trip that re-sends the whole context: the polling pattern
nxb-079 removed. Per-task retrieval is the right granularity. They are also
hosted or third-party, and stdlib-only is a standing rule here.

**Life OS ADR-0048 (2026-07-27).** Rohan's own precedent: an FTS5 lexical
index over markdown, outside the vault, never the source of truth, fully
rebuildable, chunked into passages, no model-written text in the index,
curated memory tiered above transcripts. Measured there on a 9 MB vault
against a live wrong answer, and it fixed both scan cost and the answer.
This design is reused on the same reasoning: the querier is a model, so
lexical search plus a second try is the cheap half of a hybrid.

## What was built

A vault beside the ledger (`~/.nxb/vault`, or `NXB_VAULT`), an FTS5 index
beside it (`vault-index.db`, never inside the vault), five MCP tools, a CLI,
and three seams into the fleet.

**Layout**

```
rigs/<session>/STATE.md        the orientation note; at most 24,000 characters
rigs/<session>/LOG.md          one line per collected task, appended by nxb
rigs/<session>/tasks/<id>.md   task card: summary, worker, link to the report
reports/<id>.md                the full filed reply
notes/<key>.md                 anything else, by key
```

Every note is Obsidian-compatible markdown with YAML frontmatter (`key`,
`kind`, `updated_at`, `author`, `tags`, `summary`); cards link reports with
`[[wikilinks]]`.

**The caps**

| read or write | bound |
| --- | --- |
| state note (`put` on a `/STATE` key) | refused over 24,000 characters, with the remedy: move detail to its own note and link it |
| `get` | 32,000 characters by default; `truncated` and `next_offset` say there is more |
| `search` | at most 8 hits, about 300 characters each, 2 per note, never a body |
| collect | over 6,000 characters the orchestrator receives the worker's SUMMARY and the path; `--full` for the whole text |

**The seams into the fleet**

1. Every directive now asks the worker to begin its filed answer with a
   `SUMMARY:` paragraph of at most 800 characters. `collect` files a long
   answer as `reports/<id>` plus a task card and a log line, and returns
   that paragraph and the path. The orchestrator's context receives about
   200 tokens per collect instead of a median 4K and a maximum of 770K.
2. When a rig has a state note, every directive to it carries one sentence:
   `ORIENT FIRST: your rig's state note is at <path>. Read it before reading
   anything else`. Absent the note, directives read as before.
3. The orchestrator brief tells the orchestrator to read the note at the
   start of every dispatching turn, to update it after every collected task,
   to read a report path only when the summary is not enough, and to search
   with snippets rather than open files.

**Tools and commands**

| MCP | CLI |
| --- | --- |
| `nxb_context_state(session)` | `nxb context state --session S` |
| `nxb_context_get(key, max_chars?, offset?)` | `nxb context get --key K` |
| `nxb_context_put(key, body, summary?, tags?, author?)` | `nxb context put --key K --file F` |
| `nxb_context_search(query, limit?, prefix?)` | `nxb context search --query "..."` |
| `nxb_context_list(prefix?)` | `nxb context list --prefix rigs/` |
| | `nxb context index` (rebuild), `log`, `path` |

The index refreshes itself before every search and list by comparing
`(mtime_ns, size)` against its manifest, within a budget, and says how many
files it is behind on. A note edited in Obsidian, or dropped into the
folder by hand, is found on the next search. Deleting the index loses
nothing.

## Seeing it in Obsidian

`python3 -m nxb context path` prints the folder. Either open that folder as
a vault in Obsidian (Open folder as vault), or set
`NXB_VAULT=/Users/rohan/Vellum/NXB` in the environment of the Studio
service, the MCP servers and your shell, and every note lands inside the
Vellum vault as it is written. The second is the operator's choice; nxb
never writes into a vault it was not pointed at.

## What it should be worth

Projection, not measurement; the terms are from the decomposition above and
can be verified on the next real run.

| system | projected Codex input, same workload |
| --- | --- |
| measured baseline | 1,364M |
| after nxb-079 | roughly 450M to 500M |
| after nxb-079 plus this store, used as briefed | roughly 300M |

The store's share comes from two places: orientation reading falling from
about 99K tokens per task to a few thousand plus whatever code the task
actually touches, and orchestrator contexts staying tens of thousands of
tokens rather than saturating a 244K window with collected reports. It
cannot shrink the work itself, and it cannot shrink screenshots.

## Limits, stated

- Lexical search. A paraphrase that shares no words with the note misses; the
  querier is a model and can try other terms, and the result says when
  nothing matched any term. A semantic rerank would be a second tier, added
  only against a measured miss, as ADR-0048 also held.
- The state note is the orchestrator's to keep. nxb bounds it and points
  workers at it; it does not write it. A rig whose orchestrator never
  writes one gets the old behaviour, and `nxb context state` says MISSING.
- One vault per ledger. A hub and its peers share a ledger and therefore a
  vault, with their own `rigs/<session>/` trees.
- Not a memory of what agents said to each other; the bridge (nxb-080) and
  the replies directory keep that. This holds what a task needs to start.
