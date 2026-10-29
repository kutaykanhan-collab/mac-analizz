"""Ham veriyi indirir: lig maç sonuçları, günün fikstürü, ClubElo fikstürü (kupalar için)."""
import io
import re
import time
from pathlib import Path

import pandas as pd
import requests

from config import BASE_URL, CLUBELO_FIXTURES_URL, FIXTURES_URL, LEAGUES

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


def load_clubelo(offline=False):
    """ClubElo fikstürü. Kupa ve Avrupa maçlarını bulmak + Elo olasılığı için.
    Dönen tablo: Date, Country, Home, Away, pH, pD, pA"""
    path = RAW / "clubelo_fixtures.csv"
    if not offline:
        raw = _get(CLUBELO_FIXTURES_URL)
        if raw:
            path.write_bytes(raw)
    if not path.exists():
        return pd.DataFrame()
    df = _read_csv(path.read_bytes())
    need = {"Date", "Home", "Away"}
    if df.empty or not need.issubset(df.columns):
        return pd.DataFrame()

    # Gol farkı sütunlarından 1-X-2 olasılığı çıkar (GD<-5, GD=-1, GD=0, GD>5 ...)
    pos, neg, zero = [], [], []
    for c in df.columns:
        m = re.match(r"GD([<>=])(-?\d+)", c)
        if not m:
            continue
        op, v = m.group(1), int(m.group(2))
        if op == ">" or (op == "=" and v > 0):
            pos.append(c)
        elif op == "<" or (op == "=" and v < 0):
            neg.append(c)
        else:
            zero.append(c)
    if pos and neg and zero:
        df["pH"] = df[pos].sum(axis=1)
        df["pD"] = df[zero].sum(axis=1)
        df["pA"] = df[neg].sum(axis=1)
    else:
        df["pH"] = df["pD"] = df["pA"] = float("nan")
    if "Country" not in df.columns:
        df["Country"] = ""
    df = df[["Date", "Country", "Home", "Away", "pH", "pD", "pA"]]
    return _parse_dates(df)
