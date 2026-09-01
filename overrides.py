"""Hand-editable knobs. Edit before/during the draft for things the models can't see.

GAMES_MISSED: player name -> expected regular-season games missed (out of 17).
  Haircuts adj_proj by (17 - games_missed)/17. For known IR/injury timetables or
  suspensions. 17 = out for the year (drops off the board).

BUMP: player name -> multiplier on adj_proj (>1 buy, <1 fade). OC-scheme + player role/
  situation nudges from a 2026-08-31 research sweep (two independent research passes,
  AVERAGED — where they disagreed the value washes toward 1.0). Stacks with GAMES_MISSED.

Names are matched case-insensitively against the player's full name.
"""

# ponytail: availability needs a human — this dict is that knob. From a current-NFL sweep
# (2026-08-31). Update as news breaks.
GAMES_MISSED = {
    # per David's call — research pins this at a ~6-game suspension (healthy, returns ~Wk 7).
    # Change to 6 to make him a late-round stash instead of off-board.
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

# starter RB -> the backup who inherits the workload (from a 2026 handcuff research sweep).
# Shown next to your rostered RBs so you know who to grab as insurance.
HANDCUFFS = {
    "Kyren Williams": "Blake Corum",
    "Christian McCaffrey": "Jordan James",
    "Josh Jacobs": "MarShawn Lloyd",
    "Alvin Kamara": "Kendre Miller",
    "James Conner": "Trey Benson",
    "Ashton Jeanty": "Raheem Mostert",
    "De'Von Achane": "Jaylen Wright",
    "Saquon Barkley": "Tank Bigsby",
    "Bucky Irving": "Kenny Gainwell",
    "Cam Skattebo": "Tyrone Tracy",
    "Jahmyr Gibbs": "Craig Reynolds",
    "Bijan Robinson": "Tyler Allgeier",
    "Derrick Henry": "Justice Hill",
    "Jonathan Taylor": "Tyler Goodson",
}

# Wedge factor: TD-regression + O-line + opportunity/usage + durability, merged into ONE
# damped, clamped multiplier (delta-sum x0.6, clamp 0.90-1.10) so the four signals don't
# over-stack each other, Vegas, or the scheme BUMP. From the wedge research sweep (2026-08-31).
WEDGES = {
    "Bucky Irving": 1.072,
    "Bijan Robinson": 1.06,
    "Breece Hall": 1.054,
    "Kyren Williams": 1.048,
    "CeeDee Lamb": 1.042,
    "Omarion Hampton": 1.036,
    "James Cook": 1.024,
    "Jaxon Smith-Njigba": 1.024,
    "Justin Jefferson": 1.024,
    "Wan'Dale Robinson": 1.024,
    "Amon-Ra St. Brown": 1.018,
    "Javonte Williams": 1.018,
    "Rashid Shaheed": 1.018,
    "Kenneth Walker": 1.015,
    "Xavier Worthy": 1.015,
    "Ashton Jeanty": 1.012,
    "Bo Nix": 1.012,
    "Luther Burden": 1.009,
    "Baker Mayfield": 1.006,
    "Jalen Hurts": 1.006,
    "Jahmyr Gibbs": 0.988,
    "J.K. Dobbins": 0.982,
    "Jauan Jennings": 0.982,
    "Jayden Daniels": 0.982,
    "RJ Harvey": 0.982,
    "Travis Etienne": 0.979,
    "Alvin Kamara": 0.976,
    "Cam Ward": 0.976,
    "Chase Brown": 0.976,
    "Josh Allen": 0.976,
    "Quinshon Judkins": 0.976,
    "Tony Pollard": 0.976,
    "A.J. Brown": 0.97,
    "Chuba Hubbard": 0.97,
    "Davante Adams": 0.97,
    "Drake London": 0.97,
    "Jacory Croskey-Merritt": 0.97,
    "Nico Collins": 0.97,
    "TreVeyon Henderson": 0.97,
    "Aaron Jones": 0.964,
    "Harold Fannin": 0.964,
    "Jonathan Taylor": 0.964,
    "Mike Evans": 0.964,
    "Tee Higgins": 0.964,
    "Trey McBride": 0.964,
    "Tucker Kraft": 0.964,
    "Christian McCaffrey": 0.958,
    "De'Von Achane": 0.928,
    "Dallas Goedert": 0.916,
    "Josh Jacobs": 0.916,
}

# Projection multipliers from OC-scheme + role/value research (averaged across two passes).
ADP_OVERRIDE = {
    # player name -> current market ADP, for when news has moved a player past the stale feed
    # ADP (e.g. Lloyd surged to ~90 on the Jacobs news but the projection feed still said 158).
    # Populated by the day-of research sweep; robust (no fragile live scrape).
    # "MarShawn Lloyd": 90,
}

BUMP = {
    "MarShawn Lloyd": 1.15,   # scheme only; Jacobs-out workload now auto-transferred in data.py
    "Ashton Jeanty": 1.13,
    "DeVonta Smith": 1.12,
    "Omarion Hampton": 1.12,
    "Quinshon Judkins": 1.12,
    "Sam LaPorta": 1.12,
    "Jadarian Price": 1.115,
    "Colston Loveland": 1.1,
    "Justin Jefferson": 1.1,
    "Tetairoa McMillan": 1.1,
    "Tyler Allgeier": 1.1,
    "Zay Flowers": 1.1,
    "Ladd McConkey": 1.095,
    "Bhayshul Tuten": 1.09,
    "Emeka Egbuka": 1.09,
    "Kenny Gainwell": 1.085,
    "A.J. Brown": 1.08,
    "Blake Corum": 1.08,
    "Chase Brown": 1.08,
    "DJ Moore": 1.08,
    "Darnell Washington": 1.08,
    "Elic Ayomanor": 1.08,
    "Gunnar Helm": 1.08,
    "Isaiah Likely": 1.08,
    "Jonathon Brooks": 1.08,
    "Jordan Mason": 1.08,
    "Juwan Johnson": 1.08,
    "Kyle Pitts": 1.08,
    "Kyler Murray": 1.08,
    "Malik Nabers": 1.08,
    "RJ Harvey": 1.08,
    "Terrance Ferguson": 1.08,
    "Tucker Kraft": 1.08,
    "Wan'Dale Robinson": 1.08,
    "Luther Burden": 1.075,
    "Bucky Irving": 1.07,
    "Chris Olave": 1.07,
    "Evan Engram": 1.07,
    "Jordan Addison": 1.07,
    "Stefon Diggs": 1.07,
    "Travis Etienne": 1.07,
    "Brock Bowers": 1.065,
    "George Pickens": 1.065,
    "Jahmyr Gibbs": 1.065,
    "AJ Barner": 1.06,
    "Dallas Goedert": 1.06,
    "Deebo Samuel": 1.06,
    "Drake London": 1.06,
    "Drake Maye": 1.06,
    "Kayshon Boutte": 1.06,
    "Najee Harris": 1.06,
    "Rashee Rice": 1.06,
    "Tyjae Spears": 1.06,
    "Rhamondre Stevenson": 1.055,
    "Ja'Marr Chase": 1.05,
    "Jalen Coker": 1.05,
    "Javonte Williams": 1.05,
    "Keenan Allen": 1.05,
    "Mark Andrews": 1.05,
    "Michael Pittman": 1.05,
    "Rashid Shaheed": 1.05,
    "T.J. Hockenson": 1.05,
    "Adonai Mitchell": 1.04,
    "Baker Mayfield": 1.04,
    "Bijan Robinson": 1.04,
    "Jonathan Taylor": 1.04,
    "Mason Taylor": 1.04,
    "Tyler Warren": 1.04,
    "Carnell Tate": 1.03,
    "CeeDee Lamb": 1.03,
    "Jaylen Waddle": 1.03,
    "Jordan Whittington": 1.03,
    "Tre' Harris": 1.03,
    "Kenneth Walker": 1.02,
    "Nico Collins": 1.02,
    "D'Andre Swift": 1.015,
    "Jacory Croskey-Merritt": 1.005,
    "Amon-Ra St. Brown": 1.0,
    "Cam Skattebo": 0.985,
    "David Montgomery": 0.98,
    "David Njoku": 0.98,
    "Garrett Wilson": 0.98,
    "Jaxon Smith-Njigba": 0.98,
    "Saquon Barkley": 0.98,
    "Cam Ward": 0.975,
    "Jaylen Warren": 0.975,
    "Jayden Daniels": 0.97,
    "Jake Ferguson": 0.96,
    "Terry McLaurin": 0.96,
    "Brian Thomas": 0.95,
    "Tank Bigsby": 0.95,
    "Woody Marks": 0.95,
    "Jared Goff": 0.94,
    "Marvin Harrison": 0.94,
    "DK Metcalf": 0.935,
    "Tony Pollard": 0.925,
    "Calvin Ridley": 0.92,
    "Christian McCaffrey": 0.92,
    "Chuba Hubbard": 0.92,
    "De'Von Achane": 0.92,
    "George Kittle": 0.92,
    "Travis Kelce": 0.92,
    "TreVeyon Henderson": 0.92,
    "Trey McBride": 0.915,
    "Courtland Sutton": 0.91,
    "Josh Downs": 0.91,
    "Aaron Jones": 0.9,
    "Cole Kmet": 0.9,
    "Cooper Kupp": 0.9,
    "J.K. Dobbins": 0.9,
    "Jameson Williams": 0.9,
    "Pat Freiermuth": 0.9,
    "Rashod Bateman": 0.9,
    "Rico Dowdle": 0.9,
    "Breece Hall": 0.88,
    "Christian Kirk": 0.88,
    "Michael Penix": 0.88,
    "Kyren Williams": 0.86,
    "Alvin Kamara": 0.85,
    "Jalen McMillan": 0.85,
    "Jerry Jeudy": 0.85,
    "Josh Jacobs": 0.85,
    "Kaleb Johnson": 0.85,
    "Keon Coleman": 0.85,
    "Travis Hunter": 0.85,
    "Xavier Legette": 0.85,
}
