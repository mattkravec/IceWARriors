#!/usr/bin/env python3
"""Rebuild ice_warriors_shot_explorer.html from MoneyPuck data.

The explorer is a single self-contained HTML file: a UI shell (template.html,
which already carries an inlined Chart.js) plus one gzip+base64 payload holding
every skater and goalie season from 2008-09 on, career shot maps binned on real
rink coordinates, and - optionally - the Ice WARriors projection model.

    export MPDATA_RELEASE_BASE=https://github.com/mattkravec/moneypuck-data/releases/download/data-v2
    python scripts/shot_explorer/build.py \
      --war ice_warriors_dashboard.html \
      --out ice_warriors_shot_explorer.html

First run downloads the shot files into ~/.cache/moneypuck (~290 MB) and takes a
few minutes; later runs reuse the cache. Requires pandas and pyarrow.

Data sources are tried in order: --data-dir, $MPDATA_DIR, the download cache.
Anything still missing is fetched from $MPDATA_RELEASE_BASE (or the synonym
$MPDATA_GITHUB_BASE). Parquet is preferred over CSV when both are present.

Where the numbers come from
---------------------------
Skater regular seasons come from the skaters_* aggregates, because assists, ice
time and on-ice numbers do not exist at shot level. Skater playoffs and both
goalie game types are derived from the per-shot files. Danger tiers are
recovered from raw shots with expected-goal cutoffs of 0.08 and 0.20, which
reproduce MoneyPuck's own tier counts to within about 0.5%. Situations are
labelled from each player's own side, so a goalie's "penalty kill" means his
team is short a skater. Empty-net attempts are dropped from the goalie side but
kept for shooters.
"""

from __future__ import annotations

import argparse
import base64
import glob
import gzip
import json
import math
import os
import re
import unicodedata

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.environ.get("MPDATA_CACHE",
                           os.path.join(os.path.expanduser("~"), ".cache", "moneypuck"))
RELEASE_BASE = (os.environ.get("MPDATA_RELEASE_BASE")
                or os.environ.get("MPDATA_GITHUB_BASE", "")).rstrip("/")

FIRST_SEASON, LAST_SEASON = 2008, 2025

# Rink geometry, in feet, for the attacking half. MoneyPuck's *Adjusted
# coordinates put every shot on the same end: x runs from centre ice to the end
# boards, y across the width. The map is drawn with x down the page, y across.
X0, Y0 = 25.0, -42.5
RINK_X, RINK_Y = 75.0, 85.0
SK_BIN, GO_BIN = 8.5, 6.0

SITS = ["all", "5on5", "5on4", "4on5"]
DANGER_LO, DANGER_HI = 0.08, 0.20     # expected-goal cutoffs for the tiers
MIN_ICETIME_SEC = 100 * 60            # a skater season needs 100 minutes to appear

# Skater columns carried into the payload, in payload order. Every value is
# stored as an int: the six xGoals columns are scaled by 10 and unpacked in the
# browser, and icetime is converted from seconds to whole minutes.
SKATER_COLS = [
    "games_played", "icetime",
    "I_F_goals", "I_F_primaryAssists", "I_F_secondaryAssists",
    "I_F_shotsOnGoal", "I_F_shotAttempts", "I_F_xGoals",
    "I_F_lowDangerShots", "I_F_lowDangerxGoals", "I_F_lowDangerGoals",
    "I_F_mediumDangerShots", "I_F_mediumDangerxGoals", "I_F_mediumDangerGoals",
    "I_F_highDangerShots", "I_F_highDangerxGoals", "I_F_highDangerGoals",
    "OnIce_F_xGoals", "OnIce_A_xGoals",
    "OnIce_F_shotAttempts", "OnIce_A_shotAttempts",
    "OnIce_F_goals", "OnIce_A_goals",
    "I_F_hits", "I_F_takeaways", "I_F_giveaways", "shotsBlockedByPlayer",
    "penalties", "penaltiesDrawn", "faceoffsWon", "faceoffsLost",
    "I_F_oZoneShiftStarts", "I_F_dZoneShiftStarts",
]
XG10_COLS = {"I_F_xGoals", "I_F_lowDangerxGoals", "I_F_mediumDangerxGoals",
             "I_F_highDangerxGoals", "OnIce_F_xGoals", "OnIce_A_xGoals"}

TIERS = [("low", "I_F_lowDanger"), ("med", "I_F_mediumDanger"), ("high", "I_F_highDanger")]

POS_CODE = {"C": 0, "L": 1, "R": 2, "D": 3}
POS_UNKNOWN = 4

SHOT_COLS = ["shooterPlayerId", "shooterName", "goalieIdForShot", "goalieNameForShot",
             "season", "game_id", "teamCode", "homeTeamCode", "awayTeamCode",
             "isPlayoffGame", "isHomeTeam", "homeSkatersOnIce", "awaySkatersOnIce",
             "homeEmptyNet", "awayEmptyNet", "shotWasOnGoal", "goal", "xGoal",
             "xCordAdjusted", "yCordAdjusted"]


# --------------------------------------------------------------------------- #
# locating data
# --------------------------------------------------------------------------- #
def _search_dirs(data_dir):
    dirs = [d for d in (data_dir, os.environ.get("MPDATA_DIR"), CACHE_DIR) if d]
    return [d for d in dirs if os.path.isdir(d)]


def find_file(stem, data_dir):
    """Locate one dataset by filename stem, preferring Parquet over CSV."""
    for d in _search_dirs(data_dir):
        for ext in (".parquet", ".csv", ".csv.gz"):
            hits = sorted(glob.glob(os.path.join(d, stem + ext)))
            if hits:
                return hits[0]
    return None


def fetch(name):
    """Download one file from the configured release base into the cache."""
    if not RELEASE_BASE:
        return None
    import urllib.error
    import urllib.request
    os.makedirs(CACHE_DIR, exist_ok=True)
    dest = os.path.join(CACHE_DIR, name)
    tmp = dest + ".part"
    url = f"{RELEASE_BASE}/{name}"
    try:
        with urllib.request.urlopen(url, timeout=180) as r, open(tmp, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
        os.replace(tmp, dest)
        return dest
    except urllib.error.HTTPError:
        if os.path.exists(tmp):
            os.remove(tmp)
        return None
    except Exception as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise SystemExit(
            f"Could not fetch {url} ({e}).\n"
            f"Set MPDATA_RELEASE_BASE to a reachable release, or point --data-dir "
            f"at a local copy of the MoneyPuck files.")


def need(stem, data_dir):
    """Locate a dataset, downloading it if nothing local has it."""
    p = find_file(stem, data_dir)
    if p:
        return p
    for ext in (".parquet", ".csv"):
        p = fetch(stem + ext)
        if p:
            return p
    raise SystemExit(
        f"Missing required data file '{stem}'. Looked in "
        f"{', '.join(_search_dirs(data_dir)) or '(no readable dirs)'}"
        + (f" and tried {RELEASE_BASE}" if RELEASE_BASE
           else " and no MPDATA_RELEASE_BASE is set"))


def read_table(path, columns=None):
    if path.endswith(".parquet"):
        import pyarrow.parquet as pq
        have = set(pq.read_schema(path).names)
        cols = [c for c in columns if c in have] if columns else None
        df = pd.read_parquet(path, columns=cols)
    else:
        df = pd.read_csv(path, low_memory=False)
        if columns:
            df = df[[c for c in columns if c in df.columns]]
    if columns:                       # keep the frame rectangular across schema drift
        for c in columns:
            if c not in df.columns:
                df[c] = np.nan
    return df


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def ascii_name(s):
    """Fold accents to plain ASCII so names match across sources."""
    if s is None or (isinstance(s, float) and math.isnan(s)):
        return ""
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()


def i(v):
    """Coerce a possibly-missing numeric to a plain int."""
    if v is None:
        return 0
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0
    return 0 if math.isnan(f) else int(round(f))


def x10(v):
    """Expected goals are carried as tenths so the payload stays integer."""
    return i(float(v) * 10) if v == v and v is not None else 0


def bin_keys(xc, yc, binsize):
    """Rink-cell key per shot, plus the mask of shots that land on the map.

    Coordinates are clipped to the drawn rink inclusive at both edges, and the
    closing edge folds into the last cell rather than spilling past it.
    """
    nx = int(math.ceil(RINK_X / binsize))
    ny = int(math.ceil(RINK_Y / binsize))
    keep = (xc >= X0) & (xc <= X0 + RINK_X) & (yc >= Y0) & (yc <= Y0 + RINK_Y)
    bx = np.minimum(np.floor((xc[keep] - X0) / binsize).astype(int), nx - 1)
    by = np.minimum(np.floor((yc[keep] - Y0) / binsize).astype(int), ny - 1)
    return keep, bx * 100 + by


def dump_bins(cells, min_shots=0):
    """Serialise {cell: [n, goals, [xg partials]]} to the payload's short string.

    Returns "" for a map below min_shots, which the UI renders as "no map for
    this player" - the lever for trading payload size against map coverage.
    """
    if min_shots and sum(v[0] for v in cells.values()) < min_shots:
        return ""
    return ";".join(
        f"{b},{v[0]},{v[1]},{int(round(math.fsum(v[2]) * 10))}"
        for b, v in sorted(cells.items()))


def merge_bins(dst, key, frame):
    """Fold one season's grouped cell totals into a running career map."""
    cells = dst.setdefault(key, {})
    for b, n, g, x in zip(frame["b"], frame["n"], frame["g"], frame["x"]):
        c = cells.get(b)
        if c is None:
            cells[b] = [int(n), int(g), [float(x)]]
        else:
            c[0] += int(n)
            c[1] += int(g)
            c[2].append(float(x))


def situation_index(mine, theirs):
    """Label strength from one side's own perspective; -1 means 'other'."""
    si = np.full(len(mine), -1, dtype=int)
    si[(mine == 5) & (theirs == 5)] = SITS.index("5on5")
    si[(mine == 5) & (theirs == 4)] = SITS.index("5on4")
    si[(mine == 4) & (theirs == 5)] = SITS.index("4on5")
    return si


def with_all_situations(df):
    """Duplicate every shot into the 'all' bucket alongside its own strength."""
    everything = df.assign(si=0)
    split = df[df.si >= 0]
    return pd.concat([everything, split], ignore_index=True)


def tier_of(xg):
    return np.where(xg < DANGER_LO, 0, np.where(xg < DANGER_HI, 1, 2))


# --------------------------------------------------------------------------- #
# skater regular seasons, from the aggregate files
# --------------------------------------------------------------------------- #
def load_skater_aggregates(data_dir, seasons):
    """Per-player-season rows for every situation, from skaters_*.

    MoneyPuck ships the history as one combined file plus the current season. A
    player-season qualifies on its 'all' row clearing the ice-time floor; once
    it does, every situation split for that season comes along.
    """
    want = ["playerId", "season", "name", "team", "position", "situation"] + SKATER_COLS
    frames = []
    for stem in (f"skaters_{FIRST_SEASON}_to_{LAST_SEASON - 1}", f"skaters_{LAST_SEASON}"):
        frames.append(read_table(need(stem, data_dir), columns=want))
    df = pd.concat(frames, ignore_index=True)
    df = df[df.season.isin(list(seasons))]

    qual = df[(df.situation == "all") & (df.icetime >= MIN_ICETIME_SEC)]
    keep = set(zip(qual.playerId.astype("int64"), qual.season.astype(int)))
    mask = [(int(p), int(s)) in keep for p, s in zip(df.playerId, df.season)]
    return df[mask][df.situation.isin(SITS)[mask].values]


# --------------------------------------------------------------------------- #
# the per-shot pass
# --------------------------------------------------------------------------- #
def scan_shots(data_dir, seasons, verbose=True):
    """One pass over the shot files.

    Produces, in a single sweep: skater playoff rows, goalie rows for both game
    types, every player's career shot map, and the league maps those are
    coloured against.
    """
    sk_play, go_stats = [], []
    sk_bins, go_bins = {}, {}
    lg_sk, lg_go = {0: {}, 1: {}}, {0: {}, 1: {}}
    sk_names, go_names = {}, {}

    for season in seasons:
        path = find_file(f"shots_{season}", data_dir) or need(f"shots_{season}", data_dir)
        if verbose:
            print(f"    shots {season}", flush=True)
        df = read_table(path, columns=SHOT_COLS)
        df = df[df.season == season]
        if not len(df):
            continue

        home = df.isHomeTeam.to_numpy() == 1
        hs, aws = df.homeSkatersOnIce.to_numpy(), df.awaySkatersOnIce.to_numpy()
        base = pd.DataFrame({
            "gtype": df.isPlayoffGame.to_numpy().astype(int),
            "game": df.game_id.to_numpy(),
            "goal": df.goal.to_numpy().astype(int),
            "xg": df.xGoal.to_numpy(dtype=float),
            "sog": df.shotWasOnGoal.to_numpy().astype(int),
            "xc": df.xCordAdjusted.to_numpy(dtype=float),
            "yc": df.yCordAdjusted.to_numpy(dtype=float),
        })
        base["tier"] = tier_of(base.xg.to_numpy())

        # ---- shooters -----------------------------------------------------
        sk = base.copy()
        sk["pid"] = pd.to_numeric(df.shooterPlayerId, errors="coerce").to_numpy()
        sk["team"] = df.teamCode.to_numpy()
        sk["si"] = situation_index(np.where(home, hs, aws), np.where(home, aws, hs))
        sk = sk[sk.pid.notna()]
        sk["pid"] = sk.pid.astype("int64")
        sk = sk[sk.pid != 0]              # 0 is MoneyPuck's "shooter unknown" sentinel
        for pid, nm in zip(sk.pid, df.shooterName.reindex(sk.index)):
            sk_names[int(pid)] = ascii_name(nm)

        _bin_side(sk, SK_BIN, sk_bins, lg_sk)
        play = sk[sk["gtype"] == 1]
        if len(play):
            sk_play.append(_shooting_rows(with_all_situations(play), season))

        # ---- goalies ------------------------------------------------------
        go = base.copy()
        go["pid"] = pd.to_numeric(df.goalieIdForShot, errors="coerce").to_numpy()
        # the goalie's own team, and his own side's strength
        go["team"] = np.where(home, df.awayTeamCode.to_numpy(), df.homeTeamCode.to_numpy())
        go["si"] = situation_index(np.where(home, aws, hs), np.where(home, hs, aws))
        empty = np.where(home, df.awayEmptyNet.to_numpy(), df.homeEmptyNet.to_numpy())
        go = go[go.pid.notna() & (go.pid != 0) & (empty == 0)]
        go["pid"] = go.pid.astype("int64")
        for pid, nm in zip(go.pid, df.goalieNameForShot.reindex(go.index)):
            go_names[int(pid)] = ascii_name(nm)

        _bin_side(go, GO_BIN, go_bins, lg_go)
        if len(go):
            go_stats.append(_shooting_rows(with_all_situations(go), season, keep_gt=True))

        del df, base, sk, go

    sk_play = pd.concat(sk_play, ignore_index=True) if sk_play else pd.DataFrame()
    go_stats = pd.concat(go_stats, ignore_index=True) if go_stats else pd.DataFrame()
    return sk_play, go_stats, sk_bins, go_bins, lg_sk, lg_go, sk_names, go_names


def _bin_side(side, binsize, per_player, league):
    """Accumulate this season's shot map for every player and for the league."""
    for gt in (0, 1):
        part = side[side["gtype"] == gt]
        if not len(part):
            continue
        keep, keys = bin_keys(part.xc.to_numpy(), part.yc.to_numpy(), binsize)
        part = part[keep].assign(b=keys)
        grouped = (part.groupby(["pid", "b"], sort=False)
                       .agg(n=("goal", "size"), g=("goal", "sum"), x=("xg", "sum"))
                       .reset_index())
        for pid, sub in grouped.groupby("pid", sort=False):
            merge_bins(per_player, (int(pid), gt), sub)
        lg = (part.groupby("b", sort=False)
                  .agg(n=("goal", "size"), g=("goal", "sum"), x=("xg", "sum"))
                  .reset_index())
        merge_bins(league[gt], "lg", lg)


def _shooting_rows(part, season, keep_gt=False):
    """Collapse shots to one row per player / situation (/ game type)."""
    # split on team as well: a player traded mid-season gets one row per club,
    # which is how the season log reads them back
    keys = ["pid", "si", "team"] + (["gtype"] if keep_gt else [])
    out = (part.groupby(keys, sort=False)
               .agg(games=("game", "nunique"), n=("goal", "size"), sog=("sog", "sum"),
                    g=("goal", "sum"), xg=("xg", "sum"))
               .reset_index())
    for t, (name, _) in enumerate(TIERS):
        sub = part[part.tier == t]
        agg = (sub.groupby(keys, sort=False)
                  .agg(**{f"{name}_n": ("goal", "size"),
                          f"{name}_g": ("goal", "sum"),
                          f"{name}_x": ("xg", "sum")})
                  .reset_index())
        out = out.merge(agg, on=keys, how="left")
    out["season"] = season
    return out.fillna(0)


# --------------------------------------------------------------------------- #
# assembling the payload
# --------------------------------------------------------------------------- #
def build_payload(data_dir, seasons, war_path, verbose=True, min_map_shots=0):
    if verbose:
        print("  reading skater aggregates", flush=True)
    agg = load_skater_aggregates(data_dir, seasons)

    if verbose:
        print("  scanning shot files", flush=True)
    (sk_play, go_stats, sk_bins, go_bins,
     lg_sk, lg_go, sk_shot_names, go_names) = scan_shots(data_dir, seasons, verbose)

    # ---- rosters ----------------------------------------------------------
    sk_names, sk_pos = {}, {}
    latest = agg.sort_values("season")          # last write wins = most recent season
    for pid, nm, ps in zip(latest.playerId, latest.name, latest.position):
        pid = int(pid)
        sk_names[pid] = ascii_name(nm)
        sk_pos[pid] = POS_CODE.get(str(ps).strip()[:1].upper(), POS_UNKNOWN)
    for pid, nm in sk_shot_names.items():       # shot-only players (playoffs, no aggregate)
        sk_names.setdefault(pid, nm)

    # only players with at least one season row make the roster
    rostered = set(int(p) for p in agg.playerId)
    if len(sk_play):
        rostered |= {int(p) for p in sk_play.pid}
    sk_names = {p: n for p, n in sk_names.items() if p in rostered}
    go_rostered = {int(p) for p in go_stats.pid} if len(go_stats) else set()
    go_names = {p: n for p, n in go_names.items() if p in go_rostered}

    sk_ids, go_ids = sorted(sk_names), sorted(go_names)
    sk_ix = {p: n for n, p in enumerate(sk_ids)}
    go_ix = {p: n for n, p in enumerate(go_ids)}

    def team_set(frame):
        if not len(frame):
            return set()
        return {str(t) for t in frame.team.unique()}

    teams = sorted(t for t in ({str(t) for t in agg.team.unique()}
                               | team_set(sk_play) | team_set(go_stats))
                   if t and t not in ("nan", "None", "0"))
    t_ix = {t: n for n, t in enumerate(teams)}

    # ---- skater rows ------------------------------------------------------
    rows = []
    for rec in agg.itertuples(index=False):
        row = [sk_ix[int(rec.playerId)], int(rec.season), 0,
               t_ix.get(str(rec.team), 0), SITS.index(rec.situation)]
        for c in SKATER_COLS:
            v = getattr(rec, c)
            row.append(i(v / 60.0) if c == "icetime" else
                       (x10(v) if c in XG10_COLS else i(v)))
        rows.append(row)

    for r in sk_play.itertuples(index=False):
        pid = int(r.pid)
        if pid not in sk_ix:
            continue
        vals = dict.fromkeys(SKATER_COLS, 0)
        vals["games_played"] = i(r.games)
        vals["I_F_goals"] = i(r.g)
        vals["I_F_shotsOnGoal"] = i(r.sog)
        vals["I_F_shotAttempts"] = i(r.n)
        vals["I_F_xGoals"] = x10(r.xg)
        for name, prefix in TIERS:
            vals[prefix + "Shots"] = i(getattr(r, f"{name}_n"))
            vals[prefix + "xGoals"] = x10(getattr(r, f"{name}_x"))
            vals[prefix + "Goals"] = i(getattr(r, f"{name}_g"))
        rows.append([sk_ix[pid], int(r.season), 1, t_ix.get(str(r.team), 0), int(r.si)]
                    + [vals[c] for c in SKATER_COLS])

    # ---- goalie rows ------------------------------------------------------
    grows = []
    for r in go_stats.itertuples(index=False):
        pid = int(r.pid)
        if pid not in go_ix:
            continue
        grows.append([go_ix[pid], int(r.season), int(r.gtype), t_ix.get(str(r.team), 0),
                      int(r.si), i(r.games), i(r.n), i(r.sog), i(r.g), x10(r.xg)]
                     + [f(getattr(r, f"{name}_{suf}"))
                        for name, _ in TIERS
                        for suf, f in (("n", i), ("x", x10), ("g", i))])

    payload = {
        "sits": SITS,
        "x0": X0,
        "y0": Y0,
        "war": load_war(war_path) if war_path else None,
        "goalies": {
            "names": [go_names[p] for p in go_ids],
            "ids": go_ids,
            "teams": teams,
            "rows": grows,
            "bins": {k: v for k, v in
                     ((f"{go_ix[p]}_{'P' if gt else 'R'}", dump_bins(c, min_map_shots))
                      for (p, gt), c in go_bins.items() if p in go_ix) if v},
            "lgbins": {"R": dump_bins(lg_go[0].get("lg", {})),
                       "P": dump_bins(lg_go[1].get("lg", {}))},
            "binsize": GO_BIN,
        },
        "skaters": {
            "names": [sk_names[p] for p in sk_ids],
            "ids": sk_ids,
            "pos": [sk_pos.get(p, POS_UNKNOWN) for p in sk_ids],
            "teams": teams,
            "cols": SKATER_COLS,
            "rows": rows,
            "bins": {k: v for k, v in
                     ((f"{sk_ix[p]}_{'P' if gt else 'R'}", dump_bins(c, min_map_shots))
                      for (p, gt), c in sk_bins.items() if p in sk_ix) if v},
            "lgbins": {"R": dump_bins(lg_sk[0].get("lg", {})),
                       "P": dump_bins(lg_sk[1].get("lg", {}))},
            "binsize": SK_BIN,
        },
    }
    return payload


def load_war(path):
    """Pull the projection model out of the dashboard's embedded const DATA block.

    Prefer the dashboard HTML: its player names carry proper transliteration,
    where dashboard_data.json has lost the accented characters entirely.
    """
    raw = open(path, encoding="utf-8").read()
    if path.endswith(".json"):
        data = json.loads(raw)
    else:
        m = re.search(r"const DATA\s*=\s*(\{.*?\});\s*\n", raw, re.S)
        if not m:
            raise SystemExit(f"Could not find a 'const DATA = {{...}};' block in {path}")
        data = json.loads(m.group(1))
    players = data["players"]
    cols = list(players[0].keys())
    return {"cols": cols,
            "meta": data.get("meta", {}),
            "players": [[p[c] for c in cols] for p in players]}


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="ice_warriors_shot_explorer.html",
                    help="output HTML file")
    ap.add_argument("--war", default=None,
                    help="ice_warriors_dashboard.html (or dashboard_data.json) to read "
                         "the projection model from; omit to build without the "
                         "Projections tab and the WAR column")
    ap.add_argument("--template", default=os.path.join(HERE, "template.html"),
                    help="UI shell carrying a {{PAYLOAD}} placeholder")
    ap.add_argument("--data-dir", default=None,
                    help="folder holding the MoneyPuck files (else $MPDATA_DIR, "
                         "else the download cache)")
    ap.add_argument("--first-season", type=int, default=FIRST_SEASON)
    ap.add_argument("--last-season", type=int, default=LAST_SEASON)
    ap.add_argument("--min-map-shots", type=int, default=0,
                    help="drop a player's shot map below this many career shots "
                         "(0 = keep every map; the main lever on payload size)")
    ap.add_argument("--payload-out", default=None,
                    help="also write the raw payload JSON here (for debugging)")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args()

    verbose = not args.quiet
    seasons = range(args.first_season, args.last_season + 1)
    if verbose:
        print(f"Building {args.out} for {args.first_season}-{args.last_season}")

    payload = build_payload(args.data_dir, seasons, args.war, verbose,
                            min_map_shots=args.min_map_shots)

    if args.payload_out:
        with open(args.payload_out, "w", encoding="utf-8") as f:
            json.dump(payload, f, separators=(",", ":"))

    blob = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    packed = base64.b64encode(gzip.compress(blob, 9)).decode("ascii")

    template = open(args.template, encoding="utf-8").read()
    if "{{PAYLOAD}}" not in template:
        raise SystemExit(f"{args.template} has no {{{{PAYLOAD}}}} placeholder")
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(template.replace("{{PAYLOAD}}", packed))

    if verbose:
        sk, go = payload["skaters"], payload["goalies"]
        print(f"\nWrote {args.out}  ({os.path.getsize(args.out) / 1e6:.1f} MB)")
        print(f"  skaters : {len(sk['names']):,} players, {len(sk['rows']):,} rows, "
              f"{len(sk['bins']):,} shot maps")
        print(f"  goalies : {len(go['names']):,} players, {len(go['rows']):,} rows, "
              f"{len(go['bins']):,} shot maps")
        print("  war     : "
              + (f"{len(payload['war']['players']):,} projected players"
                 if payload["war"] else "none (no --war given)"))


if __name__ == "__main__":
    main()
