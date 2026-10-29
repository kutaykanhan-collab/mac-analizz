"""Bir maç için tam analiz raporu (JSON) üretir."""
import math

import numpy as np
import pandas as pd

from config import COUNTRY_TR, DERBIES, DERBY_CARD_FACTOR, FORM_N, LEAGUES, VALUE_EDGE
from model import CountModel, GoalModel, goal_markets, lambdas_from_probs, score_matrix
from stats import team_form


# --------------------------------------------------------------------------
# Lig modellerini bir kez kur
# --------------------------------------------------------------------------
class Context:
    def __init__(self, results, ref_date):
        self.results = results
        self.ref_date = ref_date
        r = results.copy()
        for side in ("H", "A"):
            if f"{side}Y" in r.columns:
                r[f"{side}K"] = r[f"{side}Y"].fillna(0) + 2 * r.get(f"{side}R", 0).fillna(0) \
                    if f"{side}R" in r.columns else r[f"{side}Y"]
        # Not: kırmızı kart iddaa'daki gibi 2 kart sayılır (sarı=1, kırmızı=2)
        self.goal, self.corner, self.shot, self.sot, self.card = {}, {}, {}, {}, {}
        self.team_league = {}
        cur_season_start = pd.Timestamp(ref_date.year if ref_date.month >= 7 else ref_date.year - 1, 7, 1)
        for code in LEAGUES:
            d = r[r.Div == code]
            if len(d) < 40:
                continue
            self.goal[code] = GoalModel(d, ref_date)
            self.corner[code] = CountModel(d, "HC", "AC", ref_date)
            self.shot[code] = CountModel(d, "HS", "AS", ref_date)
            self.sot[code] = CountModel(d, "HST", "AST", ref_date)
            self.card[code] = CountModel(d, "HK", "AK", ref_date, ref_col="Referee")
            # Takımın güncel ligi = bu sezon oynadığı lig
            cur = d[d.Date >= cur_season_start]
            for t in set(cur.HomeTeam) | set(cur.AwayTeam):
                self.team_league[t] = code
        # Bu sezon maçı olmayan takımlar için son görüldüğü lig
        for code in LEAGUES:
            d = r[r.Div == code]
            for t in set(d.HomeTeam) | set(d.AwayTeam):
                self.team_league.setdefault(t, code)
        self.tables = {code: league_table(r[(r.Div == code) & (r.Date >= cur_season_start)]) for code in LEAGUES}


def league_table(d):
    pts = {}
    for h, a, hg, ag in zip(d.HomeTeam, d.AwayTeam, d.FTHG, d.FTAG):
        for t in (h, a):
            pts.setdefault(t, [0, 0, 0])  # puan, averaj, maç
        pts[h][2] += 1
        pts[a][2] += 1
        pts[h][1] += hg - ag
        pts[a][1] += ag - hg
        if hg > ag:
            pts[h][0] += 3
        elif hg < ag:
            pts[a][0] += 3
        else:
            pts[h][0] += 1
            pts[a][0] += 1
    order = sorted(pts.items(), key=lambda kv: (-kv[1][0], -kv[1][1]))
    return {t: {"sira": i + 1, "puan": int(v[0]), "averaj": int(v[1]), "mac": v[2], "takim_sayisi": len(order)}
            for i, (t, v) in enumerate(order)}


# --------------------------------------------------------------------------
# Yardımcılar
# --------------------------------------------------------------------------
def pct(p):
    return round(100 * p, 1)


def fair(p):
    return round(1 / p, 2) if p > 0.001 else None


def risk_of(p, odds=None):
    if odds and odds >= 2.6:
        return "Yüksek"
    if p >= 0.72:
        return "Düşük"
    if p >= 0.58:
        return "Orta"
    return "Yüksek"


def get_odds(row, keys):
    if row is None:
        return None
    for k in keys:
        if k in row and pd.notna(row[k]):
            try:
                v = float(row[k])
                if v > 1.0:
                    return v
            except (TypeError, ValueError):
                pass
    return None


def derby_info(home, away):
    for pair, why in DERBIES:
        if {home, away} == pair:
            return True, why
    return False, None


# --------------------------------------------------------------------------
# Ana analiz
# --------------------------------------------------------------------------
def analyze(ctx: Context, fx: dict):
    """fx: home, away, kickoff (str), comp_type ('lig'|'kupa'|'avrupa'),
    comp_name, div (lig maçıysa), odds_row (Series|None), referee, elo (pH,pD,pA)|None"""
    home, away = fx["home"], fx["away"]
    lg_h, lg_a = ctx.team_league.get(home), ctx.team_league.get(away)
    notes = []

    # ---- Gol beklentisi -------------------------------------------------
    method = None
    if lg_h and lg_h == lg_a and lg_h in ctx.goal:
        gm = ctx.goal[lg_h]
        lh, la = gm.lambdas(home, away)
        rho, ht_h, ht_a = gm.rho, gm.ht_h, gm.ht_a
        method = "Lig gol modeli (Dixon-Coles Poisson)"
    elif fx.get("elo") and not any(math.isnan(x) for x in fx["elo"]):
        tot = []
        for t, lg in ((home, lg_h), (away, lg_a)):
            if lg and lg in ctx.goal:
                g = ctx.goal[lg]
                hh = g.home / 2
                tot.append(math.exp(g.mu + hh + g.att.get(t, 0)) + math.exp(g.mu + hh - g.de.get(t, 0)))
        if not tot:
            return None
        total = float(np.mean(tot))
        if len(tot) == 1:
            notes.append("Rakip takımın lig verisi yok; toplam gol tek takımın profiline ve Elo gücüne göre hesaplandı.")
        pH, pD, pA = fx["elo"]
        lh, la = lambdas_from_probs(pH, pA, total)
        rho = -0.05
        g0 = ctx.goal.get(lg_h) or ctx.goal.get(lg_a)
        ht_h, ht_a = g0.ht_h, g0.ht_a
        method = "Elo gücü + takımların gol profili (ligler arası maç)"
    else:
        return None

    m = score_matrix(lh, la, rho)
    mk = goal_markets(m)
    mh = score_matrix(lh * ht_h, la * ht_a, 0.0)
    ht = goal_markets(mh)

    # ---- Form -----------------------------------------------------------
    f_h = team_form(ctx.results, home, ctx.ref_date, FORM_N)
    f_a = team_form(ctx.results, away, ctx.ref_date, FORM_N)
    if fx["comp_type"] != "lig":
        notes.append("Form verisi yalnızca lig maçlarını kapsar (kupa maçları kaynakta yok).")

    # ---- Derbi ----------------------------------------------------------
    is_derby, derby_why = derby_info(home, away)

    # ---- Korner / şut / kart -------------------------------------------
    def counts(models, factor=1.0):
        cm_h = models.get(lg_h)
        cm_a = models.get(lg_a)
        cm_h = cm_h if cm_h is not None and cm_h.ok else None
        cm_a = cm_a if cm_a is not None and cm_a.ok else None
        if cm_h is None and cm_a is None:
            return None, None
        base = cm_h or cm_a
        f_home = cm_h.f.get(home, 1) if cm_h else 1.0
        a_home = cm_h.a.get(home, 1) if cm_h else 1.0
        f_away = cm_a.f.get(away, 1) if cm_a else 1.0
        a_away = cm_a.a.get(away, 1) if cm_a else 1.0
        eh = base.lh * f_home * a_away * factor
        ea = (cm_a or base).la * f_away * a_home * factor
        return base, (eh, ea)

    def line_block(cm, eh, ea, step):
        tot = eh + ea
        center = math.floor(tot) + 0.5
        lines = [center + step * k for k in (-2, -1, 0, 1, 2) if center + step * k > 0]
        lo, hi = cm.interval(tot)
        rows = [{"cizgi": ln, "ust": pct(cm.p_over(tot, ln)), "alt": pct(1 - cm.p_over(tot, ln))} for ln in lines]
        return {"ev": round(eh, 1), "dep": round(ea, 1), "toplam": round(tot, 1),
                "aralik": f"{lo}-{hi}", "cizgiler": rows}

    cmc, ec = counts(ctx.corner)
    corner = line_block(cmc, *ec, 1) if cmc else None

    cms, es = counts(ctx.shot)
    shots = line_block(cms, *es, 2) if cms else None
    cmt, et = counts(ctx.sot)
    sot = line_block(cmt, *et, 1) if cmt else None

    # Kart: hakem + derbi + kupa katsayısı
    ref_name = (fx.get("referee") or "").strip() or None
    ref_info = None
    kfac = 1.0
    cm_card = ctx.card.get(lg_h) if lg_h else None
    if ref_name and cm_card is not None and cm_card.ok and ref_name in cm_card.ref:
        rr = cm_card.ref[ref_name]
        kfac *= rr["factor"]
        ref_info = {"ad": ref_name, "mac": rr["n"], "kart_ort": round(rr["avg"], 2) if rr["avg"] else None,
                    "katsayi": round(rr["factor"], 2),
                    "egilim": "Kart eğilimi yüksek" if rr["factor"] > 1.08 else
                              ("Kartta cimri" if rr["factor"] < 0.92 else "Lig ortalamasında")}
    elif ref_name:
        ref_info = {"ad": ref_name, "mac": 0, "kart_ort": None, "katsayi": 1.0,
                    "egilim": "Hakemin bu kaynakta yeterli maçı yok"}
    else:
        notes.append("Hakem bilgisi bu maç için kaynakta yok; kart beklentisi takım ve lig verisine dayanıyor.")
    if is_derby:
        kfac *= DERBY_CARD_FACTOR
    if fx["comp_type"] != "lig":
        kfac *= 1.05
    cmk, ek = counts(ctx.card, kfac)
    cards = line_block(cmk, *ek, 1) if cmk else None
    if cards:
        cards["hakem"] = ref_info
        cards["not"] = "Sarı = 1, kırmızı = 2 kart sayılır."

    notes.append("Oyuncu bazlı veri (sakatlık, ceza, bireysel şut) ücretsiz kaynakta yok; analiz takım düzeyindedir.")

    # ---- Oranlar ve değer ----------------------------------------------
    row = fx.get("odds_row")
    odds = {
        "1": get_odds(row, ["AvgH", "B365H", "PSH", "MaxH"]),
        "X": get_odds(row, ["AvgD", "B365D", "PSD", "MaxD"]),
        "2": get_odds(row, ["AvgA", "B365A", "PSA", "MaxA"]),
        "2.5 Üst": get_odds(row, ["Avg>2.5", "B365>2.5", "P>2.5", "Max>2.5"]),
        "2.5 Alt": get_odds(row, ["Avg<2.5", "B365<2.5", "P<2.5", "Max<2.5"]),
    }
    odds_eval = []
    implied = {}
    for group in (("1", "X", "2"), ("2.5 Üst", "2.5 Alt")):
        if all(odds[k] for k in group):
            s = sum(1 / odds[k] for k in group)
            for k in group:
                implied[k] = (1 / odds[k]) / s
            for k in group:
                p = mk[k]
                edge = p * odds[k] - 1
                odds_eval.append({
                    "pazar": "MS " + k if k in ("1", "X", "2") else k,
                    "oran": odds[k], "piyasa": pct(implied[k]), "model": pct(p),
                    "fark": round(100 * (p - implied[k]), 1), "deger": round(100 * edge, 1),
                    "durum": "Değerli" if edge >= VALUE_EDGE else ("Adil" if edge > -0.04 else "Değersiz"),
                })
            marj = round(100 * (s - 1), 1)
            odds_eval.append({"pazar": f"Kâr marjı ({'/'.join(group)})", "marj": marj})
    if not implied:
        notes.append("Bu maç için oran verisi yok; sadece model olasılığı ve adil oran gösteriliyor.")

    # ---- Öneriler -------------------------------------------------------
    rec = {}
    ms_pick = max(("1", "X", "2"), key=lambda k: mk[k])
    if mk[ms_pick] < 0.5:
        dc = max(("1X", "X2", "12"), key=lambda k: mk[k])
        rec["mac_sonucu"] = {"secim": f"Çifte Şans {dc}", "olasilik": pct(mk[dc]), "adil_oran": fair(mk[dc]),
                             "aciklama": f"Net favori yok (en yüksek MS {ms_pick} %{pct(mk[ms_pick])}). Çifte şans daha güvenli.",
                             "risk": risk_of(mk[dc])}
    else:
        rec["mac_sonucu"] = {"secim": f"MS {ms_pick}", "olasilik": pct(mk[ms_pick]), "adil_oran": fair(mk[ms_pick]),
                             "aciklama": "Model favorisi.", "risk": risk_of(mk[ms_pick])}

    ht_pick = max(("1", "X", "2"), key=lambda k: ht[k])
    iy05 = ht["0.5 Üst"]
    rec["ilk_yari"] = {
        "sonuc": {"secim": f"İY {ht_pick}", "olasilik": pct(ht[ht_pick])},
        "gol": {"secim": "İY 0.5 Üst" if iy05 >= 0.5 else "İY 0.5 Alt",
                "olasilik": pct(max(iy05, 1 - iy05)), "adil_oran": fair(max(iy05, 1 - iy05)),
                "risk": risk_of(max(iy05, 1 - iy05))},
        "iy_15_ust": pct(ht["1.5 Üst"]),
    }

    def best_line(prefix_lines):
        best = None
        for ln in prefix_lines:
            for side in ("Üst", "Alt"):
                p = mk[f"{ln} {side}"]
                if p <= 0.82 and (best is None or p > best[1]):
                    best = (f"{ln} {side}", p)
        return best

    bl = best_line((1.5, 2.5, 3.5))
    rec["toplam_gol"] = {"secim": bl[0], "olasilik": pct(bl[1]), "adil_oran": fair(bl[1]), "risk": risk_of(bl[1]),
                         "tablo": [{"cizgi": ln, "ust": pct(mk[f"{ln} Üst"]), "alt": pct(mk[f"{ln} Alt"])}
                                   for ln in (0.5, 1.5, 2.5, 3.5, 4.5)]}
    kg = "KG Var" if mk["KG Var"] >= 0.5 else "KG Yok"
    rec["kg"] = {"secim": kg, "olasilik": pct(mk[kg]), "adil_oran": fair(mk[kg]), "risk": risk_of(mk[kg])}

    def count_pick(block, name):
        if not block:
            return None
        cand = []
        for r in block["cizgiler"]:
            for side, key in (("Üst", "ust"), ("Alt", "alt")):
                p = r[key] / 100
                if 0.55 <= p <= 0.80:
                    cand.append((f"{name} {r['cizgi']} {side}", p))
        if not cand:
            return {"secim": "Pas geç", "olasilik": None, "aralik": block["aralik"], "risk": "Yüksek"}
        c = max(cand, key=lambda t: t[1])
        return {"secim": c[0], "olasilik": pct(c[1]), "adil_oran": fair(c[1]), "aralik": block["aralik"],
                "risk": risk_of(c[1])}

    rec["korner"] = count_pick(corner, "Korner")
    rec["kart"] = count_pick(cards, "Kart")
    rec["sut"] = ({"toplam_sut": shots["aralik"], "isabetli": sot["aralik"] if sot else None,
                   "ev": shots["ev"], "dep": shots["dep"]} if shots else None)

    # En değerli 2-3 bahis
    cands = []
    for e in odds_eval:
        if e.get("durum") == "Değerli" and e["model"] >= 33:
            key = e["pazar"].replace("MS ", "")
            cands.append({"bahis": e["pazar"], "olasilik": e["model"], "oran": e["oran"],
                          "deger": e["deger"], "tip": "Değer (oran > adil oran)",
                          "risk": risk_of(mk[key], e["oran"])})
    cands.sort(key=lambda c: -c["deger"])
    pool = []
    for k in ("mac_sonucu", "kg", "toplam_gol"):
        r = rec[k]
        pool.append((r["secim"], r["olasilik"] / 100, r.get("adil_oran")))
    for k in ("korner", "kart"):
        r = rec.get(k)
        if r and r.get("olasilik"):
            pool.append((r["secim"], r["olasilik"] / 100, r.get("adil_oran")))
    if iy05 >= 0.6:
        pool.append(("İY 0.5 Üst", iy05, fair(iy05)))
    pool = [p for p in pool if p[2] and p[2] >= 1.2]
    pool.sort(key=lambda t: -t[1])
    used = {c["bahis"] for c in cands}
    for name, p, fo in pool:
        if len(cands) >= 3:
            break
        if name in used:
            continue
        cands.append({"bahis": name, "olasilik": pct(p), "oran": None, "adil_oran": fo,
                      "tip": "Yüksek olasılık", "risk": risk_of(p)})
        used.add(name)
    best = cands[:3]
    surpriz = [{"bahis": e["pazar"], "olasilik": e["model"], "oran": e["oran"], "deger": e["deger"]}
               for e in odds_eval if e.get("durum") == "Değerli" and e["model"] < 33]

    # ---- Format değerlendirmesi ----------------------------------------
    fmt_notes = []
    tbl = ctx.tables.get(fx.get("div")) if fx["comp_type"] == "lig" else None
    pos = {}
    if tbl:
        for t in (home, away):
            if t in tbl:
                pos[t] = tbl[t]
                s = tbl[t]
                n = s["takim_sayisi"]
                if s["sira"] <= 4:
                    fmt_notes.append(f"{t} üst sıralarda ({s['sira']}.), zirve/Avrupa motivasyonu yüksek.")
                elif s["sira"] > n - 3:
                    fmt_notes.append(f"{t} düşme hattında ({s['sira']}.), puan baskısı yüksek.")
        fmt_notes.insert(0, "Lig maçı: normal tempo; motivasyon puan durumuna bağlı.")
    elif fx["comp_type"] == "avrupa":
        fmt_notes.append("UEFA kupa maçı: lig aşaması ya da eleme olabilir. Elemede ilk maçlar daha temkinli geçer.")
        fmt_notes.append(f"Tek maçlık eleme olsaydı 90 dakikada beraberlik (uzatma/penaltı) ihtimali: %{pct(mk['X'])}.")
    else:
        fmt_notes.append("Ulusal kupa maçı: rotasyon ihtimali yüksek, favori takım kadro değiştirebilir.")
        fmt_notes.append(f"90 dakikada beraberlik, yani uzatma/penaltı ihtimali: %{pct(mk['X'])}.")
    if is_derby:
        fmt_notes.append(f"Derbi: {derby_why}. Kart ve faul sayısı normalden yüksek beklenir, form farkı önemini yitirebilir.")

    # ---- Genel karakter -------------------------------------------------
    xg_tot = lh + la
    tags = []
    tags.append("Açık / gollü" if xg_tot >= 3.0 else ("Temkinli / az gollü" if xg_tot <= 2.25 else "Dengeli tempo"))
    if cards and cards["toplam"] >= 5.0:
        tags.append("Kartlı / sert")
    if corner and corner["toplam"] >= 11:
        tags.append("Bol kornerli")
    if abs(mk["1"] - mk["2"]) >= 0.35:
        tags.append("Tek taraflı")
    elif abs(mk["1"] - mk["2"]) <= 0.12:
        tags.append("Başa baş")
    risks = []
    if mk["X"] >= 0.29:
        risks.append(f"Beraberlik ihtimali yüksek (%{pct(mk['X'])}); MS bahisleri riskli.")
    if is_derby:
        risks.append("Derbilerde istatistik sapması fazladır, stake düşük tutulmalı.")
    if fx["comp_type"] != "lig":
        risks.append("Kupa maçlarında rotasyon modelin göremediği bir risk.")
    if f_h and f_h["genel"] and f_h["genel"]["n"] < 8 or f_a and f_a["genel"] and f_a["genel"]["n"] < 8:
        risks.append("Takımlardan birinin veri sayısı az (yeni yükselen olabilir); güven düşük.")
    if not implied:
        risks.append("Oran verisi yok: önerileri iddaa oranıyla karşılaştırıp adil orandan yüksekse oyna.")

    return {
        "id": f"{fx['date']}_{home}_{away}".replace(" ", "_"),
        "tarih": fx["date"], "saat": fx.get("time"),
        "ev": home, "dep": away,
        "turnuva": fx["comp_name"], "tur": fx["comp_type"],
        "format": {"lig": "Lig maçı", "kupa": "Ulusal kupa", "avrupa": "UEFA Avrupa kupası"}[fx["comp_type"]],
        "derbi": {"var": is_derby, "neden": derby_why},
        "puan_durumu": pos,
        "yontem": method,
        "beklenen_gol": {"ev": round(lh, 2), "dep": round(la, 2), "toplam": round(lh + la, 2)},
        "olasiliklar": {k: pct(v) for k, v in mk.items() if k != "top_scores"},
        "ilk_yari_olasilik": {k: pct(ht[k]) for k in ("1", "X", "2", "0.5 Üst", "1.5 Üst")},
        "skorlar": [{"skor": s, "olasilik": pct(p)} for s, p in mk["top_scores"]],
        "form": {"ev": f_h, "dep": f_a},
        "korner": corner, "sut": shots, "isabetli_sut": sot, "kart": cards,
        "oranlar": odds_eval,
        "format_notlari": fmt_notes,
        "oneriler": rec,
        "en_degerli": best,
        "surpriz": surpriz,
        "karakter": tags,
        "riskler": risks,
        "veri_notlari": notes,
    }
