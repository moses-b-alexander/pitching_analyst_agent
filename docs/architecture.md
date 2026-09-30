# Live Baseball Pitching Analyst Agent — Architecture / Dev Handoff

## Product thesis

Build a small live baseball-analysis agent that improves active watching.

The product should let the user **keep eyes on the game** while offloading:

- live data retrieval,
- pitch/event normalization,
- per-pitcher state,
- statistical formalization,
- hypothesis bookkeeping,
- source reconciliation,
- and concise interpretation.

It should **not** become another dashboard that encourages constant screen switching.

The user's ideal interaction is casual:

> "his curve looks lower tonight"

The system should perform the rigorous work underneath:

> classify → define measurable quantity → choose baseline → determine exploratory/prospective status → optionally test → update pitcher thesis

V1 should be buildable quickly and should favor reliability and low interaction cost over feature breadth.

## Hard scope guard

This product is a **starting-pitcher analyst**, not a general live pitching engine.

- Resolve and track the true/named starters pregame.
- If an SP exits early, finalize that start normally; do not reinterpret the bulk reliever as a new starter.
- If the game is a bullpen game/opener game that does not fit the configured SP contract, flag the session as out-of-scope rather than silently adapting.
- Reliever data may continue to ingest for game-state integrity, but interpretive reliever analysis is not an automatic V1 responsibility.

---

# 1. Product requirements

## Fixed-format behavior

The following should be deterministic/stable across users and games:

### Pregame
- season corpus stats,
- current-postseason corpus stats,
- short executive priors.

### Half-inning
- two-line factual capsule,
- evolving executive thesis.

### Starter exit
- completeness-verified final starter line,
- whole-outing executive synthesis,
- candidate statistical questions.

### Statistical results
- sample size,
- baseline,
- effect size,
- exploratory/prospective status,
- test/result if run.

## Personalized behavior

Personalization should primarily affect:

- which informal observations are considered important,
- problem-class classification,
- suggested hypotheses,
- conditioning variables,
- historical baseline selection,
- statistical-test recommendations,
- interpretation depth,
- recurring user interests.

Do not personalize the basic stat-line schema.

---

# 2. Modes / lifecycle

Treat one watched game as a stateful session.

## Mode 0 — Pregame

Input:
- game identifier, or teams/date,
- starting pitchers if not discoverable.

Actions:
- resolve game,
- resolve starter IDs,
- load/cache regular-season corpus,
- load/cache current-postseason corpus,
- produce fixed pregame summary,
- initialize independent pitcher states.

Do not default to:
- opponent-specific splits,
- career history,
- arbitrary rolling windows.

Those are on-demand only.

---

## Mode 1 — Live starter watching

Continuously ingest live game state.

Do not call the LLM on every pitch.

The deterministic engine tracks:
- inning/half,
- pitcher,
- plate appearance,
- pitch number,
- pitch type,
- ball/strike result,
- location/shape fields,
- batted-ball outcome,
- pitching changes.

LLM calls occur only on:
- user observation,
- requested analysis,
- configured half-inning checkpoint,
- meaningful failure/reconciliation alert.

---

## Mode 2 — Observation formalization

User can type ordinary language.

Examples:

`his velo looks cooked`

`curve is buried way more`

`they're swinging flat`

`he keeps going sinker after 4s`

No command syntax required.

Pipeline:

1. capture raw observation verbatim,
2. attach timestamp/game/active pitcher/inning,
3. infer intended pitcher if obvious,
4. classify into one or more problem classes,
5. store as viewer observation,
6. determine whether it creates a hypothesis,
7. freeze the hypothesis boundary if appropriate,
8. optionally answer immediately,
9. preserve it for the next scheduled synthesis.

The model should use high interpretive effort here.

---

## Mode 3 — Statistical test

Can be triggered explicitly or suggested by the analyst.

System should convert an informal claim into:

- metric,
- observed window,
- baseline corpus,
- null,
- alternative,
- test family,
- effect measure,
- conditioning set,
- exploratory/prospective status.

The deterministic analytics layer should execute the numerical test where practical.

The LLM should interpret the result.

---

## Mode 4 — Starter exit

A pitching change creates an **exit candidate**, not immediately a final report.

Run a completeness gate first.

Once complete:
- freeze starter corpus,
- produce final line,
- produce whole-outing executive synthesis,
- offer a small set of high-value statistical questions,
- optionally produce a visual if it resolves a major thesis.

Return attention to live relievers afterward.

---

## Mode 5 — Postgame / post-start exploration

Allow deeper:
- location,
- movement,
- usage,
- sequencing,
- hitter response,
- trajectory,
- comparisons,
- visualization.

The user can query the full stored corpus without losing the live observations that generated hypotheses.

---

# 3. Architecture principle

Use a layered design:

```text
DATA SOURCES
    ↓
SOURCE ADAPTERS
    ↓
NORMALIZED GAME STORE
    ↓
EVENT / STATE ENGINE
    ↓
DETERMINISTIC ANALYTICS
    ↓
LLM INTERPRETER
    ↓
CLI / MCP / CHAT CLIENT
```

Do not let the LLM become the authoritative store or parser.

---

# 4. Source layer

Use adapters so source choices can change without changing analytics.

## Primary live source adapter

Preferred role:
- game state,
- play-by-play,
- pitch events,
- pitcher changes,
- box score,
- pitch count,
- official outcomes.

Likely source:
- MLB Gameday / MLB structured game feeds.

Important:
- treat undocumented endpoints as implementation details,
- isolate them behind an adapter,
- use fixtures/tests,
- tolerate schema changes.

## Statcast / Baseball Savant adapter

Use for:
- historical pitch corpus,
- release_speed,
- release_pos_x/z,
- release extension/position data when available,
- plate_x / plate_z,
- pitch_type,
- IVB / horizontal movement fields,
- batted-ball metrics,
- per-pitch historical baselines.

Baseball Savant publishes documentation for its Statcast CSV fields, making it a strong source for reproducible historical features.

## Secondary scoreboard adapter

Optional fallback:
- ESPN/CBS/Yahoo/etc.

Use for:
- cross-checking core game state,
- emergency fallback.

Do not make HTML scraping a core dependency if structured game data are available.

## Ethical scraping policy

If scraping is necessary:
- obey site terms and access rules,
- respect robots/rate limits where applicable,
- cache aggressively,
- use low request frequency,
- identify the client appropriately when required,
- never bypass authentication/paywalls/technical controls.

Prefer structured/public interfaces.

---

# 5. Source confidence and reconciliation

Every normalized value should carry provenance where feasible.

Example:

```python
ValueWithSource(
    value=83,
    source="mlb_gameday",
    observed_at=...,
    confidence="authoritative",
)
```

For fields that can change:
- pitch classification,
- earned runs,
- inherited-run attribution,
- official scoring,

retain revision metadata.

## Starter-exit completeness gate

Suggested state machine:

```text
ACTIVE
  ↓ pitching change detected
EXIT_CANDIDATE
  ↓ official/structured source confirms replacement
RECONCILING
  ↓ core line stable and inherited runners resolved
FINALIZED
```

### Core completeness fields

Require:
- outs/IP,
- pitches,
- strikes,
- hits,
- runs,
- earned runs,
- walks,
- strikeouts.

Recommended:
- HR,
- batters faced,
- pitch mix sum.

### Inherited runners

If runners remain:
- do not finalize R/ER,
- mark `awaiting_inherited_runner_resolution`,
- finalize after their plate appearances/inning determine responsibility.

### Exit polling

The ingestion/state engine should detect SP removal automatically from the live feed. A user exit signal is helpful context but is **not required**.

When `STARTER_EXIT_CANDIDATE` is entered, poll/reconcile approximately every **10 minutes** until the completeness gate passes.

Requirements:
- detect pitching changes automatically,
- first check immediately,
- exponential/fixed 10-minute cadence is acceptable for V1,
- stop polling after finalization,
- polling must not invoke the LLM unless interpretation is needed,
- source polling should be cheap and deterministic,
- user does not need to send another prompt.

If the start leaves inherited runners, continue polling until their responsibility is resolved.

### Cross-source rule

For V1, a reasonable gate:

- one authoritative structured source with internally consistent values, plus
- one secondary corroboration where available.

If authoritative source is delayed:
- expose `exit detected; line pending`,
- do not invent.

---

# 6. Normalized data model

Use SQLite for V1 unless a clear reason demands more.

DuckDB is attractive for postgame analytics, but SQLite is sufficient for the stateful service and easy to inspect.

A hybrid is possible later.

## Core tables

### games

```text
game_id
date
home_team
away_team
status
inning
half
created_at
updated_at
```

### players

```text
player_id
name
throws
bats
```

### pitcher_appearances

```text
appearance_id
game_id
pitcher_id
starter_bool
start_time
end_time
finalized_bool
outs
pitches
strikes
hits
runs
earned_runs
walks
strikeouts
```

### pitches

At minimum:

```text
game_id
appearance_id
pitcher_id
batter_id
at_bat_number
pitch_number
inning
half
balls
strikes
pitch_type
description
event
release_speed
release_pos_x
release_pos_z
release_extension
plate_x
plate_z
pfx_x / arm-side normalized movement
pfx_z / IVB-equivalent field
launch_speed
launch_angle
timestamp
source_revision
```

Keep raw-source JSON/snapshots separately for debugging.

### observations

```text
observation_id
game_id
pitcher_id
inning
half
raw_text
created_at
problem_classes
source="viewer"
```

### hypotheses

```text
hypothesis_id
pitcher_id
observation_id
statement
metric_definition
baseline_definition
generated_window
frozen_at
status
inference_type
test_window
```

`status` examples:
- candidate,
- frozen,
- collecting,
- tested,
- retired,
- unresolved.

`inference_type`:
- exploratory,
- prospective,
- sequential.

### summaries

Store generated:
- pregame,
- half-inning,
- starter-exit,
- postgame.

This allows replay and regression testing.

---

# 7. Inning-window semantics

The product treats **innings as meaningful narrative windows**.

If the user says:
- I2,
- I1–I3,
- I3–I5,

preserve that window.

Do not silently equalize by pitch count.

Pitch count is still stored and reported because:
- statistical power differs,
- uncertainty differs,
- fatigue interpretation differs.

Key principle:

> narrative window equality does not imply sample-size equality.

A 20-pitch three-inning span and a 60-pitch three-inning span remain the requested baseball windows, even though their estimates have different precision.

Do not combine across a pitching change.

---

# 8. Hypothesis/inference engine

This should be explicit code/state, not prompt-only memory.

## Problem classes

Use enum-like tags:

```python
USAGE_PROPORTION
CONTINUOUS_SHAPE
LOCATION_SPATIAL
SEQUENCE_TRANSITION
COMMAND_PRECISION
FATIGUE_TREND
HITTER_RESPONSE
MATCHUP_INTERACTION
TRAJECTORY_SEPARATION
```

One observation can have several classes, but pick a primary class.

## Exploratory / prospective logic

When an observation is generated from window A:

```text
A = generating window
```

Any test on A is exploratory.

If the hypothesis is frozen before window B begins:

```text
B = prospective window
```

B can support prospective inference.

Examples:

```text
OBS after I2
generated_window = I2
test_window = I3–I5
```

or:

```text
OBS after I1–I3
generated_window = I1–I3
test_window = I4–I6 if pitcher remains
```

Pitch count does not determine prospective status.

## Statistical engine

V1 methods:

- exact binomial,
- Fisher exact,
- difference in proportions,
- bootstrap CI,
- empirical permutation/resampling,
- simple linear regression for within-outing trend,
- conditional transition proportions.

Avoid building a giant statistical framework.

Use SciPy / statsmodels / NumPy as appropriate.

Every test result object should return:

```python
{
    "n": ...,
    "baseline_n": ...,
    "estimate": ...,
    "baseline_estimate": ...,
    "effect": ...,
    "ci": ...,
    "p_value": ...,
    "method": ...,
    "inference_type": ...,
    "conditioning": ...
}
```

The LLM receives this structured result and explains it.

---

# 9. Deterministic output compositor

The fixed factual lines should **not** be free-form LLM output.

Generate them in code.

Example:

```text
Line: 17 P · 11S/6B | 1 R · 3 H | 2 K · 1 BB
Mix: 4S 8 (47%) · SI 3 (18%) · FC 2 (12%) · CU 4 (24%)
Hits: S8 · S7 · D9
```

Benefits:
- reproducibility,
- no hallucinated counts,
- stable UI,
- easy tests.

The LLM writes only:
- executive thesis,
- observation classification,
- statistical interpretation,
- next meaningful question.

---


## Executive-summary annotation legend

Hardcode a two-axis semantic legend into the compositor/prompt contract.

### Viewer axis — numeric

```text
¹ viewer observation supported/consistent with current data
² viewer observation partially supported / mixed
³ viewer observation not supported / current data point the other way
⁴ viewer observation unresolved / insufficient data
```

### Analyst axis — alphabetic

```text
ᵃ analyst thesis strengthened / supported
ᵇ analyst thesis partially supported / materially qualified
ᶜ analyst thesis weakened / current evidence points away from it
ᵈ analyst thesis corrected / reframed
ᵉ analyst thesis unresolved / insufficient data
```

The ordering on each axis runs from stronger agreement/support toward stronger disagreement/correction, with unresolved placed last.

The LLM may attach:
- a number,
- a letter,
- or both

to a thesis bullet.

Examples:

```text
¹ᵃ   viewer observation supported; analyst thesis strengthened
²ᵇ   both are only partially supported
³ᶜ   viewer observation unsupported; analyst thesis weakened
ᵈ    analyst-only correction
⁴ᵉ   both unresolved
```

The legend text itself should be pasted **deterministically** at the end of the executive summary so semantics remain stable across model backends.

Do not treat the axes as mathematically precise scores. They are a compact ordinal reading aid.

# 10. LLM interpreter

Use a **fully provider-agnostic model abstraction**.

The architecture must support:
- hosted proprietary APIs,
- local/open-weight models,
- quantized inference,
- remote OpenAI-compatible endpoints,
- Anthropic-compatible/native endpoints,
- or future model backends.

No core state, analytics, or source-reconciliation logic may depend on a specific model vendor.


```python
class AnalystLLM(Protocol):
    async def interpret_observation(...): ...
    async def summarize_checkpoint(...): ...
    async def synthesize_starter_exit(...): ...
    async def propose_tests(...): ...
```

Implementations could include:
- Anthropic,
- OpenAI,
- local/open model later.

Do not couple application state to one provider.

Given the intended use, model quality matters most for:
- informal observation interpretation,
- competing hypotheses,
- concise thesis updating.

A cheaper/faster model can potentially handle simple formatting, but deterministic code should already own most formatting.

## Model-role routing

Expose three configurable **analysis roles** consistently across pregame, live, starter-exit, and postgame modes:

```yaml
models:
  exec: anthropic:claude-sonnet-4-6
  facts: deterministic
  stats: openai:gpt-5.6-sol
```

### `exec`
Used for:
- executive summaries,
- thesis continuity,
- interpreting viewer observations qualitatively,
- concise starter-exit synthesis.

### `facts`
Default: `deterministic`.

Owns:
- factual stat-line composition,
- pitch mix counts/percentages,
- Retrosheet-style hit line,
- source reconciliation display.

This role **must not depend on an LLM by default**.

Optionally allow a model backend for:
- ambiguous text parsing,
- source-repair suggestions,
- validation assistance.

Even then, deterministic reconciled data remain authoritative and the model may not invent missing facts.

### `stats`
Used for:
- observation formalization,
- null/alternative construction,
- test selection,
- deeper statistical questioning,
- interpretation of deterministic numerical test results.

The same role mapping applies in:
- pregame,
- live,
- starter-exit,
- postgame.

## Runtime model overrides

Allow model-role changes:
- in config/code defaults,
- at session start,
- during pregame,
- during live play,
- during postgame conversation.

Examples:

```text
use claude-sonnet-4-6 for exec
use openai:gpt-5.6-sol for stats
set facts deterministic
```

A role override remains active until:
- explicitly changed,
- session reset,
- or configuration policy says otherwise.

Persist the resolved provider/model ID in session state so outputs can be audited.

## Invalid or ambiguous model workflow

Never silently reinterpret an invalid/ambiguous model name.

Resolution flow:

1. parse provider/model alias,
2. check configured provider registry,
3. check model availability/capability if the provider supports discovery,
4. if there is exactly one safe resolution, show the resolved canonical ID,
5. if ambiguous/invalid/unavailable, **push back and ask for clarification**,
6. retain the currently active model for that role until resolved.

Examples requiring clarification:

- `use sonnet` when multiple Sonnet aliases are configured,
- `use gpt 5` when several compatible IDs exist,
- a local model name that matches multiple quantizations,
- a model that exists but is not configured for the required provider.

Do not auto-fallback to a more expensive model without an explicit configured fallback policy.


## Prompt context

Provide the LLM only the relevant state:

- pitcher season/postseason prior,
- last few inning capsules,
- active theses,
- observations for this pitcher,
- test metadata/results,
- current checkpoint data.

Do not resend the whole game transcript every call.

---

# 11. Cost / latency design

Never call the LLM once per pitch.

Suggested call triggers:

- pregame: 1 call,
- user observation: optional call,
- half-inning analysis: 1 call only when requested/configured,
- explicit statistical test: 1 interpretation call after deterministic compute,
- starter exit: 1 synthesis call,
- postgame: on demand.

Cache:
- season pitch data,
- postseason pitch data,
- pitcher metadata,
- historical feature aggregates.

This makes model cost small relative to a per-pitch agent.

---

# 12. State engine

Use an explicit event-driven state machine.

Useful events:

```text
GAME_STARTED
HALF_INNING_ENDED
PITCH_RECORDED
PA_ENDED
PITCHER_CHANGED
STARTER_EXIT_CANDIDATE
STARTER_FINALIZED
USER_OBSERVATION
USER_TEST_REQUEST
GAME_ENDED
```

User observation events should never block ingestion.

---

# 13. CLI V1

A terminal interface is probably the fastest useful prototype.

Example:

```bash
python agent.py --game 849851
```

Potential output:

```text
Connected: BOS @ NYY
SP: Payton Tolle vs Cam Schlittler
Pregame summary ready.
```

The process polls in the background while stdin accepts natural text:

```text
> his curve looks way lower than normal
OBS saved: Schlittler
Class: location/proportion
Hypothesis frozen after T2; prospective window begins T3.
```

At checkpoint:

```text
SCHLITTLER T3
Line: ...
Mix: ...

EXEC
- ...
- ...
```

## CLI commands

Commands can exist for power users but should never be required:

```text
/test <text>
/compare <text>
/post <text>
/status
/quit
```

Plain text defaults to an observation/question interpreted by the LLM.

Conversation/state phrases should be understood naturally rather than requiring commands:
- `game starting` → freeze pregame priors and enter live mode,
- `game ended` → enter postgame conversation mode,
- natural replies to summaries remain ordinary conversation.

The structured protocol is internal; the user's input surface stays informal.

---

# 14. MCP interface

Build the analytics engine independently, then expose it through MCP.

As of Sep 2026, the official MCP Python SDK v2 is the stable line and supports:
- tools,
- resources,
- prompts,
- stdio,
- Streamable HTTP.

That makes one local service usable from compatible LLM hosts.

## Suggested MCP tools

```text
resolve_game
get_game_state
get_pitcher_state
get_half_inning_capsule
record_observation
formalize_observation
run_test
get_starter_exit_summary
compare_pitchers
```

## Suggested MCP resources

```text
baseball://game/{game_id}
baseball://game/{game_id}/pitcher/{pitcher_id}
baseball://game/{game_id}/hypotheses
baseball://skill/live-pitching-analyst
```

Keep interpretation prompts either:
- in the app repository,
- exposed as MCP prompts,
- or supplied by the LLM host.

For Claude Code, a local stdio MCP server is an attractive first integration.

For a remote/shared service, use Streamable HTTP.

---

# 15. ChatGPT integration

Keep the core service transport-agnostic.

Possible interaction patterns:

## Manual skill + live service
- ChatGPT receives the Markdown skill,
- MCP/plugin/tool exposes deterministic baseball state,
- ChatGPT performs interpretation.

## Chat-only fallback
- User brings the skill into a normal chat,
- assistant uses web/live tools directly,
- state is conversational rather than service-backed.

The architecture should not depend on ChatGPT-specific UI behavior.

---

# 16. Historical corpus cache

Do not re-download a full season every checkpoint.

For each starter before first pitch:

1. resolve pitcher ID,
2. load current-season Statcast corpus,
3. load current postseason corpus,
4. normalize features,
5. cache locally.

Useful precomputed aggregates:

```text
pitch type × handedness
pitch type × count bucket
pitch type × inning/pitch-number bucket
zone region
release-speed distribution
IVB distribution
horizontal-movement distribution
release position
transition matrix
```

Keep raw pitches so new questions can still be computed.

---

# 17. Feature definitions

Centralize feature definitions.

Examples:

```python
is_below_zone
is_heart
is_edge
is_high
is_outer_to_batter
is_inner_to_batter
is_backdoor_candidate
is_frontdoor_candidate
```

Do not scatter zone definitions across notebooks.

Version them.

A user's informal concept such as "1.5 ball heights into the zone" should be translatable into a documented feature definition.

---

# 18. Hitter-response support

V1 can remain modest.

Track:
- swing/take,
- contact/whiff,
- foul,
- launch angle,
- exit velocity,
- batted-ball class.

Do not attempt computer vision from broadcast video in V1.

The LLM may interpret viewer observations like "flat swing," but deterministic confirmation should use available Statcast swing/batted-ball metrics where possible.

---

# 19. Visualization

Not a V1 priority.

No ordinary live half-inning visuals.

At starter exit or postgame, optional plotting functions may support:
- movement/velocity,
- location,
- conditional usage/decision behavior,
- within-outing trends.

Selection remains analyst/user-driven.

Implement plotting after the text workflow is stable.

---

# 20. Reliability / failure modes

## Live source lag
Behavior:
- retain observations,
- print `exact mix pending`,
- retry source later.

## Conflicting pitch classifications
Behavior:
- store revision,
- do not silently mutate historical summaries,
- mark older summary classification as provisional if material.

## Inherited runners
Behavior:
- hold starter final R/ER until resolved.

## Source outage
Behavior:
- degrade to secondary source,
- identify reduced confidence,
- continue accepting user observations.

## LLM outage / API cost issue
Behavior:
- ingestion continues,
- factual capsules remain available,
- observations queue for later interpretation.

This is important: **the baseball data service should remain useful without the LLM**.

---


# Provider usage / quota observability

Treat provider usage and limits as a **capability**, not an assumption.

Define an optional interface such as:

```python
class ProviderTelemetry(Protocol):
    async def request_usage(self) -> RequestUsage: ...
    async def rate_limits(self) -> RateLimitState | None: ...
    async def account_usage(self) -> AccountUsage | None: ...
    async def account_costs(self) -> AccountCosts | None: ...
    async def configured_spend_limits(self) -> SpendLimitState | None: ...
```

Possible states:
- supported,
- unsupported,
- permission_denied,
- unavailable,
- stale.

## OpenAI example

OpenAI inference responses expose request token usage, and API responses expose rate-limit headers such as request/token limits, remaining capacity, and reset times.

OpenAI also provides organization-level Usage and Costs APIs, but these require appropriate admin credentials/permissions.

Project/organization spend limits and dashboard visibility are permission-controlled. Do **not** assume that a normal inference key can read every limit configured in the web dashboard.

Therefore:
- always log per-request token usage when returned,
- log rate-limit headers when returned,
- optionally query Usage/Costs with a separate admin credential if the user configures one,
- treat dashboard-configured hard/soft spend limits as visible only when the provider exposes them to the credential in use,
- handle quota/spend-limit API errors explicitly.

## Other providers / local models

Implement the same interface opportunistically.

For local/open-weight inference:
- there may be no monetary quota,
- expose local telemetry such as latency, tokens/sec, VRAM/RAM use when available,
- do not fake an API-style spend limit.

The agent UI should distinguish:
- **request rate limit**
- **account/project usage**
- **monetary spend**
- **configured spend cap**
- **local compute capacity**


# 21. Replayability and testing

A major engineering advantage is that baseball games are replayable event streams.

Store raw source snapshots/events so a completed game can be replayed through the state engine.

## Unit tests

Test:
- inning boundary detection,
- pitching changes,
- inherited runner accounting,
- pitch-mix totals,
- balls/strikes,
- partial innings,
- doubleheaders/game resolution,
- pitch classification revisions.

## Golden-output tests

Given a frozen game fixture:
- exact factual capsule must match expected text,
- starter final line must match,
- prospective/exploratory flags must be deterministic.

## LLM regression tests

Do not assert exact prose.

Assert structural properties:
- <= configured thesis count,
- no unsupported factual numbers,
- correct pitcher,
- correct hypothesis status,
- cites provided evidence.

---

# 22. Suggested repository

```text
live-pitching-agent/
├── README.md
├── pyproject.toml
├── .env.example
├── config.yaml
├── agent.py
├── server.py
├── src/
│   └── pitching_agent/
│       ├── config.py
│       ├── models.py
│       ├── state.py
│       ├── events.py
│       ├── store.py
│       ├── compositor.py
│       ├── sources/
│       │   ├── base.py
│       │   ├── mlb.py
│       │   ├── savant.py
│       │   └── secondary.py
│       ├── analytics/
│       │   ├── features.py
│       │   ├── windows.py
│       │   ├── tests.py
│       │   ├── transitions.py
│       │   └── trajectories.py
│       ├── llm/
│       │   ├── base.py
│       │   ├── anthropic.py
│       │   ├── openai.py
│       │   └── prompts.py
│       ├── services/
│       │   ├── ingestion.py
│       │   ├── reconciliation.py
│       │   ├── hypothesis.py
│       │   └── analyst.py
│       └── mcp/
│           └── tools.py
├── skills/
│   └── personal_live_pitching_analyst_skill.md
├── tests/
│   ├── fixtures/
│   ├── test_state.py
│   ├── test_reconciliation.py
│   ├── test_windows.py
│   └── test_compositor.py
└── data/
    ├── cache/
    └── baseball.sqlite
```

---

# 23. V1 recommendation

Build only enough to reproduce the workflow already proven useful in chat.

## V1

- CLI process,
- game resolution,
- one primary live adapter,
- Savant historical cache,
- SQLite,
- pitch/event normalization,
- two-line deterministic capsule,
- independent SP state,
- half-inning events,
- natural-language observation capture,
- problem classification via LLM,
- hypothesis ledger,
- basic stats engine,
- starter-exit completeness gate,
- starter-exit synthesis,
- provider abstraction,
- replay fixtures.

This is a reasonable small prototype.

## V1 acceptance criteria

During a live game the user can:

1. start `agent.py`,
2. receive a pregame starter overview,
3. type short observations without syntax,
4. receive correct lagged factual capsules,
5. receive concise evolving theses,
6. ask a statistical question,
7. have the system distinguish exploratory vs prospective data,
8. receive a source-complete starter-exit synthesis,
9. continue watching without managing state manually.

---

# 24. V2 — "good enough"

Only add features that prove useful in V1:

- MCP server for Claude/ChatGPT-compatible hosts,
- better source failover/reconciliation,
- robust historical baseline conditioning,
- richer test catalog,
- automatic candidate-test ranking,
- optional starter-exit/postgame plots,
- session persistence across postseason games,
- user preference profile for statistical questions,
- stronger replay/regression suite.

Do not build:
- a large web dashboard,
- computer vision,
- pitch prediction models,
- autonomous betting/prediction features,
- elaborate multi-agent orchestration,

unless real use demonstrates a need.

---


# Product-owner questions to resolve before coding

Start the next development conversation by answering these. They intentionally remain open requirements.

1. **Half-inning output initiation**
   - auto-print factual capsule + exec when ready,
   - or remain silent until requested?
   - Can this differ between terminal and chat clients?

2. **Observation attribution**
   - default an unqualified observation to the currently active SP?
   - What confidence threshold should trigger a clarification instead?

3. **Stat-test execution**
   - suggest freely but execute only on explicit request,
   - or auto-run cheap pre-frozen prospective tests when their window completes?

4. **Cross-game personalization**
   - persist analytical preferences/problem classes/baseline choices?
   - Which preferences should never persist?
   - Hypotheses themselves should generally remain game/pitcher scoped.

5. **Restart/recovery**
   - if `agent.py` restarts midgame, should it automatically reconstruct game state and restore observations/hypotheses from SQLite?
   - Required for V1 or acceptable V2?

6. **Source-conflict policy**
   - authoritative MLB field wins automatically,
   - or hold/reconcile for certain fields?
   - Which fields can remain provisional?

7. **Reliever boundary**
   - raw ingestion only after both SPs exit,
   - or allow explicit on-demand reliever analysis outside this SP skill?
   - Should the product actively warn when a request crosses the SP-only scope?

8. **Polling**
   - 10-minute exit-reconciliation cadence acceptable?
   - faster only while inherited runners are unresolved?
   - maximum retries / timeout behavior?

9. **Notification behavior**
   - when an exit line becomes source-complete, should terminal print immediately?
   - should MCP expose a resource/event and let the host decide how to surface it?

10. **Model backend**
    - preferred initial provider/API for development,
    - requirement for OpenAI-compatible local endpoints,
    - target quantized open-weight model sizes/hardware,
    - minimum interpretation quality before fallback to a hosted model?

11. **Historical-cache boundaries**
    - full current regular season + current postseason by default is agreed;
    - how aggressively should old cached pitches be refreshed/reclassified?

12. **Persistence/privacy**
    - local-only SQLite by default?
    - export/import session files?
    - should raw user observations persist indefinitely or be game-scoped by default?

# 25. Implementation priorities

Order of work:

```text
1. Reliable live ingestion
2. Normalized event state
3. Deterministic factual capsule
4. Pitcher-specific state / inning windows
5. Observation capture
6. LLM interpretation
7. Starter-exit reconciliation
8. Statistical tests
9. MCP wrapper
10. Optional visualization
```

If step 1–4 are unreliable, no amount of LLM intelligence fixes the product.

---

# 26. Product principle

The product should feel like a knowledgeable analyst sitting next to the viewer, not a terminal full of baseball numbers.

The user watches.

The agent:
- remembers,
- retrieves,
- formalizes,
- checks,
- interprets,
- and only interrupts when useful.

That is the feature.
