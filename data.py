"""Build the unified player table: Sleeper meta + ESPN proj/ADP + Vegas/age/injury
adjustments + VOR. Cached to data/cache/ so we don't refetch every launch."""
import json, math, os, time, urllib.request, urllib.parse
import config, overrides

CACHE = config.CACHE_DIR
os.makedirs(CACHE, exist_ok=True)

# ESPN position ids we care about come via Sleeper instead; keep for DEF/K fallback.
NFL_ABBR = {  # Odds API full name -> Sleeper team abbrev
    "Arizona Cardinals":"ARI","Atlanta Falcons":"ATL","Baltimore Ravens":"BAL",
    "Buffalo Bills":"BUF","Carolina Panthers":"CAR","Chicago Bears":"CHI",
    "Cincinnati Bengals":"CIN","Cleveland Browns":"CLE","Dallas Cowboys":"DAL",
    "Denver Broncos":"DEN","Detroit Lions":"DET","Green Bay Packers":"GB",
    "Houston Texans":"HOU","Indianapolis Colts":"IND","Jacksonville Jaguars":"JAX",
    "Kansas City Chiefs":"KC","Las Vegas Raiders":"LV","Los Angeles Chargers":"LAC",
    "Los Angeles Rams":"LAR","Miami Dolphins":"MIA","Minnesota Vikings":"MIN",
    "New England Patriots":"NE","New Orleans Saints":"NO","New York Giants":"NYG",
    "New York Jets":"NYJ","Philadelphia Eagles":"PHI","Pittsburgh Steelers":"PIT",
    "San Francisco 49ers":"SF","Seattle Seahawks":"SEA","Tampa Bay Buccaneers":"TB",
    "Tennessee Titans":"TEN","Washington Commanders":"WAS",
}

# 2026 bye weeks by team (from Sharp Football / FantasyPros). Used to flag stacked byes.
BYES = {
    "KC":5,"CAR":5, "CIN":6,"MIA":6,"DET":6,"MIN":6, "BUF":7,"LAC":7,"WAS":7,"JAX":7,
    "SF":8,"NYG":8,"NO":8,"HOU":8, "PIT":9,"TEN":9, "CHI":10,"DEN":10,"TB":10,"PHI":10,
    "CLE":11,"ATL":11,"GB":11,"NE":11,"LAR":11,"SEA":11, "IND":13,"NYJ":13,"LV":13,"BAL":13,
    "ARI":14,"DAL":14,
}

# Strength-of-schedule multiplier by team (season DVP + fantasy-playoff Wk15-17), from the
# SOS research sweep. A tiebreaker (±5% max) — good playoff slates up, brutal ones down.
# ponytail: team-level flat; a per-position×week DVP engine off nflverse is the later upgrade.
SOS_TEAM = {
    "ATL":1.05, "ARI":1.05, "DET":1.05, "MIN":1.04, "LAC":1.03, "NO":1.03, "IND":1.03,
    "TB":1.01, "BAL":0.98, "KC":0.97, "HOU":0.97, "SEA":0.97, "SF":0.96, "PHI":0.95,
}

# Coaching-prowess multiplier by team: staff/play-caller QUALITY (scheming players open,
# play-calling, RZ, development, in-game adjustments) — an axis beyond scheme volume and
# Vegas. Small (±4%). Populated from the coaching-prowess research sweep.
COACHING = {
    "ARI":0.99,"ATL":1.01,"BAL":0.99,"BUF":1.02,"CAR":1.00,"CHI":1.03,"CIN":1.01,"CLE":1.00,
    "DAL":1.00,"DEN":1.03,"DET":1.01,"GB":1.02,"HOU":1.00,"IND":1.02,"JAX":1.02,"KC":1.04,
    "LV":1.00,"LAC":1.02,"LAR":1.04,"MIA":0.99,"MIN":1.03,"NE":1.01,"NO":1.00,"NYG":0.97,
    "NYJ":0.99,"PHI":1.00,"PIT":1.00,"SF":1.04,"SEA":0.99,"TB":1.00,"TEN":0.98,"WAS":0.99,
}

# Waiver-aware replacement ranks (12-team, moderate tilt): value each player over the best
# player you could STREAM off waivers, not the last drafted starter. RB gets a deep baseline
# (you can't stream a good RB — everyone hoards them → scarcity); QB/TE shallower (deep waiver
# pools, stream-able). Elevates RB to its true scarcity value while keeping elite WR premium.
REPL_RANK = {"QB":13, "RB":38, "WR":44, "TE":14, "K":12, "DEF":12}


def _get(url, headers=None, ttl=86400):
    """GET with a simple on-disk cache keyed by url. ttl seconds.
    On a fetch failure, serve stale cache if we have any — so a mid-draft restart or
    upstream hiccup can't take the tool down."""
    key = os.path.join(CACHE, urllib.parse.quote(url, safe="")[:180] + ".json")
    if os.path.exists(key) and time.time() - os.path.getmtime(key) < ttl:
        with open(key) as f:
            return json.load(f)
    try:
        hdrs = {"User-Agent": "Mozilla/5.0 (draft-advisor)"}  # api.sleeper.com 403s urllib's default UA
        hdrs.update(headers or {})
        req = urllib.request.Request(url, headers=hdrs)
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
        with open(key, "w") as f:
            json.dump(data, f)
        return data
    except Exception:
        if os.path.exists(key):          # stale is better than dead during a live draft
            with open(key) as f:
                return json.load(f)
        raise


def sleeper_players(ttl=86400):
    """player_id -> meta. The dump is ~5MB; cache it hard."""
    return _get("https://api.sleeper.app/v1/players/nfl", ttl=ttl)


def preseason_usage(ttl=43200):
    """player_id -> (snap_share, touches) from this year's preseason games. Reveals who won a
    role — snap%, carries+targets. INFO ONLY: established starters rest in preseason (Bijan/CMC
    play 0 snaps), so raw snap share is scrub-dominated and must never be a value multiplier;
    it's surfaced as a flag on contested/late players for the drafter to judge."""
    try:
        raw = _get(f"https://api.sleeper.app/v1/stats/nfl/pre/{config.SEASON}", ttl=ttl)
    except Exception:
        return {}
    out = {}
    for pid, s in (raw or {}).items():
        if not isinstance(s, dict):
            continue
        osnp, tos = s.get("off_snp"), s.get("tm_off_snp")
        if not osnp or not tos:
            continue
        out[pid] = (round(osnp / tos, 3), int((s.get("rush_att", 0) or 0) + (s.get("rec_tgt", 0) or 0)))
    return out


ESPN_POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DEF"}


def _norm(name):
    """Normalize a player name for fuzzy joining: lowercase, drop punctuation/suffixes."""
    n = name.lower().replace(".", "").replace("'", "").replace("-", " ")
    for suf in (" jr", " sr", " ii", " iii", " iv", " v"):
        if n.endswith(suf):
            n = n[: -len(suf)]
    return " ".join(n.split())


def espn_proj_adp(ttl=21600):
    """Return (by_id, by_name) where each maps -> {proj, adp}.
    by_id keyed on str(espn athlete id); by_name keyed on '<norm name>|<POS>'."""
    url = ("https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026"
           "/segments/0/leaguedefaults/3?view=kona_player_info")
    hdr = {"accept": "application/json",
           "x-fantasy-filter": json.dumps({"players": {"limit": 600,
               "sortDraftRanks": {"sortPriority": 1, "sortAsc": True, "value": "PPR"}}})}
    d = _get(url, headers=hdr, ttl=ttl)
    by_id, by_name = {}, {}
    for entry in d.get("players", []):
        p = entry["player"]
        proj = next((s["appliedTotal"] for s in p.get("stats", [])
                     if s.get("seasonId") == 2026 and s.get("statSourceId") == 1
                     and s.get("statSplitTypeId") == 0 and s.get("scoringPeriodId") == 0), None)
        rec = {"proj": proj, "adp": (p.get("ownership") or {}).get("averageDraftPosition")}
        by_id[str(p["id"])] = rec
        pos = ESPN_POS.get(p.get("defaultPositionId"))
        if pos and p.get("fullName"):
            by_name[_norm(p["fullName"]) + "|" + pos] = rec
    return by_id, by_name


def rotowire_proj(ttl=21600):
    """Sleeper's own RotoWire projections — primary source. Returns
    player_id(str) -> {proj, adp}. Keyed on the SAME Sleeper id we join meta on, so no
    fuzzy name-join, and it covers K/DEF (real DST projections, unlike ESPN)."""
    out = {}
    for pos in ("QB", "RB", "WR", "TE", "K", "DEF"):
        url = ("https://api.sleeper.com/projections/nfl/2026"
               f"?season_type=regular&position[]={pos}&order_by=pts_ppr")
        for row in _get(url, ttl=ttl):
            st = row.get("stats") or {}
            out[str(row["player_id"])] = {"proj": st.get("pts_ppr"), "adp": st.get("adp_ppr")}
    return out


DIVISIONS = {
    "BUF":"AFCE","MIA":"AFCE","NE":"AFCE","NYJ":"AFCE","BAL":"AFCN","CIN":"AFCN","CLE":"AFCN",
    "PIT":"AFCN","HOU":"AFCS","IND":"AFCS","JAX":"AFCS","TEN":"AFCS","DEN":"AFCW","KC":"AFCW",
    "LV":"AFCW","LAC":"AFCW","DAL":"NFCE","NYG":"NFCE","PHI":"NFCE","WAS":"NFCE","CHI":"NFCN",
    "DET":"NFCN","GB":"NFCN","MIN":"NFCN","ATL":"NFCS","CAR":"NFCS","NO":"NFCS","TB":"NFCS",
    "ARI":"NFCW","LAR":"NFCW","SF":"NFCW","SEA":"NFCW",
}


def def_matchups(ttl=21600):
    """team abbrev -> {opp, opp_pts} for the SOONEST game (Week 1). A DEF facing a low
    implied-points offense = soft matchup (good streaming spot). Reuses the Odds API games."""
    if not config.ODDS_API_KEY:
        return {}
    url = ("https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds/"
           f"?apiKey={config.ODDS_API_KEY}&regions=us&markets=spreads,totals&oddsFormat=american")
    games = sorted(_get(url, ttl=ttl), key=lambda g: g.get("commence_time", ""))[:16]  # Week 1
    out = {}
    for g in games:
        home, away = g["home_team"], g["away_team"]
        total = spread_home = None
        for bk in g.get("bookmakers", []):
            for mk in bk.get("markets", []):
                if mk["key"] == "totals" and total is None:
                    total = mk["outcomes"][0].get("point")
                if mk["key"] == "spreads" and spread_home is None:
                    for o in mk["outcomes"]:
                        if o["name"] == home:
                            spread_home = o.get("point")
            if total is not None and spread_home is not None:
                break
        if total is None or spread_home is None:
            continue
        ih, ia = total / 2 - spread_home / 2, total / 2 + spread_home / 2
        ha, aa = NFL_ABBR.get(home), NFL_ABBR.get(away)
        if ha and aa:
            out[ha] = {"opp": aa, "opp_pts": round(ia, 1)}   # home DEF faces away offense
            out[aa] = {"opp": ha, "opp_pts": round(ih, 1)}
    return out


def team_env(ttl=21600):
    """team abbrev -> offensive-environment multiplier from Vegas season implied points."""
    if not config.ODDS_API_KEY:
        return {}  # no key -> skip Vegas layer, projections still work
    url = ("https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds/"
           f"?apiKey={config.ODDS_API_KEY}&regions=us&markets=spreads,totals&oddsFormat=american")
    games = _get(url, ttl=ttl)
    pts = {}  # abbrev -> summed implied points
    for g in games:
        home, away = g["home_team"], g["away_team"]
        total = spread_home = None
        for bk in g.get("bookmakers", []):
            for mk in bk.get("markets", []):
                if mk["key"] == "totals" and total is None:
                    total = mk["outcomes"][0].get("point")
                if mk["key"] == "spreads" and spread_home is None:
                    for o in mk["outcomes"]:
                        if o["name"] == home:
                            spread_home = o.get("point")
            if total is not None and spread_home is not None:
                break
        if total is None or spread_home is None:
            continue
        # implied points = total/2 - spread/2  (favorite: negative spread -> more points)
        ih = total / 2 - spread_home / 2
        ia = total / 2 + spread_home / 2
        for name, ip in ((home, ih), (away, ia)):
            ab = NFL_ABBR.get(name)
            if ab:
                pts[ab] = pts.get(ab, 0.0) + ip
    if not pts:
        return {}
    avg = sum(pts.values()) / len(pts)
    # multiplier: teams ±, damped so it nudges not dominates (0.5 weight)
    return {ab: 1.0 + 0.5 * (v - avg) / avg for ab, v in pts.items()}


def age_mult(pos, age):
    """Position age curve. Multiplier on projection. None age -> 1.0."""
    if not age:
        return 1.0
    if pos == "RB":
        if age >= 30: return 0.85
        if age >= 28: return 0.93
        return 1.0
    if pos == "WR":
        if age >= 32: return 0.88
        if age >= 30: return 0.95
        return 1.0
    if pos == "TE":
        if age >= 33: return 0.90
        return 1.0
    if pos == "QB":
        if age >= 39: return 0.92
        return 1.0
    return 1.0


# case-insensitive views of the manual override dicts (docstring promised this)
_GM_CI = {k.lower(): v for k, v in overrides.GAMES_MISSED.items()}
_BUMP_CI = {k.lower(): v for k, v in overrides.BUMP.items()}
_WEDGE_CI = {k.lower(): v for k, v in overrides.WEDGES.items()}
_ADP_OV_CI = {k.lower(): v for k, v in overrides.ADP_OVERRIDE.items()}

# Preseason roster-technicality tags (NA/DNR/PUP) are mostly noise, not "will miss N games"
# — don't nuke a startable player off a paperwork tag. IR is real but often not season-long.
_INJ_GM = {"IR": 6, "Out": 1, "Doubtful": 1, "PUP": 2, "Sus": 3, "NA": 0, "DNR": 0}


def injury_mult(name, status):
    """Games-missed haircut. overrides.GAMES_MISSED (case-insensitive) wins; else map status."""
    gm = _GM_CI.get(name.lower())
    if gm is None:
        gm = _INJ_GM.get(status, 0)
    return max(0.0, (17 - gm) / 17)


def build_players():
    """Return list of player dicts with adj_proj and vor, sorted by vor desc.
    Only skill positions + K/DEF that have a projection or are draftable."""
    sl = sleeper_players()
    roto = rotowire_proj()                       # primary: id-keyed RotoWire
    espn_id, espn_name = espn_proj_adp()         # fallback only
    env = team_env()
    pre = preseason_usage()                      # {pid: (snap_share, touches)} — info flag only

    players = []
    for pid, m in sl.items():
        pos = m.get("position")
        if pos not in ("QB", "RB", "WR", "TE", "K", "DEF"):
            continue
        name = m.get("full_name") or (m.get("first_name", "") + " " + m.get("last_name", "")).strip()
        # BLEND two independent projections to denoise per-source outliers (RotoWire had
        # Josh Jacobs at 87, ESPN at 198 — averaging beats trusting either alone).
        r = roto.get(pid) or {}
        eid = str(m.get("espn_id")) if m.get("espn_id") else None
        es = (espn_id.get(eid) if eid else None) or espn_name.get(_norm(name) + "|" + pos, {})
        srcs = [p for p in (r.get("proj"), es.get("proj")) if p is not None]
        proj = sum(srcs) / len(srcs) if srcs else None
        adp = _ADP_OV_CI.get(name.lower()) or r.get("adp") or es.get("adp")  # override > RotoWire > ESPN
        draftable = adp is not None and adp < 250   # has a real draft position
        # don't silently drop players: only skip true clutter (no projection AND not draftable
        # AND not on a team). Keeps Aiyuk (proj gap) / Tyreek Hill (team=None) on the board.
        if proj is None and not draftable and not m.get("team"):
            continue
        if proj is None:
            # imputed baseline so the player still appears/rosters; low so it can't distort VOR
            proj = {"K": 116.0, "DEF": 100.0}.get(pos, 40.0)
        # Soft situational priors (all proxy "good spot") -> combine in log-space with damping +
        # a hard cap so they can't compound into runaway over-love. Injury is a separate real haircut.
        signals = [env.get(m.get("team"), 1.0), age_mult(pos, m.get("age")),
                   SOS_TEAM.get(m.get("team"), 1.0), COACHING.get(m.get("team"), 1.0),
                   _BUMP_CI.get(name.lower(), 1.0), _WEDGE_CI.get(name.lower(), 1.0)]
        logsum = sum(math.log(s) for s in signals if s > 0)
        factor = min(config.SIGNAL_CAP_HI, max(config.SIGNAL_CAP_LO,
                                               math.exp(config.SIGNAL_DAMP * logsum)))
        base_adj = proj * factor * injury_mult(name, m.get("injury_status"))
        ps = pre.get(pid)
        players.append({
            "pid": pid, "name": name, "pos": pos, "team": m.get("team"),
            "age": m.get("age"), "inj": m.get("injury_status"),
            "proj": round(proj, 1), "base_adj": base_adj, "adj_proj": round(base_adj, 1),
            "adp": adp if adp else 999.0, "bye": BYES.get(m.get("team")),
            "presnap": ps[0] if ps else None, "pretouch": ps[1] if ps else None,
            "depth": m.get("depth_chart_order"),
        })

    # ① Market blend: regress each model value toward what the market (ADP) implies for that draft
    # slot. Build an ADP->value curve (value of the k-th best draftable player = what the market
    # pays for pick k), then pull each player toward the value at their ADP. Modest edges (within
    # BLEND_FREE of market) are kept in full; extreme divergence (a bump-inflated backup, a rookie
    # the model has 3 rounds early) gets yanked home — kills over-love, keeps genuine edges.
    curve = sorted((p["base_adj"] for p in players if p["adp"] < 250), reverse=True)
    n = len(curve)
    for p in players:
        if p["adp"] >= 250 or n == 0:                 # no market signal -> trust the model
            continue
        mkt = curve[min(int(round(p["adp"])), n) - 1]
        m0, d = p["base_adj"], abs(p["base_adj"] - mkt) / mkt if mkt > 0 else 0.0
        w = math.exp(-config.BLEND_K * max(0.0, d - config.BLEND_FREE))
        p["adj_proj"] = round(w * m0 + (1 - w) * mkt, 1)

    # Workload transfer: when a starter is marked OUT (GAMES_MISSED high), move their vacated
    # production to their handcuff — the model doesn't do this on its own (had to hand-bump
    # Lloyd/Kaleb Johnson live). Applied before VOR so the backup's value reflects the role.
    idx = {p["name"].lower(): p for p in players}
    for starter, backup in overrides.HANDCUFFS.items():
        gm = _GM_CI.get(starter.lower(), 0)
        if gm < 8:                                    # only if starter misses ~half+ the season
            continue
        sp, bp = idx.get(starter.lower()), idx.get(backup.lower())
        if not sp or not bp:
            continue
        transfer = sp["proj"] * (gm / 17.0) * 0.32    # backup inherits volume at lower efficiency
        bp["adj_proj"] = round(bp["adj_proj"] + transfer, 1)

    # VOR = adj_proj - replacement-level adj_proj at position
    by_pos = {}
    for p in players:
        by_pos.setdefault(p["pos"], []).append(p)
    for pos, ps in by_pos.items():
        ps.sort(key=lambda x: x["adj_proj"], reverse=True)
        rank = REPL_RANK.get(pos, 12)
        repl = ps[rank - 1]["adj_proj"] if len(ps) >= rank else (ps[-1]["adj_proj"] if ps else 0)
        for p in ps:
            p["vor"] = round(p["adj_proj"] - repl, 1)

    players.sort(key=lambda x: x["vor"], reverse=True)
    return players


if __name__ == "__main__":
    ps = build_players()
    print(f"{len(ps)} players\n")
    print(f"{'POS':4}{'NAME':24}{'TM':4}{'AGE':4}{'PROJ':>7}{'ADJ':>7}{'VOR':>7}{'ADP':>7}")
    for p in ps[:40]:
        print(f"{p['pos']:4}{p['name'][:23]:24}{(p['team'] or '-'):4}"
              f"{str(p['age'] or '-'):4}{p['proj']:>7}{p['adj_proj']:>7}{p['vor']:>7}{p['adp']:>7}")
