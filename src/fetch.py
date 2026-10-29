"""Ham veriyi indirir: lig maç sonuçları, günün fikstürü, ClubElo fikstürü (kupalar için)."""
import io
import time
from pathlib import Path

import pandas as pd
import requests

from config import BASE_URL, CLUBELO_RATINGS_URL, FIXTURES_URL, LEAGUES, UEFA_FEED_URLS, UEFA_FEEDS

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
HEADERS = {"User-Agent": "mac-analiz/1.0 (kisisel istatistik projesi)"}


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
