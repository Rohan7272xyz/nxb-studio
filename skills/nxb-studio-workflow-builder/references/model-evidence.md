# Model and effort evidence

Snapshot date: **2026-09-04**. This file covers models relevant to the local NXB Studio's Claude Code and Codex runtimes. It is a routing evidence pack, not a promise of availability or future performance.

## Evidence discipline

### Fact classes

Keep these separate in every recommendation:

- **Public contract**: current official provider docs for model IDs, supported settings, pricing, and availability.
- **Published evaluation**: a numerical result from an official launch report, system card, or original benchmark publisher, with its configuration.
- **Local observation**: installed CLI version, embedded catalog, configured default, or a successful historical transcript on this machine.
- **Inference**: a workflow recommendation derived from the above.

Never phrase an inference as a benchmark fact. A hard statistic is still a sample from a particular harness, not a deterministic prediction for the user's repository.

### Required metadata for a score

Preserve:

```text
model/canonical ID; effort or mode; benchmark and version; scaffold/harness;
tools; context/output limits; trials/seeds; evaluation date; safeguards or
fallback; agent count; source URL
```

If the source omits a field, say `not disclosed`. Do not fill it from another source.

### Refresh policy

When model choice affects a workflow and Internet access is available:

1. Open the current official model/config pages for both providers.
2. Check official retirement/availability notes and the installed client version.
3. Check whether a newer provider launch/system card supersedes this snapshot.
4. Prefer original benchmark documentation when interpreting a benchmark.
5. Record the retrieval date in the recommendation.

If current browsing is unavailable, use this snapshot and state its date. Never silently call it current after a newer release or client update.

Use primary sources. A secondary leaderboard can add context only when the original source is unavailable; label it as secondary. Do not use customer quotes as hard benchmarks.

## Local NXB environment at the snapshot

Local observation, not account-entitlement proof:

- Claude Code `2.1.260`; configured default `opus[1m]`, `xhigh`.
- Codex CLI `0.153.2`; configured default `gpt-5.6-sol`, `xhigh`.
- NXB's Claude suggestions: `opus`, `opus[1m]`, `fable`, `fable[1m]`, `sonnet`, `sonnet[1m]`, `haiku`.
- NXB's Codex regex suggestions: `gpt-5.6-terra`, `gpt-5.6-sol`, `gpt-5.6-pro`, `gpt-5.6-luna`, `gpt-5.6`, `gpt-5.5`, `gpt-5.4-mini`, `gpt-5.4`, `gpt-5.3-codex`, `gpt-5.2-codex`, `gpt-5.2`.
- The installed Codex binary knows `gpt-6-astra`, but NXB's GPT-5-only regex omits it.
- Binary/catalog presence proves client recognition only. The account can still lack access.
- `gpt-5.6-pro` is a local string match without a corresponding current official model contract found in this review. Do not recommend it as a real model without fresh proof.

The baseline Studio uses a generic effort suggestion list. Exact support is model/client-specific and must be checked independently.

## Current OpenAI/Codex lineup

Public contract from the official [Codex model guide](https://learn.chatgpt.com/docs/models) and API model pages, retrieved 2026-09-04:

| Model | Intended use | API effort | Context / max output | Current API list price per MTok input / cached / output |
|---|---|---|---|---:|
| `gpt-6-astra` | Hardest end-to-end code, apps, research, computer-use, and judgment-heavy work | low, medium, high, xhigh, max | 1.05M / 128K | $10 / $1 / $50 |
| `gpt-5.6-sol` | Complex, ambiguous, high-value work needing depth and polish | none, low, medium default, high, xhigh, max | 1.05M / 128K | $4 / $0.40 / $20 |
| `gpt-5.6-terra` | Everyday pragmatic all-rounder; natural GPT-5.5 replacement | same as Sol | 1.05M / 128K | $2 / $0.20 / $12 |
| `gpt-5.6-luna` | Clear, repeatable, cost-sensitive, high-volume work | same as Sol | 1.05M / 128K | $0.20 / $0.02 / $1.20 |
| `gpt-5.3-codex-spark` | Near-instant, text-only coding iteration research preview | no current API effort contract | 128K at launch | subscription preview; do not infer API price |

Sources:

- [GPT-6 Astra API model](https://developers.openai.com/api/docs/models/gpt-6-astra)
- [GPT-5.6 Sol API model](https://developers.openai.com/api/docs/models/gpt-5.6-sol)
- [GPT-5.6 Terra API model](https://developers.openai.com/api/docs/models/gpt-5.6-terra)
- [GPT-5.6 Luna API model](https://developers.openai.com/api/docs/models/gpt-5.6-luna)
- [Codex model guide](https://learn.chatgpt.com/docs/models)
- [Codex Spark launch](https://openai.com/index/introducing-gpt-5-3-codex-spark/)

`gpt-5.6` aliases to Sol. Use a canonical/pinned ID when reproducibility matters; use a family alias when accepting provider-managed upgrades.

Knowledge cutoffs in the current API contracts are 2026-04-30 for Astra and 2026-02-16 for the GPT-5.6 family. A cutoff is not a reason to skip current-source retrieval when the task depends on newer facts.

Pricing notes:

- Sol's $4/$20 promotional API pricing is documented through at least 2026-11-21.
- OpenAI documents cache writes separately at 1.25 times uncached input for these newer models.
- Requests beyond 272K input tokens are priced at 2x input and 1.5x output for the entire request.
- Astra API Fast processing is 2x standard price. Codex subscription Fast mode uses a credit multiplier; do not conflate API dollars with subscription usage/credits.
- NXB launches interactive clients. API price is useful comparative evidence but does not directly calculate the operator's plan usage.

### Codex effort and orchestration semantics

From the current [Codex model guide](https://learn.chatgpt.com/docs/models):

| Setting | Meaning |
|---|---|
| low | Quick, tightly scoped tasks; lighter reasoning |
| medium | Default balance for everyday work |
| high | Greater depth for difficult multistep work |
| xhigh | Extra-high depth for complex problems |
| max | Maximum single-agent reasoning time for the hardest problems |
| ultra | Maximum reasoning plus automatic task delegation to subagents |

`ultra` is not an API `reasoning.effort` value. OpenAI's GPT-5.6 launch used four agents by default for Ultra and directs API developers to the Responses multi-agent beta for Ultra-like behavior.

Current public surfaces are inconsistent: the interactive Codex selector shows Max and Ultra, while the public config reference historically listed `model_reasoning_effort` only through xhigh. The installed 0.153.2 embedded catalog exposes Ultra for Astra/Sol/Terra and Max for Luna, but that local structure is not a durable public contract.

Therefore:

- do not blindly encode `ultra` as `model_reasoning_effort`;
- capability-check the installed client and selected model;
- treat Ultra as nested orchestration in the workflow brief;
- default to visible NXB workers instead of hidden nested subagents;
- if selected explicitly, disclose agent multiplication and quota implications.

## Current Anthropic/Claude lineup

Public contract from official model and Claude Code docs, retrieved 2026-09-04:

| Product | Canonical Anthropic API ID | Common Claude Code selection | Effort support | Context / max output | API price per MTok input / output |
|---|---|---|---|---|---:|
| Fable 5.1 | `claude-fable-5-1` | `fable` in Claude Code >=2.1.255 | low, medium, high default, xhigh, max | 1M / 128K | $10 / $50 |
| Fable 5 | `claude-fable-5` | explicit ID; old `fable` resolution before 2.1.255 | low, medium, high default, xhigh, max | 1M / 128K | $10 / $50 |
| Opus 5 | `claude-opus-5` | `opus` or `opus[1m]` on the Anthropic API | low, medium, high default, xhigh, max | 1M / 128K | $5 / $25 |
| Sonnet 5 | `claude-sonnet-5` | `sonnet` or `sonnet[1m]` on the Anthropic API | low, medium, high default, xhigh, max | 1M / 128K | $2 / $10 |
| Haiku 4.5 | `claude-haiku-4-5-20251001` | `haiku` | **no effort control** | 200K / 64K | $1 / $5 |

Sources:

- [Fable 5.1 overview](https://platform.claude.com/docs/en/models/fable-5-1/overview)
- [Claude model overview](https://platform.claude.com/docs/en/models/overview)
- [Claude Code model configuration](https://code.claude.com/docs/en/model-config)
- [Anthropic effort guide](https://platform.claude.com/docs/en/build-with-claude/effort)

Version minima in the Claude Code docs: Fable 5.1 >=2.1.255, Fable 5 >=2.1.170, Opus 5 >=2.1.219, and Sonnet 5 >=2.1.197.

Documented reliable knowledge cutoffs are 2026-06 for Fable 5.1, 2026-05 for Opus 5, 2026-01 for Sonnet 5, and 2025-02 for Haiku 4.5. Retrieve current sources for facts newer than those dates.

Aliases are mutable and provider-dependent. On the Anthropic API at this snapshot, `fable`, `opus`, and `sonnet` resolve to Fable 5.1, Opus 5, and Sonnet 5. Cloud providers can lag. Store the resolved canonical model in run evidence whenever exact reproducibility matters.

`best`, `default`, and `opusplan` are official Claude Code selector modes but are not currently discovered by NXB's simple alias regex. Do not assume a picker is complete.

Mythos 5.1/5 and Mythos Preview are reduced-safeguard variants represented in some launch evaluations and special access programs. They are not ordinary local NXB suggestions. Do not route work to Mythos unless current official eligibility, risk controls, and exact model ID are established.

### Claude effort and orchestration semantics

From the current [effort guide](https://platform.claude.com/docs/en/build-with-claude/effort) and [Claude Code configuration](https://code.claude.com/docs/en/model-config):

| Setting | Meaning |
|---|---|
| low | Efficient, short, scoped, latency-sensitive, non-frontier work; often suitable for subagents |
| medium | Balanced token saving for ordinary agentic work |
| high | Default on current effort-capable models; complex coding/reasoning |
| xhigh | Long-horizon agentic/coding work, often over 30 minutes, with substantially higher token use |
| max | Deepest model effort with unconstrained token spending; diminishing returns and overthinking are possible |
| ultracode | **Claude Code mode**, not API effort: sends xhigh and orchestrates dynamic workflows |

Additional rules:

- Effort affects total agent behavior—reasoning, tool calls, files read, and verification—not only hidden thinking.
- Effort labels are calibrated per model. The same label is not a fixed common compute budget.
- Unsupported selections can fall back to the highest supported level at or below the request; confirm the session header/resolved run.
- In Claude Code, `max` is session-only unless set with `CLAUDE_CODE_EFFORT_LEVEL`; normal persisted settings accept through xhigh.
- `ultracode` needs Claude Code >=2.1.203 and has its own persistence setting. If dynamic workflows are disabled, it degrades to ordinary xhigh.
- `ultrathink` is a one-turn in-context instruction. It does not change the API effort value.
- Haiku 4.5 does not support effort. Omit it.

There is no authoritative public benchmark for Claude Code `ultracode` versus xhigh/max. Do not invent one.

## Like-for-like current cross-provider evidence

### OpenAI Astra launch comparison

The [GPT-6 Astra launch report](https://openai.com/index/gpt-6-astra/) published the following table on 2026-09-04. These are source-specific system results and, unless a row says otherwise, **maximum scores at any tested effort**. The exact winning effort is not disclosed. Research/API harnesses may differ from production Codex and Claude Code.

| Coding evaluation | Astra | Sol | Fable 5.1 | Fable 5 | Opus 5 | Gemini 3.8 Flash |
|---|---:|---:|---:|---:|---:|---:|
| Terminal-Bench 4.0 | 57.9% | 37.3% | 55.8% | 42.0% | 52.3% | 19.1% |
| DeepSWE v1.1 | 74.1% | 72.7% | 67.4% | 69.9% | 73.7% | 73.8% |
| FrontierCode 1.1 Extended | 64.5% | 60.6% | 63.6% | 64.9% | 63.6% | 56.3% |
| FrontierCode 1.1 Main | 53.3% | 47.5% | 50.9% | 53.5% | 53.4% | 43.6% |
| Internal Database Migration Tasks | 63.9% | 42.7% | 57.8% | 50.3% | not shown | not shown |
| AA Coding Agent Index v1.4 | 67.0 | 65.1 | not shown | 67.2 | 68.1 | 61.2 |

Other relevant rows from that same report:

| Evaluation | Astra | Sol | Fable 5.1 | Fable 5 | Opus 5 |
|---|---:|---:|---:|---:|---:|
| Terminal-Bench-Science 0.1 | 64.6% | 22.4% | 52.6% | 21.4% | 30.0% |
| AutomationBench | 41.4% | 18.1% | 31.4% | 17.4% | 26.9% |
| Agents' Last Exam | 59.3% | 53.6% | not shown | 48.7% | 55.5% |
| OSWorld 2.0, 2026-08-08 offline partial | 72.6% | 65.7% | not shown | not shown | 70.2% |
| BrowseComp | 91.5% | 90.4% | not shown | 87.4% | 90.8% |
| MRCR v2, 256K-512K | 100.0% | 91.5% | not shown | not shown | not shown |
| MRCR v2, 512K-1M | 96.3% | 73.8% | not shown | not shown | not shown |

Useful inference: Astra has the strongest published result in this table for Terminal-Bench 4.0 and several long-horizon/automation tasks, but it does not dominate every coding row. Do not choose it universally from one aggregate.

### Anthropic Fable 5.1 launch comparison

The [Fable 5.1 launch](https://www.anthropic.com/claude-fable-and-mythos-5-1) reports a consistent launch-table setup for these rows:

| Evaluation | Fable 5.1 | Fable 5 | Opus 5 | GPT-5.6 Sol |
|---|---:|---:|---:|---:|
| Terminal-Bench-Science 0.1 | 52.6% | 24.7% | 29.0% | 22.4% |
| Terminal-Bench 4.0 | 55.8% | 42.0% | 52.3% | 37.3% |
| CursorBench 3.2 | 73.4% | 70.5% | 70.0% | 67.2% |
| AutomationBench | 31.4% | 17.1% | 26.9% | 19.6% |

Terminal-Bench 4.0 used 66 tasks, Claude Code `--bare`, max effort, and 15 trials/task for Claude models; reported standard error was roughly +/-1.6 to 2 points. Terminal-Bench-Science used 70 tasks and had roughly +/-3.5 to 4.5 points standard error. Anthropic's reproduced Fable/Opus science values differ from the three-trial public-leaderboard values but fall within noise.

Do not merge this table's 24.7/29.0 values with OpenAI's 21.4/30.0 table as if one were a typo; they came from different trial setups.

## Provider-specific coding evidence

### Astra and GPT-5.6 family

OpenAI's [GPT-5.6 launch report](https://openai.com/index/gpt-5-6/) published:

| Evaluation | Sol | Terra | Luna | GPT-5.5 |
|---|---:|---:|---:|---:|
| AA Coding Agent Index v1.1 | 80 | 77.4 | 74.6 | 76.4 |
| SWE-Bench Pro | 64.6% | 63.4% | 62.7% | 59.4% |
| DeepSWE v1.1 | 72.7% | 69.6% | 67.2% | 67.0% |
| Terminal-Bench 2.1 | 88.8% | 87.4% | 84.7% | 85.6% |
| AutomationBench | 18.1% | 15.2% | 14.9% | 12.9% |
| MRCR 256K-512K | 91.5% | 89.6% | 41.3% | 81.5% |
| MRCR 512K-1M | 73.8% | 72.5% | 41.3% | 74.0% |

The narrative explicitly identifies Sol Max at 80 on AA Coding Agent Index v1.1. Do not silently label every other single-agent row Max when the table does not.

Public Ultra comparisons in the same report:

| Evaluation | Sol single-agent column | Sol Ultra |
|---|---:|---:|
| Terminal-Bench 2.1 | 88.8% | 91.9% |
| BrowseComp | 90.4% | 92.2% |
| SEC-Bench Pro | 71.2% | 74.3% |

Ultra used four agents by default. These rows show a measured gain in those harnesses, not a universal benefit for nested NXB workflows.

For Astra, the launch report does **not** publish a Low/Medium/High/XHigh/Max coding grid. Any table claiming exact Astra coding performance at each effort is fabricated.

### Fable 5.1

Official launch/system-card evidence:

- SWE-bench Pro 81.2%, Multilingual 89.1%, Multimodal 54.7%, DeepSWE 1.1 67.4%: adaptive thinking, max, default sampling, five-trial averages.
- Terminal-Bench 4.0 55.8%; Terminal-Bench-Science 52.6%; CursorBench 3.2 73.4%: benchmark-specific production/Claude Code harnesses.
- FrontierSWE v2 mean score 0.57 versus Opus 5 0.52 and Fable 5 0.48: 34 ultra-long tasks, max, five trials/task, Proximal harness, up to about 20 hours.

Sources: [Fable 5.1 launch](https://www.anthropic.com/claude-fable-and-mythos-5-1) and [Fable 5.1 system card](https://www-cdn.anthropic.com/0339e6a7c5c7b87f5c07798616dc32c215d14235/Claude%20Fable%205.1%20%26%20Claude%20Mythos%205.1%20System%20Card.pdf).

Anthropic recommends starting Fable 5.1 at high and sweeping all five levels. At low it may search/retrieve less; require current-source verification explicitly on retrieval-heavy work. At xhigh/max, leave enough output capacity for thinking plus the final artifact.

### Fable 5

Official launch/system-card evidence:

- SWE-bench Verified 95.0%; SWE-bench Pro 80.0%, standard max configuration with five trials.
- Terminal-Bench 2.1 84.3% at high across 445 trials; 20.9% of trials fell back to Opus 4.8, so this is a product-system result.
- FrontierCode v1 Main 46.3 score / 48.8 pass and Diamond 29.3 / 30.2 at xhigh, mean@5.
- CursorBench, older version, 72.9% at max in Cursor's production harness.

Sources: [Fable 5 launch](https://www.anthropic.com/news/claude-fable-5-mythos-5) and [Fable 5 system card](https://www-cdn.anthropic.com/57a52ea7d8f0e54e8a542e908266086df425cdf5/Claude%20Fable%205%20%26%20Claude%20Mythos%205%20System%20Card.pdf).

Do not compare the older CursorBench 72.9 directly with CursorBench 3.2 values.

### Opus 5 effort curves

The [Opus 5 system card](https://www-cdn.anthropic.com/ceaf5c7ff2783855203fde8208ec311252dced5b/Claude%20Opus%205%20System%20Card.pdf) reports:

| DeepSWE v1.1 effort | low | medium | high | xhigh | max |
|---|---:|---:|---:|---:|---:|
| Score | 57.7 | 66.9 | 68.0 | 69.7 | 68.8 |

| FrontierBench 0.1 effort | low | medium | high | xhigh | max |
|---|---:|---:|---:|---:|---:|
| Score | 25.0% | not disclosed | 39.0% | 44.4% | 43.0% |

FrontierCode 1.1 Main's best reported Opus 5 score was 53.4 and Extended's was 63.6; both best configurations were medium. Higher effort caused more out-of-scope changes that the grader penalized. This is direct evidence that Max is not monotonically best.

Other Opus 5 max standard results: SWE-bench Verified 96.0%, Pro 79.2%, Multilingual 89.5%, and Multimodal 59.4%.

Source: [Opus 5 launch](https://www.anthropic.com/news/claude-opus-5) and system card above.

### Sonnet 5 effort curves

From the [Sonnet 5 system card](https://www-cdn.anthropic.com/283ef97c476cf442c91d9a37d5b214242a55bb92/Claude%20Sonnet%205%20System%20Card.pdf):

| Effort | low | medium | high | xhigh | max |
|---|---:|---:|---:|---:|---:|
| FrontierCode v1 | 18.0 | 26.6 | 28.9 | 34.0 | 38.8 |
| CursorBench, older version | 47.7 | 54.9 | 57.0 | 59.0 | 61.2 |

Other official results: SWE-bench Verified 85.2%, Pro 63.2%, Multilingual 78.3%, Multimodal 28.1% in the standard max setup; Terminal-Bench 2.1 80.4% at xhigh across 89 tasks x five attempts.

Source: [Sonnet 5 launch](https://www.anthropic.com/news/claude-sonnet-5) and system card above.

### Haiku 4.5

The [Haiku 4.5 launch](https://www.anthropic.com/news/claude-haiku-4-5) reports:

- SWE-bench Verified 73.3% on the full 500 tasks, 50 trials, a bash/string-replace scaffold, and fixed 128K thinking budget.
- Terminal-Bench about 41.75% with Terminus-2 XML, five runs, and fixed 32K thinking.

These are fixed thinking-budget results, not effort-level results. Haiku has no low/medium/high/xhigh/max setting.

## Cost/quality sweep evidence

Anthropic's [optimizing cost and intelligence](https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence) guide reports an internal 482-problem SWE-bench Pro harness-compatible subset from 2026-08-04:

| Model/effort | Score | Estimated cost per solve |
|---|---:|---:|
| Fable 5.1 low | 88.6% | $0.54 |
| Fable 5.1 default/high | 92.1% | $1.19 |
| Opus 5 low | 84.0% | $0.25 |
| Opus 5 default/high | 91.7% | $1.01 |
| Sonnet 5 default/high | 77.4% | $0.84 |

The guide also reports an Opus-low-then-default-retry policy at about 93% for $0.45/task versus fixed default at 91.7% for $0.93 in that setup.

This subset is **not comparable to the public SWE-bench Pro leaderboard**. Opus default averaged two runs; reduced efforts used one. It is useful policy evidence that effort sweeps and retry routing can dominate fixed expensive settings, not a universal production estimate.

## Historical GPT models still visible locally

These are historical evidence and may not be available through ChatGPT-sign-in Codex now.

| Model/source configuration | SWE-bench Pro | Terminal-Bench | Other relevant result |
|---|---:|---:|---|
| GPT-5.5, xhigh | 58.6% | 82.7% on 2.0 | Expert-SWE internal 73.1%; OSWorld-Verified 78.7% |
| GPT-5.4, xhigh | 57.7% | 75.1% on 2.0 | OSWorld-Verified 75.0% |
| GPT-5.4 mini, xhigh | 54.4% | 60.0% on 2.0 | smaller tier |
| GPT-5.4 nano, xhigh | 52.4% | 46.3% on 2.0 | smallest tier |
| GPT-5.3-Codex, xhigh | 56.8% | 77.3% on 2.0 | OSWorld-Verified 64.7%, later 74.0% with image-resolution preservation |
| GPT-5.2-Codex, xhigh | 56.4% | 64.0% on 2.0 | OSWorld-Verified 38.2% |

Primary sources:

- [GPT-5.5 launch](https://openai.com/index/introducing-gpt-5-5/)
- [GPT-5.4 launch](https://openai.com/index/introducing-gpt-5-4/)
- [GPT-5.4 mini/nano](https://openai.com/index/introducing-gpt-5-4-mini-and-nano/)
- [GPT-5.3-Codex](https://openai.com/index/introducing-gpt-5-3-codex/)
- [GPT-5.2-Codex system card](https://cdn.openai.com/pdf/ac7c37ae-7f4c-4442-b741-2eabdeaf77e0/oai_5_2_Codex.pdf)

The current Codex model guide says GPT-5.4 and 5.4 mini retired from ChatGPT-sign-in Codex on 2026-08-31; 5.2 and 5.3-Codex were already deprecated there. API-key availability can differ. Historical benchmark presence never proves present entitlement.

## Routing guidance derived from the evidence

The statements below are inferences, not measured guarantees.

### Model class

- **Astra**: reserve for the hardest cross-cutting implementation, ambiguous diagnosis, integration, or judgment-heavy end-to-end role when access and quota justify it. Its largest published advantages are uneven across benchmarks.
- **Fable 5.1**: reserve for hours-long coding/research, very large context, or work that still fails on Opus 5 at high/xhigh. Start high; do not assume max.
- **Opus 5 / Sol**: strong frontier default for complex coding, orchestration, integration, and review. Effort sweeps show that medium/high can beat max on scope-sensitive tasks.
- **Terra / Sonnet 5**: default implementer class for well-scoped everyday coding and tool use.
- **Luna / Haiku 4.5**: bounded, repetitive, cheap, fast tasks with objective checks. Haiku's smaller context and absent effort knob are real constraints.
- **Legacy GPT models**: use only for a specific compatibility, historical comparison, or proven account route; otherwise prefer current replacements.

### Effort

- Start at medium/default for bounded tasks and high for hard coding/orchestration.
- Use low for simple, checkable work, triage, or the first stage of a retry policy.
- Use xhigh for long-horizon or high-failure-cost work after confirming the task benefits.
- Use max only for a genuine frontier bottleneck or measured gain. Max can overthink and can score below medium/xhigh on scope-sensitive benchmarks.
- Prefer staged escalation (`low/medium -> retry hard failures at high/xhigh`) when objective verification exists.
- Do not assign one exact multiplier for time, tokens, or quality to an effort name; no universal public mapping exists.

### Verification diversity

- Different runtime/provider for maker and checker gives stronger independence than two samples of one runtime.
- Same-runtime replicas are still useful to estimate stochastic variance.
- Compare evidence and reproduced tests, not majority vote.

## Benchmark traps

- Terminal-Bench 2.0, 2.1, 4.0, and Terminal-Bench-Science are different evaluations.
- AA Coding Agent Index v1.1 and v1.4 are not one continuous scale.
- CursorBench launch versions and CursorBench 3.2 are not directly comparable.
- OpenAI's 2026-07-08 [coding-evaluation audit](https://openai.com/index/separating-signal-from-noise-coding-evaluations/) estimated roughly 30% of public SWE-bench Pro tasks were broken and retracted its earlier recommendation to adopt that benchmark. Treat SWE-bench Pro as historical, lower-confidence evidence.
- Internal evaluations are not independently reproducible.
- Fable safeguards can zero or reroute tasks; Fable 5 Terminal-Bench 2.1 included substantial Opus fallback.
- A provider launch table is a system comparison, not necessarily a raw-model comparison. Prompts, tools, scaffolds, safety layers, and infrastructure differ.
- “Maximum at any effort” cannot be converted to a named effort result.
- Statistical noise matters. A one-point difference can be smaller than standard error.
- A model ID pins weights more than it pins the full serving system. Routing and safeguards can change.

## Known public gaps

As of the snapshot, no authoritative public source provides:

- a complete Astra Low/Medium/High/XHigh/Max coding grid;
- a complete Sol/Terra/Luna effort-by-effort coding grid;
- a stable public config encoding for Codex Ultra across every client/model;
- a complete current-model x five-effort x same-harness Claude grid;
- a benchmark for Claude Code `ultracode`;
- an effort grid for Haiku 4.5, because it does not support effort;
- universal latency, duration, or token multipliers by effort;
- a separate hard benchmark table for Astra Pro;
- proof of this account's access from the installed binary alone.

State these gaps instead of trying to satisfy a request for a complete table with invented values.
