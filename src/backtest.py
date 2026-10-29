"""Geriye dönük test: model geçmişte ne kadar isabetli olurdu, değer sinyalleri kâr ettirir miydi?

Her hafta için model sadece o tarihten önceki veriyle kurulur (geleceği görmez),
o haftanın maçları tahmin edilir. Sonuç docs/data/backtest.json dosyasına yazılır.
python src/backtest.py [--offline] [--weeks 30]
"""
import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import LEAGUES, TIMEZONE, VALUE_EDGE, season_codes  # noqa: E402
from fetch import load_results  # noqa: E402
from model import GoalModel, goal_markets, score_matrix  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "docs" / "data" / "backtest.json"
ODDS = {"1": ["AvgH", "B365H"], "X": ["AvgD", "B365D"], "2": ["AvgA", "B365A"],
        "2.5 Üst": ["Avg>2.5", "B365>2.5"], "2.5 Alt": ["Avg<2.5", "B365<2.5"]}


def odd(row, keys):
    for k in keys:
        v = row.get(k)
        if v is not None and pd.notna(v) and float(v) > 1:
            return float(v)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--weeks", type=int, default=30)
    args = ap.parse_args()
    today = datetime.now(ZoneInfo(TIMEZONE)).date()
    res = load_results(season_codes(today), offline=args.offline)
    if res.empty:
        sys.exit("veri yok")

    end = res.Date.max()
    starts = pd.date_range(end=end, periods=args.weeks, freq="7D")
    stats = {}

    def acc(key):
        return stats.setdefault(key, {"n": 0, "hit": 0, "brier": 0.0, "bets": 0, "won": 0, "profit": 0.0})

    for code in LEAGUES:
        d = res[res.Div == code]
        if len(d) < 150:
            continue
        for ws in starts:
            train = d[d.Date < ws]
            test = d[(d.Date >= ws) & (d.Date < ws + pd.Timedelta(days=7))]
            if len(train) < 120 or test.empty:
                continue
            gm = GoalModel(train, ws)
            for _, r in test.iterrows():
                if not (gm.has(r.HomeTeam) and gm.has(r.AwayTeam)):
                    continue
                lh, la = gm.lambdas(r.HomeTeam, r.AwayTeam)
                mk = goal_markets(score_matrix(lh, la, gm.rho))
                hg, ag = int(r.FTHG), int(r.FTAG)
                actual = {"1": hg > ag, "X": hg == ag, "2": hg < ag,
                          "2.5 Üst": hg + ag > 2, "2.5 Alt": hg + ag < 3}
                for grp, keys in (("MS", ("1", "X", "2")), ("2.5", ("2.5 Üst", "2.5 Alt"))):
                    for scope in ("Tümü", LEAGUES[code][0]):
                        a = acc((scope, grp))
                        pick = max(keys, key=lambda k: mk[k])
                        a["n"] += 1
                        a["hit"] += int(actual[pick])
                        a["brier"] += sum((mk[k] - actual[k]) ** 2 for k in keys)
                        for k in keys:  # değer sinyali: model olasılığı x oran - 1 >= eşik
                            o = odd(r, ODDS[k])
                            if o and mk[k] * o - 1 >= VALUE_EDGE and mk[k] >= 0.33:
                                a["bets"] += 1
                                a["won"] += int(actual[k])
                                a["profit"] += (o - 1) if actual[k] else -1

    rows = []
    for (scope, grp), a in stats.items():
        if a["n"] == 0:
            continue
        rows.append({
            "kapsam": scope, "pazar": "Maç sonucu (1X2)" if grp == "MS" else "2.5 Üst/Alt",
            "mac": a["n"], "isabet": round(100 * a["hit"] / a["n"], 1),
            "brier": round(a["brier"] / a["n"], 3),
            "deger_bahis": a["bets"],
            "deger_kazanan": round(100 * a["won"] / a["bets"], 1) if a["bets"] else None,
            "roi": round(100 * a["profit"] / a["bets"], 1) if a["bets"] else None,
        })
    rows.sort(key=lambda x: (x["kapsam"] != "Tümü", x["kapsam"], x["pazar"]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"olusturma": datetime.now(ZoneInfo(TIMEZONE)).strftime("%d.%m.%Y %H:%M"),
                               "hafta": args.weeks, "satirlar": rows}, ensure_ascii=False), encoding="utf-8")
    for r in rows[:4]:
        print(r)


if __name__ == "__main__":
    main()
