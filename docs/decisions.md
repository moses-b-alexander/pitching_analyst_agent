# Product-owner decisions

Answers to the open questions in [`architecture.md`](architecture.md) ("Product-owner questions to resolve before coding").

Canonical behavior spec: [`skills/live-starting-pitching-analyst/SKILL.md`](../skills/live-starting-pitching-analyst/SKILL.md), mirrored from
[`live-pitching-analyst-chatgpt-plugin`](https://github.com/moses-b-alexander/live-pitching-analyst-chatgpt-plugin).
Where this file and SKILL.md disagree, this file records the agent-specific decision.

Decided 2026-09-30.

## Scope (revised 2026-09-30)

The agent does three things:

1. **Fetch and count.** Poll the MLB feed, compute the stat lines and any test numbers in code. The model never produces a number.
2. **Remember observations.** Save what the viewer types, indexed by team and starting pitcher. Nothing else is persisted.
3. **Talk.** One model call per message: condensed skill prompt + current stat lines + that pitcher's observations + baseline numbers.

Cut from the original architecture doc: MCP server, hypothesis ledger tables, summaries table, preference profile, per-role model routing and audit, provider telemetry, session export/import, pitch/snapshot storage, revision log. `architecture.md` is kept as the original handoff; where it disagrees with this file, this file wins.

| # | Question | Decision |
|---|---|---|
| 1 | Half-inning output initiation | **Auto-print the deterministic factual capsule only.** Exec thesis runs on request (or when a pending observation for that pitcher exists). No LLM cost on quiet innings. **Half-inning lag** per SKILL.md §1: after bottom N print the top-N pitcher; after top N+1 print the bottom-N pitcher (configurable). If the feed is failing or unavailable when a capsule is due, keep polling with backoff and print it once data arrives, never skip or guess. |
| 2 | Observation attribution | **User names the team or player explicitly.** Session keeps team membership for the two SPs only, so "Yankees" or "Schlittler" resolves to a starter. If no team/player is named, ask — do not guess from the active pitcher. |
| 3 | Stat-test execution | **Explicit request only.** The model classifies an observation and picks a test from a short fixed menu (returned as JSON); code runs the numbers; the model explains them. Never auto-run. |
| 4 | Cross-game personalization | **None.** Nothing carries between games: no preference profile, no carried hypotheses. Observations are game-scoped and cleared per #12. |
| 5 | Restart/recovery | **Required for V1, by refetching.** The MLB feed is cumulative, so a restart refetches the game and recomputes everything; saved observations are read back from SQLite. No game data is stored. |
| 6 | Source-conflict policy | **MLB live feed wins automatically.** The MLB boxscore endpoint corroborates the starter-exit line (ESPN dropped 2026-09-30: undocumented, blocked our client, adds nothing MLB lacks). `pitch_type`, ER, and scoring-dependent fields are revision-tracked and provisional until finalization; exit summary may ship with `mix provisional`. See source table below. |
| 7 | Reliever boundary | **Ingest always; warn once; allow on-demand.** Reliever requests get a one-time out-of-SP-scope warning, then are answered with the same tools. |
| 8 | Exit polling | **Fixed 10-minute cadence**, first check immediate. Stop at finalization; give up 2 h after game end and mark `unresolved`. |
| 9 | Exit notification | **Terminal prints the final line immediately** when source-complete, plus a model synthesis if a model is configured. |
| 10 | Model backend | **Open-weight models through one OpenAI-compatible endpoint.** Default is local Ollama (`http://localhost:11434/v1`); a hosted open-weight provider is the same adapter with a different `base_url` and key. One model, no per-role routing. With `model: null` the agent runs facts-only. Dev machine: RTX 4060 8 GB, 32 GB RAM, so 7-9B models at 4-bit fit on the GPU. |
| 11 | Historical-cache refresh | **Full re-pull every pregame.** Current regular season + current postseason per starter, downloaded fresh at session start; cache is the fallback if Savant is unavailable. |
| 12 | Persistence/privacy | **Local SQLite holding viewer observations only**, indexed by team and starting pitcher (text, game, team, pitcher, inning/half, time). A clear command deletes a game's observations; the same happens automatically 24 h after the game is first seen Final. No pitch data, snapshots, hypotheses, summaries, or preferences are stored. *(Revised 2026-09-30.)* |

## Sources (V1)

| Key | Source | Endpoint | Role |
|---|---|---|---|
| `mlb_live` | MLB Stats API live feed | `statsapi.mlb.com/api/v1.1/game/{pk}/feed/live` | **Authoritative live**: state, PBP, pitches, pitching changes, official scoring |
| `mlb_stats` | MLB Stats API | `/api/v1/schedule`, `/people/{id}`, `/game/{pk}/boxscore` | Game resolution, probables, handedness; box-line corroboration |
| `savant_csv` | Baseball Savant Statcast search | `baseballsavant.mlb.com/statcast_search/csv` | **Authoritative historical** season/postseason corpus |
| `savant_gf` | Baseball Savant gamefeed | `baseballsavant.mlb.com/gf?game_pk=` | V2 candidate: live bat-tracking (bat speed, swing path) for hitter-response questions |

Excluded: ESPN, HTML scrapers (CBS/Yahoo), FanGraphs. Retrosheet is not a live source (its event files are published after the season); we use only its hit **notation** (S8, D9, HR), built from the MLB feed.

### What each stat-line field comes from (verified, game 823652, both starters)

| Output | Live source | Matches Savant exactly? |
|---|---|---|
| Pitch-type counts / % | `mlb_live` `details.type.code` (same Statcast classification Savant publishes) | ✅ all 192 pitches |
| Hit types + fielder (`S8`, `D9`, `HR`) | `mlb_live` `result.eventType` + `hitData.location` | ✅ all 12 hits (vs Savant `events` + `hit_location`) |
| P · S/B · R/ER · H · K · BB · IP | `mlb_live` plays and pitches | ✅ equals official boxscore for all 7 pitchers |
| Velo, movement, release, plate location | `mlb_live` `pitchData` (converted, see `sources/mlb.py`) | ✅ 103/103 pitches |
