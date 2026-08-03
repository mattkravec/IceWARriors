# Ice WARriors — NHL Player Value & Career Projections

A WAR-style valuation of every NHL skater and goalie (MoneyPuck data, 2008–2025 seasons) plus real-age rest-of-career projections for active players, delivered as an interactive dashboard, downloadable data, and a reusable data-loading skill.

Everything here is a principled **v1** — honest about its assumptions, not an oracle. Read the *Limitations* section before quoting a number.

---

## What's in this folder

| File | What it is |
|---|---|
| `ice_warriors_dashboard.html` | **Start here.** Self-contained interactive dashboard — sortable/searchable player rankings on the left, per-player valuation and career-projection curves on the right. No internet needed; open in any browser. |
| `career_projections.csv` | Every active player: current age, talent rate, projected peak, remaining-career WAR (with range), projected seasons, career-to-date and projected-total WAR. |
| `player_value_history_skaters.csv` | Every skater-season with all five WAR components, GAR, and WAR. |
| `player_value_history_goalies.csv` | Every goalie-season with GSAx and WAR. |
| `methodology.md` | Full methodology writeup — component construction, calibration, aging/projection, and detailed limitations. |
| `moneypuck-nhl.skill` | Reusable Claude skill that loads and analyzes the MoneyPuck data (handles all the file quirks). Install it to rerun analysis on future data. |
| `dashboard_data.json` | The data the dashboard reads (already embedded in the HTML; here for reuse). |

---

## Quick start

Open `ice_warriors_dashboard.html` in a browser. Search a player or sort the list by remaining-career WAR, projected total, talent, current-season WAR, or career-to-date. Click any player to see their stat tiles and the actual-vs-projected WAR curve.

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

## Data & the skill

The analysis is built on the MoneyPuck NHL dataset (per-skater, per-goalie, per-line, per-team, and per-shot files) plus `allPlayersLookup.csv` for birthdates. The `moneypuck-nhl.skill` loads it and handles the quirks (schema drift, playoff rows in shot files, duplicate headers, situation splits). It can source data three ways, in priority order:

1. **A local folder via `MPDATA_DIR`** — point it at a Google Drive for Desktop synced copy of the data folder. This is the robust way to use the big per-shot files (they never move over the network).
2. **A GitHub repo via `MPDATA_GITHUB_BASE`** — the sandbox can fetch its own CSVs from GitHub raw (files must be under 100 MB).
3. **Direct uploads** — files in the session are used with no setup.

See `references/google_drive.md` inside the skill for the full Drive workflow. Note: a skill *script* cannot download from Google Drive at runtime (the sandbox can't reach Google), so Drive data is sourced via a local sync, not an API call.

---

## Reproducing & extending

The WAR value files (`player_value_history_*.csv`) are the durable output of the value model. The projection layer (aging curves, role-conditioned survival/games, talent regression, forward simulation) is rebuilt from those files.

**Heads-up:** the projection scripts currently live in a temporary workspace that resets between sessions, so the projection pipeline — including the role-conditioned prior and the manually-added Barkov — is **not yet baked into anything permanent**. Folding the pipeline into the `moneypuck-nhl` skill is the way to make it reproducible on future data drops; that step hasn't been done yet.

---

## Limitations — read before quoting a number

- **Not RAPM-isolated.** On-off differentials reduce but don't eliminate teammate, competition, and deployment bias in the defensive components.
- **Very young players are speculative.** A one- or two-season talent estimate extrapolated across a 15–20 year career; the bands are wide for a reason, and the deep tails carry the most model risk.
- **Goalie aging is a domain prior, not data.** The 27 peak and gentle slope are imposed because the goalie sample is too thin and noisy to estimate — goalie projections deserve the most caution.
- **One manually-added player.** Aleksander Barkov missed 2025-26 (ACL) so he isn't in the source data as "active"; he was forced in, anchored at his current age (30) using his pre-injury seasons. His "2025-26 WAR" tile shows his last *played* season.
- **Mixed expected/actual inputs.** Shooting uses expected goals (stable); assists use actuals (no public expected-assist metric).
- **Calibration is judgment.** Shrinkage weights, replacement offsets, role-tier priors, and goals-per-win are principled but tunable — they set the scale, not the rank order.

---

## Roadmap

1. **RAPM / regression-isolated** offense and defense — now the highest-value modeling upgrade.
2. **Fold the projection pipeline into the skill** so it reruns on new data (and the role-prior + Barkov fixes persist).
3. **Position-split aging curves** (forwards, defensemen, goalies age differently).
4. **Bayesian projection** with full posterior draws instead of normal-approximation bands.
