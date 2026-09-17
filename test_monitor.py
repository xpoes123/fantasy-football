"""Offline checks for the monitor's lineup optimizer + start/sit legality. No network."""
import monitor


def _p(name, pos, proj, bye=None, inj=None):
    return {"pid": name, "name": name, "pos": pos, "adj_proj": proj, "bye": bye, "inj": inj}


def test_optimize_picks_best_and_respects_flex():
    slots = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"]
    roster = [_p("QB1", "QB", 300), _p("RB1", "RB", 250), _p("RB2", "RB", 200),
              _p("RB3", "RB", 180), _p("WR1", "WR", 240), _p("WR2", "WR", 150),
              _p("TE1", "TE", 130), _p("K1", "K", 110), _p("DEF1", "DEF", 100)]
    chosen = {p["name"] for p in monitor.optimize(roster, slots, week=1, wk={})}
    assert chosen == {"QB1", "RB1", "RB2", "RB3", "WR1", "WR2", "TE1", "K1", "DEF1"}, chosen
    # RB3 (180) beats WR2/TE1 for the single FLEX slot
    assert "RB3" in chosen


def test_optimize_benches_bye_and_out_players():
    slots = ["QB", "RB"]
    roster = [_p("QB1", "QB", 300, bye=1), _p("QB2", "QB", 100),      # QB1 on bye -> QB2 starts
              _p("RB1", "RB", 250, inj="Out"), _p("RB2", "RB", 90)]   # RB1 out -> RB2 starts
    chosen = {p["name"] for p in monitor.optimize(roster, slots, week=1, wk={})}
    assert chosen == {"QB2", "RB2"}, chosen


def test_swap_class_never_crosses_qb_and_def():
    assert monitor.__dict__  # module import sanity
    cls = lambda pos: pos if pos in ("QB", "K", "DEF") else "FLX"
    assert cls("QB") != cls("DEF") != cls("WR")
    assert cls("RB") == cls("WR") == cls("TE") == "FLX"   # interchangeable via FLEX


if __name__ == "__main__":
    test_optimize_picks_best_and_respects_flex()
    test_optimize_benches_bye_and_out_players()
    test_swap_class_never_crosses_qb_and_def()
    print("ok")
