"""Geriye dönük test: model geçmişte ne kadar isabetli olurdu?

Her hafta için model sadece o tarihten önceki veriyle kurulur (geleceği görmez),
o haftanın maçları tahmin edilir. Üç yöntem karşılaştırılır:
  - Model: sadece istatistik modeli
  - Piyasa: bahis oranlarından çıkan olasılık
  - Model + piyasa: sitede gösterilen nihai olasılık
Ayrıca "model piyasadan yüksek görüyor" sinyaline oynansaydı getiri (ROI) hesaplanır.
Sonuç docs/data/backtest.json dosyasına yazılır.
python src/backtest.py [--offline] [--weeks 30]
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import LEAGUES, MODEL_WEIGHT, TIMEZONE, VALUE_EDGE, season_codes  # noqa: E402
from fetch import load_results  # noqa: E402
from model import GoalModel, goal_markets, score_matrix  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "docs" / "data" / "backtest.json"
ODDS = [("1", "AvgH", "B365H"), ("X", "AvgD", "B365D"), ("2", "AvgA", "B365A"),
        ("Ü", "Avg>2.5", "B365>2.5"), ("A", "Avg<2.5", "B365<2.5")]


def odd(row, keys):
    for k in keys:
        v = row.get(k)
        if v is not None and pd.notna(v) and float(v) > 1:
            return float(v)
    return None


def collect(res, weeks):
    end = res.Date.max()
    starts = pd.date_range(end=end, periods=weeks, freq="7D")
    rows = []
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
                mk = goal_markets(score_matrix(*gm.lambdas(r.HomeTeam, r.AwayTeam), gm.rho))
                o = {k: odd(r, keys) for k, *keys in ODDS}
                if not all(o.values()):
                    continue
                rows.append({"lig": LEAGUES[code][0], "p1": mk["1"], "px": mk["X"], "p2": mk["2"],
                             "pu": mk["2.5 Üst"], "hg": int(r.FTHG), "ag": int(r.FTAG),
                             **{f"o{k}": v for k, v in o.items()}})
    return pd.DataFrame(rows)


def evaluate(df):
    s3 = 1 / df.o1 + 1 / df.oX + 1 / df.o2
    m = {"1": (1 / df.o1) / s3, "X": (1 / df.oX) / s3, "2": (1 / df.o2) / s3}
    s2 = 1 / df.oÜ + 1 / df.oA
    mu = (1 / df.oÜ) / s2
    y = {"1": df.hg > df.ag, "X": df.hg == df.ag, "2": df.hg < df.ag}
    yu = (df.hg + df.ag) > 2
    w = MODEL_WEIGHT
    methods = {
        "Model": ({"1": df.p1, "X": df.px, "2": df.p2}, df.pu),
        "Piyasa (oranlar)": (m, mu),
        "Model + piyasa": ({k: w * v + (1 - w) * m[k] for k, v in {"1": df.p1, "X": df.px, "2": df.p2}.items()},
                           w * df.pu + (1 - w) * mu),
    }
    out = []
    for name, (p, pu) in methods.items():
        P = pd.concat([p["1"], p["X"], p["2"]], axis=1).to_numpy()
        Y = pd.concat([y["1"], y["X"], y["2"]], axis=1).to_numpy()
        hit = Y[np.arange(len(P)), P.argmax(1)].mean()
        brier = ((P - Y) ** 2).sum(1).mean()
        hit_u = ((pu >= 0.5) == yu).mean()
        out.append({"yontem": name, "mac": int(len(df)), "ms_isabet": round(100 * hit, 1),
                    "ms_brier": round(float(brier), 3), "ust_isabet": round(100 * hit_u, 1)})
    # Model farkı sinyali: model olasılığı x oran - 1 >= eşik
    bets = won = 0
    profit = 0.0
    for p, o, yy in ((df.p1, df.o1, y["1"]), (df.px, df.oX, y["X"]), (df.p2, df.o2, y["2"]),
                     (df.pu, df.oÜ, yu), (1 - df.pu, df.oA, ~yu)):
        sel = (p * o - 1 >= VALUE_EDGE) & (p >= 0.33)
        bets += int(sel.sum())
        won += int(yy[sel].sum())
        profit += float(np.where(yy[sel], o[sel] - 1, -1).sum())
    sig = {"bahis": bets, "kazanan": round(100 * won / bets, 1) if bets else None,
           "roi": round(100 * profit / bets, 1) if bets else None}
    return out, sig


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--weeks", type=int, default=30)
    args = ap.parse_args()
    today = datetime.now(ZoneInfo(TIMEZONE)).date()
    res = load_results(season_codes(today), offline=args.offline)
    if res.empty:
        sys.exit("veri yok")
    df = collect(res, args.weeks)
    if df.empty:
        sys.exit("test için yeterli maç yok")
    genel, sinyal = evaluate(df)
    ligler = []
    for lig, g in df.groupby("lig"):
        if len(g) < 40:
            continue
        rows, sg = evaluate(g)
        mp = {r["yontem"]: r for r in rows}
        ligler.append({"lig": lig, "mac": len(g), "model": mp["Model"]["ms_isabet"],
                       "piyasa": mp["Piyasa (oranlar)"]["ms_isabet"], "nihai": mp["Model + piyasa"]["ms_isabet"],
                       "ust": mp["Model + piyasa"]["ust_isabet"], "sinyal_roi": sg["roi"]})
    ligler.sort(key=lambda x: -x["mac"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "olusturma": datetime.now(ZoneInfo(TIMEZONE)).strftime("%d.%m.%Y %H:%M"),
        "hafta": args.weeks, "genel": genel, "sinyal": sinyal, "ligler": ligler,
    }, ensure_ascii=False), encoding="utf-8")
    for r in genel:
        print(r)
    print("sinyal", sinyal)


if __name__ == "__main__":
    main()
