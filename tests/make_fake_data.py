"""Sahte ama gerçekçi veri üretir; sistemi internetsiz test etmek için.
python tests/make_fake_data.py && python src/run.py --offline --date 2026-10-29"""
from pathlib import Path

import numpy as np
import pandas as pd

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)
rng = np.random.default_rng(7)

LG = {
    "T1": ["Galatasaray", "Fenerbahce", "Besiktas", "Trabzonspor", "Goztep", "Samsunspor", "Buyuksehyr",
           "Kasimpasa", "Rizespor", "Antalyaspor", "Konyaspor", "Alanyaspor", "Kayserispor", "Eyupspor",
           "Gaziantep", "Kocaelispor", "Genclerbirligi", "Karagumruk"],
    "E0": ["Liverpool", "Arsenal", "Man City", "Chelsea", "Tottenham", "Man United", "Newcastle", "Aston Villa",
           "Brighton", "Everton", "Fulham", "Brentford", "Bournemouth", "Crystal Palace", "Wolves",
           "Nott'm Forest", "West Ham", "Leeds", "Burnley", "Sunderland"],
}
REFS = ["M Oliver", "A Taylor", "S Hooper", "C Kavanagh", "P Tierney", "J Gillett"]


def season(code, teams, start, n_rounds=None):
    k = len(teams)
    strength = {t: rng.normal(0, 0.35) for t in teams}
    strength[teams[0]] += 0.4
    strength[teams[1]] += 0.3
    rows = []
    pairs = [(h, a) for h in teams for a in teams if h != a]
    rng.shuffle(pairs)
    if n_rounds:
        pairs = pairs[: n_rounds * k // 2]
    for i, (h, a) in enumerate(pairs):
        dt = start + pd.Timedelta(days=int(i / (k / 2)) * 7)
        lh = np.exp(0.25 + 0.2 + strength[h] - 0.6 * strength[a])
        la = np.exp(0.25 + strength[a] - 0.6 * strength[h])
        hg, ag = rng.poisson(lh), rng.poisson(la)
        hth, hta = rng.binomial(hg, 0.44), rng.binomial(ag, 0.44)
        ref = rng.choice(REFS)
        rf = 1.3 if ref == "A Taylor" else 1.0
        rows.append({
            "Div": code, "Date": dt.strftime("%d/%m/%Y"), "Time": "19:00", "HomeTeam": h, "AwayTeam": a,
            "FTHG": hg, "FTAG": ag, "FTR": "H" if hg > ag else ("D" if hg == ag else "A"),
            "HTHG": hth, "HTAG": hta, "Referee": ref if code == "E0" else np.nan,
            "HS": rng.poisson(13 * np.exp(0.5 * strength[h])), "AS": rng.poisson(10.5 * np.exp(0.5 * strength[a])),
            "HST": rng.poisson(4.6 * np.exp(0.5 * strength[h])), "AST": rng.poisson(3.8 * np.exp(0.5 * strength[a])),
            "HC": rng.poisson(5.4 * np.exp(0.3 * strength[h])), "AC": rng.poisson(4.4 * np.exp(0.3 * strength[a])),
            "HY": rng.poisson(1.9 * rf), "AY": rng.poisson(2.2 * rf), "HR": rng.binomial(1, 0.05), "AR": rng.binomial(1, 0.06),
            "AvgH": 2.1, "AvgD": 3.3, "AvgA": 3.5,
        })
    return pd.DataFrame(rows)


for code, teams in LG.items():
    season(code, teams, pd.Timestamp("2025-08-10")).to_csv(RAW / f"{code}_2526.csv", index=False)
    season(code, teams, pd.Timestamp("2026-08-15"), n_rounds=9).to_csv(RAW / f"{code}_2627.csv", index=False)

fx = pd.DataFrame([
    {"Div": "T1", "Date": "29/10/2026", "Time": "17:00", "HomeTeam": "Galatasaray", "AwayTeam": "Fenerbahce",
     "AvgH": 2.05, "AvgD": 3.55, "AvgA": 3.40, "Avg>2.5": 1.72, "Avg<2.5": 2.10},
    {"Div": "T1", "Date": "29/10/2026", "Time": "14:30", "HomeTeam": "Konyaspor", "AwayTeam": "Rizespor",
     "AvgH": 2.30, "AvgD": 3.20, "AvgA": 3.10, "Avg>2.5": 1.95, "Avg<2.5": 1.85},
    {"Div": "E0", "Date": "29/10/2026", "Time": "19:45", "HomeTeam": "Arsenal", "AwayTeam": "Everton",
     "Referee": "A Taylor", "AvgH": 1.40, "AvgD": 4.80, "AvgA": 7.50, "Avg>2.5": 1.65, "Avg<2.5": 2.25},
    {"Div": "E0", "Date": "30/10/2026", "Time": "20:00", "HomeTeam": "Burnley", "AwayTeam": "Leeds",
     "AvgH": 2.60, "AvgD": 3.20, "AvgA": 2.80},
])
fx.to_csv(RAW / "fixtures.csv", index=False)

gd_cols = ["GD<-5", "GD=-5", "GD=-4", "GD=-3", "GD=-2", "GD=-1", "GD=0", "GD=1", "GD=2", "GD=3", "GD=4", "GD=5", "GD>5"]


def elo_row(date, country, h, a, ph, pd_, pa):
    neg = [0.002, 0.004, 0.01, 0.03, 0.08] + [0]
    r = {"Date": date, "Country": country, "Home": h, "Away": a}
    vals = np.array([0.001, 0.003, 0.01, 0.03, 0.10, 0.25, pd_ / 1, 0.25, 0.10, 0.03, 0.01, 0.003, 0.001])
    vals[:6] = vals[:6] / vals[:6].sum() * pa
    vals[7:] = vals[7:] / vals[7:].sum() * ph
    r.update(dict(zip(gd_cols, vals)))
    return r


elo = pd.DataFrame([
    elo_row("2026-10-29", "TUR", "Galatasaray", "Fenerbahce", 0.45, 0.27, 0.28),   # lig, zaten var
    elo_row("2026-10-29", "TUR", "Galatasaray", "Liverpool", 0.33, 0.26, 0.41),    # Avrupa
    elo_row("2026-10-30", "TUR", "Besiktas", "Trabzonspor", 0.48, 0.27, 0.25),     # kupa ya da lig
    elo_row("2026-10-30", "AUT", "Sturm Graz", "Salzburg", 0.40, 0.27, 0.33),      # takip dışı -> atlanır
    elo_row("2026-10-30", "ENG", "Man City", "Bodo/Glimt", 0.80, 0.13, 0.07),      # Avrupa, rakip verisiz
])
elo.to_csv(RAW / "clubelo_fixtures.csv", index=False)
print("Sahte veri yazıldı:", RAW)
