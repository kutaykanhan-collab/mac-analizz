"""Canlı modeli test etmek için geçmiş maç verisi toplar (FotMob, biten maçlar).

Her maç için dakika dakika şutlar (xG), goller, kırmızı kartlar ve baskı (momentum)
kısa bir kayıt olarak data/live/maclar.jsonl dosyasına eklenir.
python src/live_collect.py [--days 42] [--max 900]
"""
import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import FOTMOB_LEAGUES  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "live" / "maclar.jsonl"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
      "Accept": "application/json"}


def get_json(url):
    for i in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=25)
            if r.ok and r.text[:1] == "{":
                return r.json()
        except requests.RequestException:
            pass
        time.sleep(2 * (i + 1))
    return None


def compact(j, meta):
    c = j.get("content", {})
    home_id = (j.get("general", {}).get("homeTeam") or {}).get("id")
    shots = []
    for s in (c.get("shotmap") or {}).get("shots", []) or []:
        shots.append([s.get("min"), s.get("minAdded") or 0, 1 if s.get("teamId") == home_id else 0,
                      round(s.get("expectedGoals") or 0, 4), 1 if s.get("eventType") == "Goal" else 0,
                      1 if s.get("isOnTarget") else 0, s.get("period")])
    goals, reds = [], []
    for e in ((c.get("matchFacts") or {}).get("events") or {}).get("events", []) or []:
        t = e.get("type")
        if t == "Goal":
            goals.append([e.get("time"), e.get("overloadTime") or 0, 1 if e.get("isHome") else 0])
        elif t == "Card" and e.get("card") in ("Red", "YellowRed"):
            reds.append([e.get("time"), e.get("overloadTime") or 0, 1 if e.get("isHome") else 0])
    mom = [[d.get("minute"), d.get("value")] for d in ((c.get("momentum") or {}).get("main") or {}).get("data", []) or []]
    teams = (j.get("header") or {}).get("teams") or [{}, {}]
    return {**meta, "hg": teams[0].get("score"), "ag": teams[1].get("score"),
            "shots": shots, "goals": goals, "reds": reds, "momentum": mom}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=42)
    ap.add_argument("--max", type=int, default=900)
    args = ap.parse_args()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if OUT.exists():
        for line in OUT.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(line)["id"])
            except Exception:
                pass

    todo = []
    for k in range(1, args.days + 1):
        d = date.today() - timedelta(days=k)
        j = get_json(f"https://www.fotmob.com/api/data/matches?date={d.strftime('%Y%m%d')}")
        if not j:
            continue
        for lg in j.get("leagues", []):
            code = FOTMOB_LEAGUES.get(lg.get("primaryId"))
            if not code:
                continue
            for m in lg.get("matches", []):
                st = m.get("status", {})
                if st.get("finished") and not st.get("cancelled") and m["id"] not in done:
                    todo.append({"id": m["id"], "tarih": d.isoformat(), "lig": code, "lig_ad": lg.get("name"),
                                 "ev": m["home"]["name"], "dep": m["away"]["name"]})
        time.sleep(0.3)
    print(f"{len(todo)} yeni maç bulundu, en fazla {args.max} tanesi indirilecek")
    n = 0
    with OUT.open("a", encoding="utf-8") as f:
        for meta in todo[: args.max]:
            j = get_json(f"https://www.fotmob.com/api/data/matchDetails?matchId={meta['id']}")
            if j:
                f.write(json.dumps(compact(j, meta), ensure_ascii=False) + "\n")
                n += 1
            time.sleep(0.4)
    print(f"{n} maç eklendi, toplam {len(done) + n}")


if __name__ == "__main__":
    main()
