# Ice WARriors — NHL Player Value & Career Projections

A WAR-style valuation of every NHL skater and goalie (MoneyPuck data, 2008–2025 seasons) plus real-age rest-of-career projections for active players, delivered as two interactive dashboards, downloadable data, and a reusable data-loading skill.

Everything here is a principled **v1** — honest about its assumptions, not an oracle. Read the *Limitations* section before quoting a number.

---

## What's in this folder

| File | What it is |
|---|---|
| `ice_warriors_dashboard.html` | **Start here.** Self-contained interactive dashboard — sortable/searchable player rankings on the left, per-player valuation and career-projection curves on the right. No internet needed; open in any browser. |
| `ice_warriors_shot_explorer.html` | The performance data underneath the valuation. Every skater and goalie season 2008-09 through 2025-26, **regular season and playoffs**, with situational splits, danger-tier expected goals, career shot maps on real rink coordinates, and a Projections tab carrying this same WAR model. Self-contained. |
| `career_projections.csv` | Every active player: current age, talent rate, projected peak, remaining-career WAR (with range), projected seasons, career-to-date and projected-total WAR. |
| `player_value_history_skaters.csv` | Every skater-season with all five WAR components, GAR, and WAR. |
| `player_value_history_goalies.csv` | Every goalie-season with GSAx and WAR. |
| `methodology.md` | Full methodology writeup — component construction, calibration, aging/projection, and detailed limitations. |
| `moneypuck-nhl.skill` | Reusable Claude skill that loads and analyzes the MoneyPuck data (handles all the file quirks). Install it to rerun analysis on future data. |
| `scripts/shot_explorer/` | The shot explorer's build pipeline — `build.py`, the UI template it fills, and `PAYLOAD.md` documenting the payload format. One command rebuilds the explorer from scratch. |
| `dashboard_data.json` | The data the dashboard reads (already embedded in the HTML; here for reuse). |

---

## Quick start

Open `ice_warriors_dashboard.html` in a browser. Search a player or sort the list by remaining-career WAR, projected total, talent, current-season WAR, or career-to-date. Click any player to see their stat tiles and the actual-vs-projected WAR curve.

Open `ice_warriors_shot_explorer.html` when you want the season-by-season record rather than the projection — who actually did what, at which strength, in which season, and from where on the ice.

---

## The model in brief

**Value (WAR).** Each skater gets a Goals-Above-Replacement figure from five components — even-strength offense, even-strength defense (on-off isolated), power play, penalty kill, and penalty differential — each regressed for reliability, then divided by 6 goals per win. Goalies use GSAx (expected minus actual goals against). The scale matches public models: replacement ≈ 0, average regular ≈ 1, elite ≈ 5–7. Validated against known leaderboards (McDavid tops his MVP year; Hellebuyck tops goalies).

**Projections.** Anchored to each player's **real age** (from birthdates). The skater aging curve is fit from the data and peaks at **25**; goalies use a later-peaking curve (**27**) imposed from domain knowledge because their sample is too noisy to estimate. Games played and survival (staying in the league) are conditioned on a player's **role** (schedule-normalized games tier) *and* age, and that role is evolved forward each season so it decays realistically. Current talent is a recency- and games-weighted average of recent seasons, regressed toward the **mean of players in the same role** — so an established full-timer isn't dragged toward a league median full of call-ups.

---

## How to read the dashboard

- **The projected line is talent *level*** — expected WAR per full 82-game season at each age. It follows the aging curve, so young players rise toward a peak and older players decline. A dip at the handoff from the last actual season is **regression to the mean** (one or two seasons is thin evidence).
- **Remaining-career WAR** (the headline tile) is *lower* than simply adding up that line, because it also discounts for games missed and the chance of retirement each future year.
- **Bands widen with time** — projecting a decade out is mostly uncertainty, and the chart shows it.
- An **"est. age"** flag means no birthdate was on file and age was estimated from experience (~2% of players).

---

## The shot explorer

Where the main dashboard answers *what is this player worth going forward*, the explorer answers *what has actually happened*. Three tabs.

**Skaters** and **Goalies** are one row per player per season, filtered by season, situation (all / 5v5 / power play / penalty kill), team, minimum games, and regular season vs. playoffs. Skaters add a position filter and a totals/per-60 basis toggle. Clicking any row opens a career view — season log, career chart, and a **shot map** on a half rink, coloured by that player's goals or saves above expected per shot versus the league rate in the same 6- to 8-foot cell, with a second mode for shot volume versus the league mix.

**Projections** is this same WAR model: 1,039 players ranked by remaining-career WAR, projected total, current talent, 2025-26 WAR, or career-to-date, with the projected talent path and its range.

The halves cross-link on MoneyPuck `playerId`, so no name matching is involved. Open a player in the shot explorer and a banner shows their remaining WAR, peak level and age, and talent rate, with a button into the projection; the projection has a button back to their shot map. The **`WAR`** column in the skater and goalie tables tracks the season filter — it shows that player's actual WAR for whichever season is selected. With **All seasons** selected there's no single season to show, so it falls back to 2025-26 WAR. It reads `—` for a season the model has no actual WAR for, and for players the model has no projection for at all.

**Coverage against the model:** 98 of 98 goalies and 859 of 941 skaters. The 82 misses are all real players who never cleared the 100-minute season cutoff (best single season: median 42 minutes, max 98), so their Projections entry says "no shot-explorer rows" rather than offering a dead link.

**Where the numbers come from.** Goalies are built entirely from shot-level data, because the goalie aggregates are regular-season only and carry no coordinates. Skater regular seasons come from the `skaters_*` aggregates (assists, ice time, and on-ice numbers don't exist at shot level); skater playoffs are shot-derived. Danger tiers are recovered from raw shots using expected-goal cutoffs of 0.08 and 0.20, which reproduce MoneyPuck's own tier counts to within about 0.5%. Situations are labelled from each player's own side, so a goalie's "penalty kill" means his team is short a skater.

### Rebuilding it

```bash
export MPDATA_RELEASE_BASE=https://github.com/mattkravec/moneypuck-data/releases/download/data-v2
python scripts/shot_explorer/build.py \
  --war ice_warriors_dashboard.html \
  --out ice_warriors_shot_explorer.html
```

First run downloads ~290 MB of shot files into `~/.cache/moneypuck` and takes a few minutes; later runs reuse the cache and rebuild in about 30 seconds. Requires `pandas` and `pyarrow`. The `--war` flag reads the projections straight out of the dashboard's embedded `const DATA` block, so `dashboard_data.json` isn't needed. Prefer the HTML over the JSON: `dashboard_data.json` has lost the accented characters in ~14 player names. Drop the flag and the build still succeeds — the Projections tab then comes up empty and the `WAR` column reads `—` for everyone.

Data is found in `--data-dir`, then `$MPDATA_DIR`, then the cache; anything missing is fetched from `$MPDATA_RELEASE_BASE`. `--min-map-shots N` drops shot maps below N career shots, which is the main lever on payload size; `--first-season` / `--last-season` narrow the history. See [`scripts/shot_explorer/PAYLOAD.md`](scripts/shot_explorer/PAYLOAD.md) for the payload format and the data quirks the build handles.

---

## Data & the skill

The analysis is built on the MoneyPuck NHL dataset (per-skater, per-goalie, per-line, per-team, and per-shot files) plus `allPlayersLookup.csv` for birthdates. The `moneypuck-nhl.skill` loads it and handles the quirks (schema drift, playoff rows in shot files, duplicate headers, situation splits). It can source data three ways, in priority order:

1. **A local folder via `MPDATA_DIR`** — point it at a Google Drive for Desktop synced copy of the data folder.
2. **A GitHub Release via `MPDATA_RELEASE_BASE`** (`MPDATA_GITHUB_BASE` is accepted as a synonym) — the current `data-v2` release holds 28 Parquet assets, ~380 MB total. Release assets allow 2 GB per file and resolve to a host the sandbox can reach, which normal repo files over 100 MB and Git LFS do not.
3. **Direct uploads** — files in the session are used with no setup.

Data is stored as **Parquet**, not CSV: roughly 10× smaller, dtypes preserved, and column pushdown makes subsetted reads about 14× faster (a 4-column shots read is 0.55 s versus 7.5 s for all 137). The loaders accept `.parquet`, `.csv`, and `.csv.gz` interchangeably and prefer Parquet when both exist.

See `references/google_drive.md` inside the skill for the full Drive workflow. Note: a skill *script* cannot download from Google Drive at runtime (the sandbox can't reach Google), so Drive data is sourced via a local sync, not an API call.

---

## Reproducing & extending

The WAR value files (`player_value_history_*.csv`) are the durable output of the value model. The projection layer (aging curves, role-conditioned survival/games, talent regression, forward simulation) is rebuilt from those files.

The **shot explorer is fully reproducible** — its pipeline lives in this repo at [`scripts/shot_explorer/`](scripts/shot_explorer/), with the UI template beside it and the payload format documented in [`PAYLOAD.md`](scripts/shot_explorer/PAYLOAD.md). One command rebuilds it from scratch.

**Heads-up:** the *projection* scripts still live in a temporary workspace that resets between sessions, so the projection pipeline — including the role-conditioned prior and the manually-added Barkov — is **not yet baked into anything permanent**. Folding it into the skill the same way is the remaining step, and it's what would let both dashboards rebuild from one command on a new data drop.

---

## Limitations — read before quoting a number

- **Not RAPM-isolated.** On-off differentials reduce but don't eliminate teammate, competition, and deployment bias in the defensive components.
- **Very young players are speculative.** A one- or two-season talent estimate extrapolated across a 15–20 year career; the bands are wide for a reason, and the deep tails carry the most model risk.
- **Goalie aging is a domain prior, not data.** The 27 peak and gentle slope are imposed because the goalie sample is too thin and noisy to estimate — goalie projections deserve the most caution.
- **One manually-added player.** Aleksander Barkov missed 2025-26 (ACL) so he isn't in the source data as "active"; he was forced in, anchored at his current age (30) using his pre-injury seasons. His "2025-26 WAR" tile shows his last *played* season.
- **Mixed expected/actual inputs.** Shooting uses expected goals (stable); assists use actuals (no public expected-assist metric).
- **Calibration is judgment.** Shrinkage weights, replacement offsets, role-tier priors, and goals-per-win are principled but tunable — they set the scale, not the rank order.
- **Skater playoff rows are shooting-only.** Assists, ice time, and on-ice numbers don't exist at shot level, so a skater's playoff view covers goals, shots, expected goals, and finishing and nothing else. Goalies are unaffected.
- **The expected-goals model has drifted badly in high danger.** League-wide goals saved above expected per 100 high-danger shots moved from about −2.7 in 2008-09 to +9 from 2023-24 on, while low and medium danger stayed within a goal of zero. Raw career totals therefore quietly reward whoever played recently. The **`Adj`** columns re-base each danger tier on that season's league average and are the ones to use across eras. The same drift inflates apparent repeatability: year-over-year correlation in high-danger GSAx reads 0.40 raw and 0.07 once the drift is removed.
- **Danger-tier GSAx is mostly noise.** Roughly 96% of the season-to-season spread in high-danger goals saved above expected is binomial luck at typical volumes (~92 high-danger shots a season). Low and medium danger carry what real signal there is. Treat individual shot-map cells as descriptive, not as evidence.
- **The Projections tab is a snapshot.** It's baked into the explorer at build time, not linked live to the WAR model. Rerun the model and the explorer must be rebuilt too, or that tab silently goes stale while the shot data beside it stays current.

---

## Roadmap

1. **RAPM / regression-isolated** offense and defense — now the highest-value modeling upgrade.
2. **Fold the projection pipeline into the skill** so it reruns on new data (and the role-prior + Barkov fixes persist). The shot explorer is already there; this is the last piece.
3. **Position-split aging curves** (forwards, defensemen, goalies age differently).
4. **Bayesian projection** with full posterior draws instead of normal-approximation bands.
5. **Drop the 100-minute season cutoff** so players below it get season rows too. Shot-map coverage is already complete — every rostered player has one.
