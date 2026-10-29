"""Günlük çalıştırma: veriyi indir, bülteni kur, her maçı analiz et, JSON yaz.

Kullanım:  python src/run.py            (internetten indirir)
           python src/run.py --offline  (data/raw içindekiyle çalışır)
           python src/run.py --date 2026-10-30
"""
import argparse
import difflib
import json
import re
import sys
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import COUNTRY_TR, DAYS_AHEAD, LEAGUES, TIMEZONE, season_codes  # noqa: E402
from fetch import load_clubelo, load_fixtures, load_results  # noqa: E402
from report import Context, analyze  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "data"

# ClubElo adı -> football-data adı (farklı yazılanlar). Gerekirse çoğaltılabilir.
ALIASES = {
    "Bayern": "Bayern Munich", "Leverkusen": "Leverkusen", "Gladbach": "M'gladbach",
    "Frankfurt": "Ein Frankfurt", "Koeln": "FC Koln", "Mainz": "Mainz",
    "Atletico": "Ath Madrid", "Bilbao": "Ath Bilbao", "Celta": "Celta",
    "Sporting": "Sp Lisbon", "Braga": "Sp Braga", "Guimaraes": "Guimaraes",
    "PSV": "PSV Eindhoven", "AZ": "AZ Alkmaar", "Brugge": "Club Brugge",
    "PSG": "Paris SG", "Paris SG": "Paris SG", "Saint-Etienne": "St Etienne",
    "Forest": "Nott'm Forest", "Newcastle": "Newcastle", "Wolves": "Wolves",
    "Sheffield United": "Sheffield United", "Olympiakos": "Olympiakos",
    "Fenerbahce": "Fenerbahce", "Istanbul": "Buyuksehyr", "Basaksehir": "Buyuksehyr",
    "Goeztepe": "Goztep", "Goztepe": "Goztep", "Rizespor": "Rizespor",
}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(fc|cf|sc|ac|afc|sk|fk|as|ss|us|1\.)\b", " ", s)
    return re.sub(r"[^a-z0-9]", "", s)


def build_matcher(teams):
    by_norm = {norm(t): t for t in teams}

    def match(name):
        if name in teams:
            return name
        if name in ALIASES and ALIASES[name] in teams:
            return ALIASES[name]
        n = norm(name)
        if n in by_norm:
            return by_norm[n]
        for k, t in by_norm.items():  # "Man City" ~ "Manchester City" gibi
            if len(n) >= 4 and (k.startswith(n) or n.startswith(k)) and min(len(k), len(n)) >= 4:
                return t
        hit = difflib.get_close_matches(n, list(by_norm), n=1, cutoff=0.82)
        return by_norm[hit[0]] if hit else None

    return match


def uk_to_local(d, t, tz):
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
    elo = load_clubelo(offline=args.offline)
    if results.empty:
        print("HATA: maç verisi yok")
        sys.exit(1)

    print(f"[2/4] Modeller kuruluyor ({len(results)} maç)")
    ctx = Context(results, ref)
    match = build_matcher(set(ctx.team_league))

    print("[3/4] Bülten hazırlanıyor")
    bulletin = []
    seen = set()
    elo_idx = {}
    if not elo.empty:
        for r in elo.itertuples():
            h, a = match(r.Home), match(r.Away)
            if h and a:
                elo_idx[(h, a)] = (r.pH, r.pD, r.pA)

    for _, r in fixtures.iterrows():
        d, t = uk_to_local(r.Date, r.get("Time"), tz)
        if d not in days:
            continue
        h, a = r.HomeTeam, r.AwayTeam
        bulletin.append({
            "date": d.isoformat(), "time": t, "home": h, "away": a,
            "comp_type": "lig", "comp_name": LEAGUES[r.Div][0], "div": r.Div,
            "odds_row": r, "referee": r.get("Referee") if isinstance(r.get("Referee"), str) else None,
            "elo": elo_idx.get((h, a)),
        })
        seen.add((h, a))

    # Kupa ve Avrupa maçları (ClubElo fikstüründe olup lig fikstüründe olmayanlar)
    skipped = 0
    if not elo.empty:
        for r in elo.itertuples():
            d = r.Date.date()
            if d not in days:
                continue
            h, a = match(r.Home), match(r.Away)
            if (h, a) in seen:
                continue
            if not h and not a:
                continue  # takip ettiğimiz liglerden değil -> gereksiz
            lg_h, lg_a = ctx.team_league.get(h), ctx.team_league.get(a)
            if h and a and lg_h == lg_a:
                # Aynı ligden iki takım, lig fikstür dosyasında yok. Bu sezon bu
                # sahada zaten oynadılarsa kupa maçıdır, oynamadılarsa lig maçıdır.
                season_start = pd.Timestamp(today.year if today.month >= 7 else today.year - 1, 7, 1)
                played = results[(results.HomeTeam == h) & (results.AwayTeam == a) & (results.Date >= season_start)]
                if played.empty:
                    bulletin.append({
                        "date": d.isoformat(), "time": None, "home": h, "away": a,
                        "comp_type": "lig", "comp_name": LEAGUES[lg_h][0], "div": lg_h,
                        "odds_row": None, "referee": None, "elo": (r.pH, r.pD, r.pA),
                    })
                    seen.add((h, a))
                    continue
                ctype = "kupa"
            else:
                c_h = LEAGUES[lg_h][1] if lg_h else None
                c_a = LEAGUES[lg_a][1] if lg_a else None
                ctype = "avrupa" if (c_h and c_a and c_h != c_a) else "kupa"
                if not (h and a) and r.Country and (c_h or c_a) and r.Country not in (c_h, c_a):
                    ctype = "avrupa"
            country = LEAGUES[(lg_h or lg_a)][1]
            if ctype == "avrupa":
                name = "UEFA Avrupa Kupası"
            elif not (h and a):
                name = "Kupa / UEFA maçı"  # rakip takip edilen liglerde değil, turnuva kesin değil
            else:
                name = f"{COUNTRY_TR.get(country, country)} Kupası"
            bulletin.append({
                "date": d.isoformat(), "time": None,
                "home": h or r.Home, "away": a or r.Away,
                "comp_type": ctype, "comp_name": name, "div": None,
                "odds_row": None, "referee": None, "elo": (r.pH, r.pD, r.pA),
            })
            seen.add((h, a))

    print(f"[4/4] {len(bulletin)} maç analiz ediliyor")
    reports = []
    for fx in bulletin:
        try:
            rep = analyze(ctx, fx)
        except Exception as e:  # tek maç hatası tüm çalışmayı durdurmasın
            print(f"  ! {fx['home']} - {fx['away']}: {e}")
            rep = None
        if rep:
            reports.append(rep)
        else:
            skipped += 1

    reports.sort(key=lambda x: (x["tarih"], x["saat"] or "99:99", x["turnuva"]))
    diag = {
        "sonuc_satir": {c: int((results.Div == c).sum()) for c in LEAGUES},
        "fikstur_toplam": int(len(fixtures)),
        "fikstur_tarihler": sorted({str(x.date()) for x in fixtures.Date})[:10] if not fixtures.empty else [],
        "elo_toplam": int(len(elo)),
        "elo_gun_icinde": int(sum(1 for x in elo.Date if x.date() in days)) if not elo.empty else 0,
        "elo_eslesen": len(elo_idx),
    }
    out = {
        "kaynak": diag,
        "olusturma": datetime.now(tz).strftime("%d.%m.%Y %H:%M"),
        "gunler": sorted(d.isoformat() for d in days),
        "mac_sayisi": len(reports),
        "atlanan": skipped,
        "maclar": reports,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "archive").mkdir(exist_ok=True)
    payload = json.dumps(out, ensure_ascii=False, default=float)
    (OUT / "latest.json").write_text(payload, encoding="utf-8")
    (OUT / "archive" / f"{today.isoformat()}.json").write_text(payload, encoding="utf-8")
    print(f"Tamam: {len(reports)} rapor, {skipped} maç veri yetersiz olduğu için atlandı.")


if __name__ == "__main__":
    main()
