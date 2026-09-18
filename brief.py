"""'What changed for YOUR players this week' — a grounded weekly brief via Claude.

Gathers live facts for only David's rostered players across all leagues (Sleeper injury designation /
body part / notes / depth-chart position, plus best-effort ESPN news headlines), then asks Claude to
write a terse plain-English note per player who has a real, actionable change. Every claim is grounded
in the fetched facts passed in the prompt — the model is told to invent nothing. Posts a paced Sage
thread (one message per league) like the monitor.

Run: python3 brief.py           (print only)
     python3 brief.py --post    (post to David via Sage)
"""
import json, os, sys, urllib.request
import anthropic
import data, config
from monitor import drafted_leagues, _api, post_monitor, current_week

# claude-api: default to Opus 4.8; set BRIEF_MODEL=claude-haiku-4-5 to cut cost on this recurring job.
MODEL = os.environ.get("BRIEF_MODEL", "claude-opus-4-8")
_UA = {"User-Agent": "Mozilla/5.0"}


def espn_news():
    """Recent NFL headlines as 'headline — description' strings. Best-effort (ESPN 403s some hosts)."""
    try:
        r = urllib.request.Request(
            "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news", headers=_UA)
        arts = json.load(urllib.request.urlopen(r, timeout=15)).get("articles", [])
        return [f"{a.get('headline','')} — {a.get('description','')}".strip(" —") for a in arts]
    except Exception:
        return []


def gather(idx, meta, news):
    """{league: [player dicts]} for my roster + a per-pid grounding dict of only NOTEWORTHY players."""
    rosters, mine_pids = {}, set()
    for lid, name, _tn in drafted_leagues():
        r = next((x for x in _api(f"league/{lid}/rosters") if x.get("owner_id") == config.MY_USER_ID), None)
        if r:
            pls = [idx[p] for p in (r.get("players") or []) if p in idx]
            rosters[name] = pls
            mine_pids.update(p["pid"] for p in pls)

    facts = {}
    for pid in mine_pids:
        p = idx.get(pid)
        if not p:
            continue
        m = meta.get(pid, {})
        bits = []
        if m.get("injury_status"):
            inj = m["injury_status"]
            if m.get("injury_body_part"):
                inj += f" ({m['injury_body_part']})"
            if m.get("injury_notes"):
                inj += f" — {m['injury_notes']}"
            bits.append(f"injury: {inj}")
        if (m.get("depth_chart_order") or 1) >= 3 and p["pos"] in ("RB", "WR", "TE", "QB"):
            bits.append(f"depth-chart #{m['depth_chart_order']}")
        last = p["name"].split()[-1]
        hits = [n for n in news if last in n and len(last) > 3][:2]
        bits += [f"news: {n}" for n in hits]
        if bits:
            facts[pid] = {"player": f"{p['name']} ({p['pos']}, {p.get('team') or 'FA'})", "bits": bits}
    return rosters, facts


def synthesize(facts):
    """Claude -> [{pid, player, change, action, priority}] grounded strictly in `facts`."""
    lines = [f"[{pid}] {f['player']}: " + "; ".join(f["bits"]) for pid, f in facts.items()]
    schema = {"type": "object", "additionalProperties": False, "required": ["notes"],
              "properties": {"notes": {"type": "array", "items": {
                  "type": "object", "additionalProperties": False,
                  "required": ["pid", "player", "change", "action", "priority"],
                  "properties": {"pid": {"type": "string"}, "player": {"type": "string"},
                                 "change": {"type": "string"}, "action": {"type": "string"},
                                 "priority": {"type": "string", "enum": ["high", "med", "low"]}}}}}}
    client = anthropic.Anthropic()   # reads ANTHROPIC_API_KEY
    msg = client.messages.create(
        model=MODEL, max_tokens=3000,
        system=("You are David's fantasy-football GM assistant. Below are GROUNDED facts about his "
                "rostered players — injury designations, depth-chart position, and recent news. Write a "
                "terse 'what changed' note for each player with a REAL, actionable change. Use ONLY the "
                "provided facts; never invent an injury, stat, or news item. Skip players whose facts "
                "aren't meaningful. `change` = one plain sentence; `action` = start/bench/grab-handcuff/"
                "monitor/none. `priority`: high = affects a likely starter this week."),
        output_config={"format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": "\n".join(lines)}])
    txt = next(b.text for b in msg.content if b.type == "text")
    return json.loads(txt)["notes"]


_PRI = {"high": "🔴", "med": "🟡", "low": "⚪"}


def main():
    week = current_week()
    board = data.build_players()
    idx = {p["pid"]: p for p in board}
    rosters, facts = gather(idx, data.sleeper_players(ttl=1800), espn_news())
    if not facts:
        print("(no player changes to report)"); return []
    notes = {n["pid"]: n for n in synthesize(facts)}

    sections = []
    for league, players in rosters.items():
        rows = [notes[p["pid"]] for p in players if p["pid"] in notes]
        rows.sort(key=lambda n: {"high": 0, "med": 1, "low": 2}.get(n["priority"], 3))
        if not rows:
            continue
        blk = [f"## {league}"]
        for n in rows:
            blk.append(f"{_PRI.get(n['priority'], '⚪')} **{n['player']}** — {n['change']}")
            if n["action"] and n["action"].lower() != "none":
                blk.append(f"-# → {n['action']}")
        sections.append("\n".join(blk))

    title = f"🗞️ What changed for your players — Week {week}"
    print(f"{title}\n\n" + "\n\n".join(sections))
    if "--post" in sys.argv and sections:
        # warn level if anything high-priority (a likely starter affected)
        level = "warn" if any(n["priority"] == "high" for n in notes.values()) else "info"
        post_monitor(title, sections, level=level)
    return sections


if __name__ == "__main__":
    main()
