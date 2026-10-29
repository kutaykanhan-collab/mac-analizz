"""Ham veriyi indirir: lig maç sonuçları, günün fikstürü, ClubElo fikstürü (kupalar için)."""
import io
import time
from pathlib import Path

import pandas as pd
import requests

from config import BASE_URL, CLUBELO_RATINGS_URL, FIXTURES_URL, LEAGUES, MACKOLIK_URL, UEFA_FEED_URLS, UEFA_FEEDS

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
           "Accept": "application/json, text/plain, */*"}


def _get(url, tries=3):
    for i in range(tries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200 and r.content:
                return r.content
            if r.status_code == 404:
                return None
        except requests.RequestException:
            pass
        time.sleep(2 * (i + 1))
    return None


def _read_csv(raw: bytes):
    for enc in ("utf-8-sig", "latin-1"):
        try:
            df = pd.read_csv(io.BytesIO(raw), encoding=enc, on_bad_lines="skip")
            df.columns = [str(c).strip() for c in df.columns]
            return df
        except Exception:
            continue
    return pd.DataFrame()


def _parse_dates(df, col="Date"):
    df[col] = pd.to_datetime(df[col], dayfirst=True, errors="coerce", format="mixed")
    return df.dropna(subset=[col])


def load_results(seasons, offline=False):
    """Tüm liglerin bu ve geçen sezon maçları tek tabloda."""
    RAW.mkdir(parents=True, exist_ok=True)
    frames = []
    for code in LEAGUES:
        for s in seasons:
            path = RAW / f"{code}_{s}.csv"
            if not offline:
                raw = _get(BASE_URL.format(season=s, code=code))
                if raw:
                    path.write_bytes(raw)
            if not path.exists():
                continue
            df = _read_csv(path.read_bytes())
            if df.empty or "HomeTeam" not in df.columns:
                continue
            df = df.dropna(subset=["HomeTeam", "AwayTeam", "FTHG", "FTAG"])
            df["Div"] = code
            frames.append(_parse_dates(df))
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    return out.sort_values("Date").reset_index(drop=True)


def load_fixtures(offline=False):
    """football-data günlük fikstür dosyası (oranlar dahil)."""
    path = RAW / "fixtures.csv"
    if not offline:
        raw = _get(FIXTURES_URL)
        if raw:
            path.write_bytes(raw)
    if not path.exists():
        return pd.DataFrame()
    df = _read_csv(path.read_bytes())
    if df.empty or "HomeTeam" not in df.columns:
        return pd.DataFrame()
    df = df[df["Div"].isin(LEAGUES.keys())].copy()
    return _parse_dates(df)


def load_uefa(today, offline=False):
    """UEFA kupa fikstürleri (fixturedownload.com). Dönen tablo:
    Date (UTC zaman damgası), Comp, Home, Away, Round"""
    import json
    y0 = today.year if today.month >= 7 else today.year - 1
    rows = []
    for (comp, slug_t), y in [(c, yy) for yy in (y0, y0 - 1) for c in UEFA_FEEDS.items()]:
        slug = slug_t.format(y=y)
        path = RAW / f"uefa_{slug}.json"
        if not offline:
            for u in UEFA_FEED_URLS:
                raw = _get(u.format(slug=slug))
                if raw and raw.lstrip()[:1] in (b"[", b"{"):
                    path.write_bytes(raw)
                    break
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_bytes().decode("utf-8-sig"))
        except Exception:
            continue
        if isinstance(data, dict):
            data = data.get("matches") or data.get("Matches") or []
        for m in data:
            d = m.get("DateUtc") or m.get("Date")
            h, a = m.get("HomeTeam"), m.get("AwayTeam")
            if not (d and h and a) or "To be" in str(h) or "TBD" in str(h):
                continue
            rows.append({"Date": d, "Comp": comp, "Home": h, "Away": a,
                         "Round": m.get("RoundNumber"), "Group": m.get("Group"),
                         "HG": m.get("HomeTeamScore"), "AG": m.get("AwayTeamScore")})
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["Date"], utc=True, errors="coerce")
    return df.dropna(subset=["Date"])


def load_elo_ratings(today, offline=False):
    """ClubElo güç puanları {kulüp: elo}. Alınamazsa boş sözlük."""
    path = RAW / "clubelo_ratings.csv"
    if not offline:
        raw = _get(CLUBELO_RATINGS_URL.format(date=today.isoformat()))
        if raw and raw[:4] in (b"Rank", b"\xef\xbb\xbfR"):
            path.write_bytes(raw)
    if not path.exists():
        return {}
    df = _read_csv(path.read_bytes())
    if not {"Club", "Elo"}.issubset(df.columns):
        return {}
    return dict(zip(df.Club, pd.to_numeric(df.Elo, errors="coerce")))


# Maçkolik ülke adı -> izlenen ülke kodu
MACKOLIK_COUNTRIES = {
    "Türkiye": "TUR", "İngiltere": "ENG", "İspanya": "ESP", "İtalya": "ITA", "Almanya": "GER",
    "Fransa": "FRA", "Hollanda": "NED", "Portekiz": "POR", "Belçika": "BEL", "Yunanistan": "GRE",
    "İskoçya": "SCO",
}
UEFA_WORDS = ("Şampiyonlar Ligi", "Avrupa Ligi", "Konferans Ligi")
SKIP_WORDS = ("Kadın", "U17", "U19", "U20", "U21", "U23", "Gençler", "Genç", "Rezerv", "Reserve", "Hazırlık",
              "Mladinska", "Primavera", "Premier Lig Kupası", "Bölgesel", "Amatör")


def _reserve_team(name):
    n = f" {name} "
    return any(t in n for t in (" U17 ", " U18 ", " U19 ", " U20 ", " U21 ", " U23 ", " II ", " B ", "(K)")) \
        or name.startswith("Jong ")


def _f(x):
    try:
        v = float(x)
        return v if v > 1.0 else None
    except (TypeError, ValueError):
        return None


def _odds3(h, d, a):
    """iddaa 1-X-2. Eksik ya da tutarsızsa (aşırı favori maçlarda olur) boş döner."""
    o = [_f(h), _f(d), _f(a)]
    # Aşırı favori maçlarda iddaa favorinin oranını vermez (ör. 17.35 / 12.45 / -).
    # Diğer iki oran yüksekse eksik oran 1.01 kabul edilir: favori ~%85-90.
    if o.count(None) == 1 and all(x >= 5 for x in o if x):
        o = [x or 1.01 for x in o]
    if None in o or not (1.0 < sum(1 / x for x in o) < 1.4):
        return {}
    return {"IddaaH": o[0], "IddaaD": o[1], "IddaaA": o[2]}


def load_mackolik(days, offline=False):
    """Maçkolik bülteni (iddaa 1-X-2 oranlarıyla). Sadece futbol ve izlenen ülkeler + UEFA.
    Dönen liste: dict(id, date, time, home, away, country, league, cup, code, odds)"""
    import json
    out, seen = [], set()
    for d in sorted(days):
        path = RAW / f"mackolik_{d.isoformat()}.json"
        if not offline:
            raw = _get(MACKOLIK_URL.format(date=d.strftime("%d/%m/%Y")))
            if raw and raw.lstrip()[:1] == b"{":
                path.write_bytes(raw)
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_bytes().decode("utf-8"))
        except Exception:
            continue
        for m in data.get("m", []):
            try:
                if m[0] in seen or len(m) < 37 or m[23] != 1:  # 23: spor (1 = futbol)
                    continue
                info = m[36]
                country, league, cup = info[1], info[3], info[7]
                full = f"{country} {league}"
                if any(w in full for w in SKIP_WORDS) or _reserve_team(str(m[2])) or _reserve_team(str(m[4])):
                    continue
                is_uefa = (country.startswith("UEFA") or country.startswith("Avrupa")) and \
                    any(w in full for w in UEFA_WORDS)
                if country not in MACKOLIK_COUNTRIES and not is_uefa:
                    continue
                dd = pd.to_datetime(m[35], dayfirst=True, errors="coerce")
                if pd.isna(dd):
                    continue
                seen.add(m[0])
                out.append({
                    "id": m[0], "date": dd.date(), "time": m[16] or None,
                    "home": m[2], "away": m[4], "status": m[5],
                    "country": country, "league": league, "cup": int(cup or 0), "uefa": is_uefa,
                    "code": MACKOLIK_COUNTRIES.get(country),
                    "odds": _odds3(m[18], m[19], m[20]),
                })
            except (IndexError, TypeError):
                continue
    return out
