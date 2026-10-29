"""Geçici: canlı istatistik kaynakları testi."""
import json
from datetime import date
from pathlib import Path
import requests
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
      "Accept": "application/json, text/plain, */*", "Origin": "https://example.github.io"}
out = {}
def get(u):
    r = requests.get(u, headers=UA, timeout=20)
    return r, {"durum": r.status_code, "boyut": len(r.text), "cors": r.headers.get("Access-Control-Allow-Origin"),
               "bas": r.text[:150]}
ymd = date.today().strftime("%Y%m%d")
r, info = get(f"https://www.fotmob.com/api/data/matches?date={ymd}")
out["fotmob_matches"] = info
ids = []
if r.ok:
    for lg in r.json().get("leagues", []):
        for m in lg.get("matches", []):
            st = m.get("status", {})
            if st.get("started"):
                ids.append((m["id"], lg.get("name"), m["home"]["name"], m["away"]["name"], st.get("finished"), st.get("liveTime", {}).get("short")))
out["fotmob_baslamis"] = ids[:15]
for mid in [i[0] for i in ids[:2]]:
    for path in ("api/data/matchDetails", "api/matchDetails"):
        try:
            r2, info2 = get(f"https://www.fotmob.com/{path}?matchId={mid}")
            if r2.ok and r2.text.startswith("{"):
                j = r2.json()
                c = j.get("content", {})
                st = c.get("stats") or {}
                titles = []
                for per in (st.get("Periods", {}) or {}).get("All", {}).get("stats", []) or []:
                    for s in per.get("stats", []):
                        titles.append((s.get("title"), s.get("stats")))
                info2.update({"content_keys": list(c.keys()), "stat_titles": titles[:40],
                              "momentum": str(c.get("momentum"))[:300]})
                Path("data/raw").mkdir(parents=True, exist_ok=True)
                Path(f"data/raw/probe_fotmob_detail_{mid}.json").write_text(r2.text, encoding="utf-8")
            out[f"{path}_{mid}"] = info2
        except Exception as e:
            out[f"{path}_{mid}"] = {"hata": str(e)[:150]}
for k, u in {
    "mackolik_livedata": f"https://vd.mackolik.com/livedata?date={date.today().strftime('%d/%m/%Y')}",
    "mackolik_arsiv_mac": "https://arsiv.mackolik.com/Match/Default.aspx?id=4574248",
    "mackolik_arsiv_data": "https://arsiv.mackolik.com/Match/MatchData.aspx?t=dtl&id=4574248&s=0",
    "mackolik_stats": "https://arsiv.mackolik.com/AjaxHandlers/MatchHandler.aspx?command=optaStats&id=4574248",
}.items():
    try:
        r3, info3 = get(u)
        info3["tehlikeli_atak"] = ("Tehlikeli" in r3.text) or ("dangerous" in r3.text.lower())
        out[k] = info3
    except Exception as e:
        out[k] = {"hata": str(e)[:150]}
Path("docs/data").mkdir(parents=True, exist_ok=True)
Path("docs/data/probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
