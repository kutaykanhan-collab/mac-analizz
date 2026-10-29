"""Canlı gol modelinin geçmiş maçlarda testi ve parametre ayarı.

Her maç için 10, 20, 30, 40, 55, 65, 75, 85. dakikalarda "şu anki bilgilerle" tahmin
yapılır ve gerçekte ne olduğuyla karşılaştırılır. Parametreler maçların %70'inde ayarlanır,
sonuç görülmemiş %30'da ölçülür. Çıktılar:
  docs/data/live_params.json  (sitedeki canlı model bu ayarları kullanır)
  docs/data/live_test.json    (Model Testi sekmesindeki canlı model bölümü)
"""
import itertools
import json
import math
import random
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import LEAGUES, TIMEZONE, season_codes  # noqa: E402
from fetch import load_results  # noqa: E402
from live_model import DEFAULT, outputs, rates  # noqa: E402
from model import fit_lambdas  # noqa: E402
from names import build_matcher  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "live" / "maclar.jsonl"
OUT_P = ROOT / "docs" / "data" / "live_params.json"
OUT_T = ROOT / "docs" / "data" / "live_test.json"
CHECK = [(10, 1), (20, 1), (30, 1), (40, 1), (55, 2), (65, 2), (75, 2), (85, 2)]


def prior_from_odds(row):
    """Bahis oranlarından maç öncesi gol beklentisi (yoksa None)."""
    try:
        o1, ox, o2 = float(row["AvgH"]), float(row["AvgD"]), float(row["AvgA"])
        s = 1 / o1 + 1 / ox + 1 / o2
        sup = (1 / o1 - 1 / o2) / s
        ou = None
        if pd.notna(row.get("Avg>2.5")) and pd.notna(row.get("Avg<2.5")):
            a, b = float(row["Avg>2.5"]), float(row["Avg<2.5"])
            ou = (1 / a) / (1 / a + 1 / b)
        return fit_lambdas(1.4, 1.15, sup, ou if ou is not None else 0.52)
    except (TypeError, ValueError, KeyError):
        return None


def in_first_half(t):
    return t <= 45


def before(t, M, half):
    if half == 1:
        return in_first_half(t) and t < M
    return in_first_half(t) or t < M


def snapshots(m, sign):
    """Bir maçtan kontrol noktası anlık görüntüleri."""
    out = []
    goals = m["goals"]
    for M, half in CHECK:
        gh = sum(1 for t, _, h in goals if h == 1 and before(t, M, half))
        ga = sum(1 for t, _, h in goals if h == 0 and before(t, M, half))
        rem = len(goals) - gh - ga
        if half == 1:
            nxt = sum(1 for t, _, _ in goals if M <= t < M + 10 and t <= 45)
        else:
            nxt = sum(1 for t, _, _ in goals if t > 45 and M <= t < M + 10)
        xh = xa = 0.0
        for mn, _, home, xg, _, _, per in m["shots"]:
            ok = (per == "FirstHalf" and (half == 2 or mn < M)) or (per == "SecondHalf" and half == 2 and mn < M)
            if ok:
                if home:
                    xh += xg
                else:
                    xa += xg
        rh = sum(1 for t, _, h in m["reds"] if h == 1 and before(t, M, half))
        ra = sum(1 for t, _, h in m["reds"] if h == 0 and before(t, M, half))
        mv = [v for mn, v in m["momentum"] if M - 10 <= mn < M]
        mom = sign * (sum(mv) / len(mv) / 100) if mv else 0.0
        out.append({"M": M, "half": half, "gh": gh, "ga": ga, "xh": xh, "xa": xa, "rh": rh, "ra": ra,
                    "mom": mom, "rem": rem, "next": nxt})
    return out


def ll(p, y):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def evaluate(rows, p):
    a = b = 0.0
    for lh, la, s in rows:
        r = rates(lh, la, s["M"], s["half"], s["xh"], s["xa"], s["gh"], s["ga"], s["rh"], s["ra"], s["mom"], p)
        lam = r["rem_h"] + r["rem_a"]
        a += ll(1 - math.exp(-lam), 1 if s["rem"] > 0 else 0)
        b += ll(1 - math.exp(-(r["next_h"] + r["next_a"])), 1 if s["next"] > 0 else 0)
    n = max(len(rows), 1)
    return a / n, b / n


def calibration(rows, p, key):
    bins = [(0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.01)]
    acc = {bb: [0, 0, 0.0] for bb in bins}
    for lh, la, s in rows:
        r = rates(lh, la, s["M"], s["half"], s["xh"], s["xa"], s["gh"], s["ga"], s["rh"], s["ra"], s["mom"], p)
        if key == "rem":
            pr, y = 1 - math.exp(-(r["rem_h"] + r["rem_a"])), s["rem"] > 0
        else:
            pr, y = 1 - math.exp(-(r["next_h"] + r["next_a"])), s["next"] > 0
        for bb in bins:
            if bb[0] <= pr < bb[1]:
                acc[bb][0] += 1
                acc[bb][1] += int(y)
                acc[bb][2] += pr
    return [{"aralik": f"%{int(lo * 100)}-{min(int(hi * 100), 100)}", "n": n,
             "tahmin": round(100 * sp / n, 1) if n else None, "gercek": round(100 * k / n, 1) if n else None}
            for (lo, hi), (n, k, sp) in acc.items()]


def main():
    if not DATA.exists():
        sys.exit("canlı veri yok")
    matches = [json.loads(x) for x in DATA.read_text(encoding="utf-8").splitlines() if x.strip()]
    today = datetime.now(ZoneInfo(TIMEZONE)).date()
    res = load_results(season_codes(today), offline=True)
    team_country = {}
    for code, (_, cc) in LEAGUES.items():
        for t in set(res[res.Div == code].HomeTeam):
            team_country[t] = cc
    match = build_matcher(team_country, team_country)
    res["d"] = res.Date.dt.date

    # Baskı işaretini doğrula: pozitif = ev sahibi mi?
    num = 0.0
    for m in matches:
        mv = [v for _, v in m["momentum"]]
        xh = sum(s[3] for s in m["shots"] if s[2] == 1)
        xa = sum(s[3] for s in m["shots"] if s[2] == 0)
        if mv:
            num += (sum(mv) / len(mv)) * (xh - xa)
    sign = 1 if num >= 0 else -1

    rows_by_match = []
    skipped = 0
    for m in matches:
        if m["hg"] is None or len(m["goals"]) != (m["hg"] or 0) + (m["ag"] or 0):
            skipped += 1
            continue
        cc = LEAGUES.get(m["lig"], ("", ""))[1]
        h, a = match(m["ev"], cc), match(m["dep"], cc)
        d = datetime.fromisoformat(m["tarih"]).date()
        cand = res[(res.HomeTeam == h) & (res.AwayTeam == a)] if h and a else res.iloc[0:0]
        cand = cand[(cand.d >= d - pd.Timedelta(days=1).to_pytimedelta()) & (cand.d <= d + pd.Timedelta(days=1).to_pytimedelta())]
        pri = prior_from_odds(cand.iloc[0]) if len(cand) else None
        if not pri:
            skipped += 1
            continue
        rows_by_match.append([(pri[0], pri[1], s) for s in snapshots(m, sign)])
    random.seed(7)
    random.shuffle(rows_by_match)
    cut = int(len(rows_by_match) * 0.7)
    train = [r for g in rows_by_match[:cut] for r in g]
    test = [r for g in rows_by_match[cut:] for r in g]
    print(f"{len(matches)} maç, {len(rows_by_match)} oranla eşleşti ({skipped} atlandı); eğitim {len(train)}, test {len(test)} anlık görüntü")
    if len(rows_by_match) < 60:
        sys.exit("yeterli eşleşen maç yok")

    base = dict(DEFAULT)
    variants = {
        "Sadece maç öncesi beklenti": {**base, "T0": 1e9, "beta": 0.0, "trail": 1.0, "lead": 1.0},
    }
    best, best_score = None, 1e9
    grid = itertools.product((60, 150, 300, 600), (0, 0.4, 0.8, 1.2), (1.0, 1.15, 1.3), (0.9, 1.0),
                             (0.0, 0.3, 0.6), (5.0, 8.0), (1.0, 1.05, 1.1))
    for T0, beta, trail, lead, g, s2, scale in grid:
        p = {**base, "T0": T0, "beta": beta, "trail": trail, "lead": lead, "g": g, "stoppage2": s2,
             "stoppage1": 3.0 if s2 >= 8 else 2.0, "scale": scale}
        a, b = evaluate(train, p)
        if a + b < best_score:
            best, best_score = p, a + b
    variants["+ zaman etkisi ve uzatma"] = {**best, "T0": 1e9, "beta": 0.0, "trail": 1.0, "lead": 1.0}
    variants["+ xG temposu"] = {**best, "beta": 0.0, "trail": 1.0, "lead": 1.0}
    variants["+ skor durumu ve kart"] = {**best, "beta": 0.0}
    variants["+ baskı (tam model)"] = best

    tablo = []
    for name, p in variants.items():
        a, b = evaluate(test, p)
        tablo.append({"model": name, "kalan_sure_hata": round(a, 4), "sonraki10_hata": round(b, 4)})
    print(json.dumps(tablo, ensure_ascii=False, indent=1))
    OUT_P.parent.mkdir(parents=True, exist_ok=True)
    OUT_P.write_text(json.dumps({**best, "baski_isareti": sign}, ensure_ascii=False), encoding="utf-8")
    OUT_T.write_text(json.dumps({
        "olusturma": datetime.now(ZoneInfo(TIMEZONE)).strftime("%d.%m.%Y %H:%M"),
        "mac": len(rows_by_match), "test_anlik": len(test), "parametreler": best, "karsilastirma": tablo,
        "kalibrasyon_kalan": calibration(test, best, "rem"),
        "kalibrasyon_10dk": calibration(test, best, "next"),
    }, ensure_ascii=False), encoding="utf-8")
    print("en iyi:", best)


if __name__ == "__main__":
    main()
