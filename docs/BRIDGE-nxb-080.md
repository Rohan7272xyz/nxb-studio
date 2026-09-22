# nxb-080: the bridge. Two agents talking through nxb, with no rig

2026-09-12. Rohan's ask: "if I have an existing agent on Claude Code in my
terminal and Codex in the GUI app, both with MCP, I want the two to simply
talk to each other through that MCP as a bridge, for basic tasks that do not
need a massive workflow."

## What it is

Five MCP tools on the nxb server, backed by two tables in the ledger:

| tool | does |
| --- | --- |
| `nxb_bridge_join(name, runtime?, note?)` | announce yourself under a name the other agent will address |
| `nxb_bridge_peers()` | who is on the bridge, when each was last seen, how many unread each holds |
| `nxb_bridge_send(sender, to, text, reply_to?)` | file a message for a joined name; refused with the peer list if nobody joined under `to` |
| `nxb_bridge_inbox(name, wait?, mark_read?)` | your unread messages; **waits inside the call** up to `wait` seconds (default 45, cap 240) for the first one |
| `nxb_bridge_history(a, b, limit?)` | the conversation between two names, both directions, read-only |

The same five exist on the command line (`python3 -m nxb bridge join|peers|
send|inbox|history`) so a human or a script can sit on the bridge too.

## Why it works with no daemon

Each MCP client spawns its own `python3 -m nxb.mcp` over stdio, so a Claude
Code session and the Codex app are two server processes that share nothing but
the disk. The ledger (`NXB_LEDGER`, absolute, no default) is the one file every
nxb process already agrees on, so the mailbox is two sqlite tables in it.
Writers serialise on the file; a reader polls a table on a 1 to 5 second
backoff inside the tool call. Nothing listens on a port and nothing has to be
running for a message to wait.

On this Mac both clients are already pointed at the same server and ledger:
`~/.claude.json` (`mcpServers.nxb`) and `~/.codex/config.toml`
(`[mcp_servers.nxb]`) both run `python3 -m nxb.mcp` with
`NXB_LEDGER=/Users/rohan/.nxb/ledger.db`. A session's MCP server loads its
code when the session starts, so sessions that were open before this commit
do not see the bridge tools until they are restarted (a fact nxb-078 already
recorded).

## How a conversation goes

Terminal, to the Claude Code session:

> Join the nxb bridge as `claude-terminal`, then send `codex-app` this
> question: "…". Wait in your inbox for the reply and tell me what it says.

Codex app:

> Join the nxb bridge as `codex-app`. Read your inbox with a wait of 45
> seconds, answer whatever arrives by sending to the name it came from, then
> wait again. Stop when I say so.

The agent side of that is four tool calls: `join`, `send`, `inbox(wait=45)`,
`send` again. An inbox that returns EMPTY after its wait is not a failure; the
tool result says so and says to call again.

**The waiting is the point.** nxb-079 measured that an agent polling in a loop
spends one full-context model round-trip per poll. The inbox blocks inside
the tool call instead, so a five-minute wait for a reply costs one or two
tool calls, not sixty.

## Limits, stated

- **Names are self-declared.** The bridge is on one machine; anything that
  can write the ledger is the operator. Addressing, not authentication. Same
  statement as the rest of nxb.
- **The wait cap is 240 seconds**, below what MCP clients allow a tool call
  before they give up on it. If a client cuts a wait short, raise its tool
  timeout (Codex: `tool_timeout_sec` under `[mcp_servers.nxb]`; Claude Code:
  `MCP_TOOL_TIMEOUT`) or ask for a shorter `wait` and call again.
- **A message is at most 64,000 characters.** Larger content goes by file
  path; both agents are on the same disk.
- **One machine.** Two agents on two computers would need the ledger file
  shared between them; that is not built and not pretended.
- **No delivery receipt beyond `read`.** `history` shows whether a message
  was read; nothing says whether the reader acted on it. A reply is the
  evidence, as everywhere else here.

## What it is not

Not a replacement for a rig. A rig gives you a fixed roster, minted ids a
worker validates before acting, a collector and a record; the bridge gives you
two named mailboxes. Use the bridge when the task fits in a conversation and a
rig when the task needs to be dispatched, verified and collected.
