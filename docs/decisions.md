# Product-owner decisions

Answers to the open questions in [`architecture.md`](architecture.md) ("Product-owner questions to resolve before coding").

Canonical behavior spec: [`skills/live-starting-pitching-analyst/SKILL.md`](../skills/live-starting-pitching-analyst/SKILL.md), mirrored from
[`live-pitching-analyst-chatgpt-plugin`](https://github.com/moses-b-alexander/live-pitching-analyst-chatgpt-plugin).
Where this file and SKILL.md disagree, this file records the agent-specific decision.

Decided 2026-09-30.

| # | Question | Decision |
|---|---|---|
| 1 | Half-inning output initiation | **Auto-print the deterministic factual capsule only.** Exec thesis runs on request (or when a pending observation for that pitcher exists). No LLM cost on quiet innings. |
| 2 | Observation attribution | **User names the team or player explicitly.** Session keeps team membership for the two SPs only, so "Yankees" or "Schlittler" resolves to a starter. If no team/player is named, ask — do not guess from the active pitcher. |
| 3 | Stat-test execution | **Explicit request only.** Suggest freely; never auto-run, including pre-frozen prospective tests. |
| 4 | Cross-game personalization | **Preferences persist; hypotheses don't.** Persist favored problem classes, baseline choices, test preferences, zone-definition variants. Observations and theses are game/pitcher-scoped. Hypotheses, including frozen ones, are cleared with the game (#12), so they do **not** carry into the pitcher's next start (overrides SKILL.md §5's carry-forward option). |
| 5 | Restart/recovery | **Required for V1.** On restart, rebuild game state from the replayable MLB feed and restore observations/hypotheses from SQLite. |
| 6 | Source-conflict policy | **MLB live feed wins automatically.** MLB boxscore endpoint + ESPN corroborate the starter-exit line. `pitch_type`, ER, and scoring-dependent fields are revision-tracked and provisional until finalization; exit summary may ship with `mix provisional`. See source table below. |
| 7 | Reliever boundary | **Ingest always; warn once; allow on-demand.** Reliever requests get a one-time out-of-SP-scope warning, then are answered with the same tools. |
| 8 | Exit polling | **Fixed 10-minute cadence**, first check immediate. Stop at finalization; give up 2 h after game end and mark `unresolved`. |
| 9 | Exit notification | **Terminal prints final line + exit synthesis immediately** when source-complete. MCP (V2) exposes a resource and lets the host decide. |
| 10 | Model backend | **Deferred** — separate discussion. No `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` in the dev environment as of this date. Core must run with no LLM (facts role is deterministic). |
| 11 | Historical-cache refresh | **Full re-pull every pregame.** Current regular season + current postseason per starter, downloaded fresh at session start; cache is the fallback if Savant is unavailable. |
| 12 | Persistence/privacy | **Local-only SQLite; per-game analysis is disposable; export/import in V1.** A clear command deletes a game's observations, hypotheses (incl. frozen), and summaries; the same happens automatically 24 h after the game is first seen Final. Pitch data, revision history, and cross-game preferences are kept. Raw feed snapshots are pruned to the latest once the game is Final. *(Revised 2026-09-30; originally "keep forever".)* |

## Sources (V1)

| Key | Source | Endpoint | Role |
|---|---|---|---|
| `mlb_live` | MLB Stats API live feed | `statsapi.mlb.com/api/v1.1/game/{pk}/feed/live` | **Authoritative live**: state, PBP, pitches, pitching changes, official scoring |
| `mlb_stats` | MLB Stats API | `/api/v1/schedule`, `/people/{id}`, `/game/{pk}/boxscore` | Game resolution, probables, handedness; box-line corroboration |
| `savant_csv` | Baseball Savant Statcast search | `baseballsavant.mlb.com/statcast_search/csv` | **Authoritative historical** season/postseason corpus |
| `savant_gf` | Baseball Savant gamefeed | `baseballsavant.mlb.com/gf?game_pk=` | Optional second opinion on live pitch_type/shape |
| `espn` | ESPN site API | `site.api.espn.com/apis/site/v2/sports/baseball/mlb/summary?event=` | Secondary box-line corroboration / fallback |

Excluded: HTML scrapers (CBS/Yahoo), FanGraphs, Retrosheet.
