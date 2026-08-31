"""Hand-editable knobs. Edit before/during the draft for things the models can't see.

GAMES_MISSED: player name -> expected regular-season games missed (out of 17).
  The model haircuts adj_proj by (17 - games_missed)/17. Use for known IR/injury
  timetables the Sleeper injury_status can't quantify (e.g. a mid-season return), or
  suspensions. 17 = out for the year (drops off the board entirely).

BUMP: player name -> multiplier on adj_proj (1.10 = you like them 10% more than
  consensus, 0.90 = fade). For your own reads / news the feeds don't have yet.

Names are matched case-insensitively against the player's full name.
"""

# ponytail: precise availability needs a human — this dict is that knob. Populated from a
# current-NFL research sweep (2026-08-31); update as news breaks.
GAMES_MISSED = {
    # per David's call — research actually pins this at a ~6-game suspension (healthy,
    # returns ~Wk 7). Change to 6 to make him a late-round stash instead of off-board.
    "Josh Jacobs": 17,
    "Zach Charbonnet": 7,   # torn ACL/PUP, re-injury risk into November
    "Jordyn Tyson": 5,      # hamstring, IR-return designation, ~October return
    "James Conner": 4,      # IR (foot), must miss min 4 games
    "Alvin Kamara": 3,      # MCL sprain, ~return Wk 3-4
    "Ashton Jeanty": 2,     # low-ankle sprain, Wk1 in doubt (not IR) — David: "maybe back"
    "Puka Nacua": 1,        # minor groin + pending civil review (low confidence)
    "Sam LaPorta": 1,       # hip flare-up, Wk1 questionable (low confidence)
    "Jeremiyah Love": 1,    # high-ankle sprain, ruled out Wk2
    "Jayden Higgins": 17,   # torn ACL (Aug 18) — season over
}

BUMP = {
    # "Puka Nacua": 1.08,
}
