# Shot explorer payload format

`build.py` writes one file: `template.html` with `{{PAYLOAD}}` replaced by a
gzip + base64 blob. The browser inflates it with `DecompressionStream` and
`JSON.parse`s the result into `D`, then `prep()` unpacks it. Everything below
describes that JSON object.

The format exists to keep a self-contained file small: ~10 MB of JSON compresses
to ~4 MB of base64, so the whole explorer — 18 seasons, 80k rows, 4.6k shot
maps — ships as a single HTML file with no network access.

## Top level

| key | what it is |
|---|---|
| `sits` | `["all","5on5","5on4","4on5"]`. Row field `si` indexes into this. |
| `x0`, `y0` | Origin of the drawn rink in feet: `25.0`, `-42.5`. |
| `war` | The Ice WARriors projection model, or `null` when built without `--war`. |
| `skaters` | Skater side (see below). |
| `goalies` | Goalie side. |

## `skaters` / `goalies`

| key | what it is |
|---|---|
| `names` | Player names, indexed by `gi`. From the player's **most recent** season. |
| `ids` | MoneyPuck `playerId`, same index order, ascending. This is the join key to `war`. |
| `pos` | Skaters only. `0=C 1=LW 2=RW 3=D 4=unknown`, from the most recent season. |
| `teams` | Sorted team codes shared by both sides; row field `ti` indexes into it. Both era spellings appear (`L.A` and `LAK`, `N.J` and `NJD`, …) because MoneyPuck changed codes mid-history. |
| `cols` | Skaters only: names the row fields after the first five. |
| `rows` | One row per player / season / game type / situation / team. |
| `bins` | Career shot maps, keyed `"{gi}_R"` / `"{gi}_P"`. |
| `lgbins` | League shot maps, keyed `"R"` / `"P"`, used as the comparison baseline. |
| `binsize` | Cell size in feet: `8.5` for skaters, `6.0` for goalies. |

### Rows

Every row starts with the same five fields:

```
[gi, season, gt, ti, si, ...values]
 gi      index into names/ids
 season  start year (2025 = the 2025-26 season)
 gt      0 = regular season, 1 = playoffs
 ti      index into teams
 si      index into sits
```

**Skaters** continue with one value per entry in `cols`, in that order.
**Goalies** use a fixed layout:

```
gp, sh, sog, ga, xg, ln, lx, lg, mn, mx, mg, hn, hx, hg
```

`sh` is unblocked shot attempts faced, `l/m/h` are the low/medium/high danger
tiers, and within each tier `n`/`x`/`g` are shots, expected goals and goals.

Everything is an integer. Two encodings to unpack:

- **Expected goals are stored as tenths.** Every `xGoals` column — and every
  `x` in a shot map — is `round(value * 10)`. `prep()` divides by 10.
- **`icetime` is whole minutes**, not MoneyPuck's seconds.

A player traded mid-season gets one row per club, which is how the season log
reads them back.

### Shot maps

Each map is a string of `;`-separated cells, each `bin,n,goals,xg10`:

```
0,4,1,0;1,22,0,4;2,21,1,4;...
```

`bin` is `bx * 100 + by`, where `bx` runs down the rink (centre ice → end
boards) and `by` across it. To recover a cell's corner in feet:

```
x = x0 + bx * binsize        # 25.0 .. 100.0
y = y0 + by * binsize        # -42.5 .. 42.5
```

Shots are placed from MoneyPuck's `xCordAdjusted` / `yCordAdjusted`, which fold
every shot onto one attacking end. Coordinates are clipped to the drawn rink
inclusive at both edges, and a shot exactly on the closing edge folds into the
last cell rather than spilling past it.

The UI colours a cell by the player's goals-above-expected per shot against the
league rate in the *same* cell, which is why `lgbins` has to be built on exactly
the same grid.

## `war`

```
{"cols": [...], "meta": {...}, "players": [[...], ...]}
```

`cols` names the fields of each `players` row; `id` is the MoneyPuck
`playerId` the two halves cross-link on, so no name matching is involved.

Read straight out of the dashboard's embedded `const DATA` block. Prefer
`ice_warriors_dashboard.html` over `dashboard_data.json`: the JSON has lost the
accented characters in ~14 player names, where the HTML carries them properly
transliterated.

## Sizing levers

The payload is dominated by `rows` and `bins`, roughly two to one.

- `--min-map-shots N` drops any career shot map under N shots. The UI already
  renders a missing map as "no map for this player", so this degrades cleanly.
  Default `0` keeps every map.
- `--first-season` / `--last-season` narrow the history.
- Dropping `--war` removes the Projections tab and the WAR column.

## Known data quirks the build handles

- **Shot files include playoff games; the aggregate files do not.** Rows carry
  `gt` so the two never get mixed.
- **`goalieIdForShot` is `0`** on some shots — MoneyPuck's "no goalie
  identified" sentinel. It is excluded from goalie rows and maps, but the shot
  still counts toward the league map.
- **Empty-net attempts are dropped from the goalie side** and kept for
  shooters. MoneyPuck fills in a `goalieIdForShot` even when the net is empty,
  and those attempts carry wildly inflated expected goals, so they have to be
  filtered on the empty-net flag rather than on a missing goalie.
- **The same player can appear under two name spellings in one season**
  (`J-F Berube` / `J.F. Berube`). Rows are grouped by `playerId`, never by name,
  so those merge into a single season row.
- **`shooterPlayerId` can be `0`.** Same treatment as the goalie sentinel.
