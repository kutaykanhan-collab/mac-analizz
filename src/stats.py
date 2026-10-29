"""Son N maç form istatistikleri (genel + ev/deplasman ayrımı)."""
import numpy as np
import pandas as pd


def _team_rows(df, team):
    """Takımın maçlarını 'takım bakış açısıyla' tek tabloya çevirir."""
    h = df[df.HomeTeam == team]
    a = df[df.AwayTeam == team]

    def pick(d, us, them, venue):
        g = lambda c: d[c] if c in d.columns else np.nan
        return pd.DataFrame({
            "Date": d.Date, "venue": venue,
            "opp": d["AwayTeam" if venue == "E" else "HomeTeam"],
            "gf": d[f"FT{us}G"], "ga": d[f"FT{them}G"],
            "htgf": g(f"HT{us}G"), "htga": g(f"HT{them}G"),
            "sf": g(f"{us}S"), "sa": g(f"{them}S"),
            "stf": g(f"{us}ST"), "sta": g(f"{them}ST"),
            "cf": g(f"{us}C"), "ca": g(f"{them}C"),
            "yf": g(f"{us}Y"), "ya": g(f"{them}Y"),
            "rf": g(f"{us}R"), "ra": g(f"{them}R"),
        })

    rows = pd.concat([pick(h, "H", "A", "E"), pick(a, "A", "H", "D")])
    return rows.sort_values("Date", ascending=False)


def _r(x, nd=2):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), nd)


def summarize(rows):
    n = len(rows)
    if n == 0:
        return None
    w = int((rows.gf > rows.ga).sum())
    d = int((rows.gf == rows.ga).sum())
    l = n - w - d
    tot = rows.gf + rows.ga
    res = []
    for gf, ga in zip(rows.gf, rows.ga):
        res.append("G" if gf > ga else ("B" if gf == ga else "M"))
    m = lambda c: _r(rows[c].mean()) if rows[c].notna().any() else None
    cards = rows.yf.fillna(0) + rows.rf.fillna(0)
    cards_opp = rows.ya.fillna(0) + rows.ra.fillna(0)
    return {
        "n": n, "G": w, "B": d, "M": l,
        "seri": "".join(res[:10]),
        "puan_ort": _r((3 * w + d) / n),
        "atilan": m("gf"), "yenilen": m("ga"),
        "iy_atilan": m("htgf"), "iy_yenilen": m("htga"),
        "kg_var_yuzde": round(100 * float(((rows.gf > 0) & (rows.ga > 0)).mean())),
        "ust25_yuzde": round(100 * float((tot > 2.5).mean())),
        "ust15_yuzde": round(100 * float((tot > 1.5).mean())),
        "iy_gol_yuzde": round(100 * float(((rows.htgf + rows.htga) > 0).mean())) if rows.htgf.notna().any() else None,
        "korner": m("cf"), "korner_yenilen": m("ca"),
        "sut": m("sf"), "sut_yenilen": m("sa"),
        "isabetli_sut": m("stf"), "isabetli_yenilen": m("sta"),
        "kart": _r(cards.mean()) if rows.yf.notna().any() else None,
        "kart_mac_toplam": _r((cards + cards_opp).mean()) if rows.yf.notna().any() else None,
        "son_maclar": [
            {"tarih": dt.strftime("%d.%m"), "yer": v, "rakip": o, "skor": f"{int(a)}-{int(b)}"}
            for dt, v, o, a, b in zip(rows.Date[:5], rows.venue[:5], rows.opp[:5], rows.gf[:5], rows.ga[:5])
        ],
    }


def team_form(df, team, before, n=15):
    rows = _team_rows(df[df.Date < before], team)
    if rows.empty:
        return None
    return {
        "genel": summarize(rows.head(n)),
        "ev": summarize(rows[rows.venue == "E"].head(n)),
        "deplasman": summarize(rows[rows.venue == "D"].head(n)),
    }
