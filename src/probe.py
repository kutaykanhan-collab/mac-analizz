"""Geçici: hangi kupa kaynakları GitHub sunucusundan çalışıyor?"""
import json
from datetime import date
from pathlib import Path
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
      "Accept": "application/json, text/plain, */*"}
d = date.today()
ymd = d.strftime("%Y%m%d")
out = {"tarih": str(d), "espn": {}, "diger": {}}
codes = ["tur.cup", "tur.turkish_cup", "tur.1", "tur.2", "eng.league_cup", "eng.fa", "esp.copa_del_rey",
         "ger.dfb_pokal", "ita.coppa_italia", "fra.coupe_de_france", "ned.cup", "ned.knvb_beker",
         "por.taca.portugal", "por.league_cup", "por.taca_da_liga", "bel.cup", "gre.cup", "sco.league_cup",
         "sco.tennents", "sco.cis", "uefa.champions", "uefa.europa", "uefa.europa.conf", "all"]
for c in codes:
    try:
        r = requests.get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{c}/scoreboard?dates={ymd}", headers=UA, timeout=20)
        j = r.json() if r.ok else {}
        ev = j.get("events", [])
        lg = (j.get("leagues") or [{}])[0].get("name")
        out["espn"][c] = {"durum": r.status_code, "lig": lg, "mac": len(ev),
                          "ornek": [e.get("name") for e in ev[:4]]}
    except Exception as e:
        out["espn"][c] = {"hata": str(e)[:120]}
others = {
    "sofascore": f"https://api.sofascore.com/api/v1/sport/football/scheduled-events/{d.isoformat()}",
    "sofascore_www": f"https://www.sofascore.com/api/v1/sport/football/scheduled-events/{d.isoformat()}",
    "fotmob": f"https://www.fotmob.com/api/data/matches?date={ymd}",
    "fotmob_eski": f"https://www.fotmob.com/api/matches?date={ymd}",
    "mackolik_livedata": f"https://vd.mackolik.com/livedata?date={d.strftime('%d/%m/%Y')}",
    "mackolik_iddaa": "https://www.mackolik.com/iddaa-programi",
    "tff": "https://www.tff.org/Default.aspx?pageID=1001",
}
for k, u in others.items():
    try:
        r = requests.get(u, headers=UA, timeout=20)
        t = r.text
        info = {"durum": r.status_code, "boyut": len(t), "bas": t[:200]}
        if "sofascore" in k and r.ok:
            ev = r.json().get("events", [])
            tr = [e for e in ev if (e.get("tournament", {}).get("category", {}).get("name") == "Turkey")]
            info.update({"mac": len(ev), "turkiye": [(e["tournament"]["name"], e["homeTeam"]["name"], e["awayTeam"]["name"]) for e in tr[:8]]})
        if "fotmob" in k and r.ok:
            j = r.json()
            ls = j.get("leagues", [])
            info.update({"lig": len(ls), "ornek": [l.get("name") for l in ls[:30]]})
        if "mackolik" in k:
            info["kupa_gecer"] = ("Kupa" in t) or ("Ziraat" in t)
        out["diger"][k] = info
        if k in ("mackolik_livedata", "fotmob") and r.ok:
            Path("data/raw").mkdir(parents=True, exist_ok=True)
            Path(f"data/raw/probe_{k}.json").write_text(t, encoding="utf-8")
    except Exception as e:
        out["diger"][k] = {"hata": str(e)[:150]}
Path("docs/data").mkdir(parents=True, exist_ok=True)
Path("docs/data/probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False)[:3000])
