"""Günlük çalıştırma: veriyi indir, bülteni kur, her maçı analiz et, JSON yaz.

Kullanım:  python src/run.py            (internetten indirir)
           python src/run.py --offline  (data/raw içindekiyle çalışır)
           python src/run.py --date 2026-10-30
"""
import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DAYS_AHEAD, LEAGUES, TIMEZONE, season_codes  # noqa: E402
from fetch import load_elo_ratings, load_fixtures, load_mackolik, load_results, load_uefa  # noqa: E402
from names import build_matcher  # noqa: E402
from report import Context, analyze  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "data"


def uk_to_local(d, t, tz):
    """football-data saatleri İngiltere saatidir."""
    if not isinstance(t, str) or ":" not in t:
        return d.date(), None
    hh, mm = t.split(":")[:2]
    dt = datetime(d.year, d.month, d.day, int(hh), int(mm), tzinfo=ZoneInfo("Europe/London"))
    loc = dt.astimezone(tz)
    return loc.date(), loc.strftime("%H:%M")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--date")
    args = ap.parse_args()

    tz = ZoneInfo(TIMEZONE)
    today = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else datetime.now(tz).date()
    days = {today + timedelta(d) for d in range(DAYS_AHEAD + 1)}
    ref = pd.Timestamp(today)

    print(f"[1/4] Veri indiriliyor ({today})")
    results = load_results(season_codes(today), offline=args.offline)
    fixtures = load_fixtures(offline=args.offline)
    uefa = load_uefa(today, offline=args.offline)
    elo = load_elo_ratings(today, offline=args.offline)
    mack = load_mackolik(days, offline=args.offline)
    if results.empty:
        print("HATA: maç verisi yok")
        sys.exit(1)

    print(f"[2/4] Modeller kuruluyor ({len(results)} maç)")
    ctx = Context(results, ref, elo)
    team_country = {t: LEAGUES[lg][1] for t, lg in ctx.team_league.items()}
    match = build_matcher(ctx.team_league, team_country)
    ctx.calibrate_uefa(uefa, match)
    print(f"      UEFA kalibrasyonu: {ctx.uefa['n']} maç")

    print("[3/4] Bülten hazırlanıyor")
    bulletin, seen = [], set()

    # Lig maçları (oranlarıyla)
    for _, r in fixtures.iterrows():
        d, t = uk_to_local(r.Date, r.get("Time"), tz)
        if d not in days:
            continue
        h, a = r.HomeTeam, r.AwayTeam
        bulletin.append({
            "date": d.isoformat(), "time": t, "home": h, "away": a,
            "comp_type": "lig", "comp_name": LEAGUES[r.Div][0], "div": r.Div,
            "odds_row": r, "referee": r.get("Referee") if isinstance(r.get("Referee"), str) else None,
        })
        seen.add((h, a))
    by_pair = {(fx["home"], fx["away"]): fx for fx in bulletin}

    # Maçkolik bülteni: iddaa oranlarını ekle, eksik lig maçlarını ve kupaları al
    no_data, unmatched_league = [], []
    for mm in mack:
        if mm["date"] not in days:
            continue
        h, a = match(mm["home"], mm["code"]), match(mm["away"], mm["code"])
        if (h, a) in by_pair:
            by_pair[(h, a)].update({"iddaa": mm["odds"], "label_home": mm["home"], "label_away": mm["away"]})
            continue
        lg_h, lg_a = ctx.team_league.get(h), ctx.team_league.get(a)
        title = f"{mm['country']} {mm['league']}"
        is_cup = mm["uefa"] or mm["cup"] or "Kupa" in mm["league"]
        if not (h or a):
            if is_cup:  # takip dışı lig maçları zaten gereksiz, listelenmez
                no_data.append({"mac": f"{mm['home']} - {mm['away']}", "turnuva": title, "saat": mm["time"]})
            continue
        if mm["uefa"]:
            ctype = "avrupa"
        elif is_cup:
            ctype = "kupa"
        elif h and a and lg_h == lg_a:
            ctype = "lig"
        else:
            unmatched_league.append(f"{mm['home']} - {mm['away']} ({title})")
            continue
        fx = {
            "date": mm["date"].isoformat(), "time": mm["time"],
            "home": h or mm["home"], "away": a or mm["away"],
            "comp_type": ctype, "comp_name": LEAGUES[lg_h][0] if ctype == "lig" else title,
            "div": lg_h if ctype == "lig" else None,
            "odds_row": None, "iddaa": mm["odds"], "referee": None,
            "country": mm["code"], "label_home": mm["home"], "label_away": mm["away"],
        }
        bulletin.append(fx)
        by_pair[(h, a)] = fx
        seen.add((h, a))

    # UEFA kupa maçları (en az bir takım takip ettiğimiz liglerden olmalı)
    uefa_in_days = unmatched = 0
    if not uefa.empty:
        for r in uefa.itertuples():
            loc = r.Date.tz_convert(tz)
            d = loc.date()
            if d not in days:
                continue
            uefa_in_days += 1
            h, a = match(r.Home), match(r.Away)
            if not h and not a:
                unmatched += 1
                continue  # iki takım da takip dışı liglerden
            if (h, a) in seen:
                continue
            bulletin.append({
                "date": d.isoformat(), "time": loc.strftime("%H:%M"),
                "home": h or r.Home, "away": a or r.Away,
                "elo_home": None if h else r.Home, "elo_away": None if a else r.Away,
                "comp_type": "avrupa", "comp_name": r.Comp, "div": None,
                "odds_row": None, "referee": None,
            })
            seen.add((h, a))

    print(f"[4/4] {len(bulletin)} maç analiz ediliyor")
    reports, skipped = [], []
    for fx in bulletin:
        try:
            rep = analyze(ctx, fx)
        except Exception as e:  # tek maç hatası tüm çalışmayı durdurmasın
            print(f"  ! {fx['home']} - {fx['away']}: {e}")
            rep = None
        if rep:
            reports.append(rep)
        else:
            skipped.append(f"{fx['home']} - {fx['away']}")

    reports.sort(key=lambda x: (x["tarih"], x["saat"] or "99:99", x["turnuva"]))
    diag = {
        "sonuc_satir": {c: int((results.Div == c).sum()) for c in LEAGUES},
        "fikstur_toplam": int(len(fixtures)),
        "fikstur_tarihler": sorted({str(x.date()) for x in fixtures.Date}) if not fixtures.empty else [],
        "uefa_toplam": int(len(uefa)),
        "uefa_gun_icinde": uefa_in_days,
        "uefa_eslesmeyen": unmatched,
        "elo_takim": len(elo),
        "uefa_kalibrasyon_mac": ctx.uefa["n"],
        "lig_gucu": {k: round(v, 2) for k, v in ctx.uefa["S"].items()},
        "diger_lig_gucu": round(ctx.uefa["S_other"], 2),
        "atlanan_maclar": skipped,
        "mackolik_mac": len(mack),
        "eslesmeyen_lig_maci": unmatched_league,
    }
    out = {
        "kaynak": diag,
        "olusturma": datetime.now(tz).strftime("%d.%m.%Y %H:%M"),
        "gunler": sorted(d.isoformat() for d in days),
        "mac_sayisi": len(reports),
        "atlanan": len(skipped),
        "maclar": reports,
        "veri_yok": no_data,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "archive").mkdir(exist_ok=True)
    payload = json.dumps(out, ensure_ascii=False, default=float)
    (OUT / "latest.json").write_text(payload, encoding="utf-8")
    (OUT / "archive" / f"{today.isoformat()}.json").write_text(payload, encoding="utf-8")
    print(f"Tamam: {len(reports)} rapor, {len(skipped)} maç atlandı.")


if __name__ == "__main__":
    main()
