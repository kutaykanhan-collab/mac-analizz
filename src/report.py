"""Bir maç için tam analiz raporu (JSON) üretir."""
import math

import numpy as np
import pandas as pd

from config import DERBIES, DERBY_CARD_FACTOR, FORM_N, LEAGUE_STRENGTH, LEAGUES, MODEL_WEIGHT, OTHER_LEAGUE_STRENGTH, VALUE_EDGE
from model import CountModel, GoalModel, fit_lambdas, fit_league_strength, goal_markets, score_matrix
from names import ALIASES_ELO, norm
from stats import team_form


# --------------------------------------------------------------------------
# Lig modellerini bir kez kur
# --------------------------------------------------------------------------
class Context:
    def __init__(self, results, ref_date, elo=None):
        self.elo = elo or {}
        self.elo_norm = {}
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


def _elo_lookup(self, name):
    """football-data takım adı için ClubElo puanı (yoksa None)."""
    if not self.elo or not name:
        return None
    if not self.elo_norm:
        self.elo_norm = {norm(k): v for k, v in self.elo.items()}
    for cand in (name, ALIASES_ELO.get(name)):
        if not cand:
            continue
        if cand in self.elo:
            return self.elo[cand]
        if norm(cand) in self.elo_norm:
            return self.elo_norm[norm(cand)]
    return None


Context.elo_of = _elo_lookup


def _calibrate_uefa(self, uefa, match):
    """Geçmiş UEFA sonuçlarıyla lig güçlerini ölçer. Az veri varsa önsel değerler kalır."""
    self.uefa = {"c": None, "H": 0.25, "S": dict(LEAGUE_STRENGTH), "S_other": OTHER_LEAGUE_STRENGTH, "n": 0}
    if uefa is None or uefa.empty or "HG" not in uefa.columns:
        return
    done = uefa.dropna(subset=["HG", "AG"])
    done = done[done.Date < pd.Timestamp(self.ref_date, tz="UTC")]
    games = []
    for r in done.itertuples():
        h, a = match(r.Home), match(r.Away)
        lh, la = self.team_league.get(h), self.team_league.get(a)
        if not (lh or la):
            continue
        gh_, ga_ = self.goal.get(lh), self.goal.get(la)
        att_h = gh_.att.get(h, 0) if gh_ else 0.0
        de_h = gh_.de.get(h, 0) if gh_ else 0.0
        att_a = ga_.att.get(a, 0) if ga_ else 0.0
        de_a = ga_.de.get(a, 0) if ga_ else 0.0
        games.append((lh if gh_ else None, la if ga_ else None, att_h, de_h, att_a, de_a, float(r.HG), float(r.AG)))
    if len(games) < 40:
        return
    c, H, S, so = fit_league_strength(games, LEAGUE_STRENGTH, OTHER_LEAGUE_STRENGTH)
    self.uefa = {"c": c, "H": H, "S": S, "S_other": so, "n": len(games)}


Context.calibrate_uefa = _calibrate_uefa


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


def lambdas_from_expectancy(we, total):
    """Elo kazanma beklentisini (G + B/2) tutturan gol beklentisi ayrımı."""
    lo, hi = 0.05, 0.95
    for _ in range(40):
        mid = (lo + hi) / 2
        m = score_matrix(total * mid, total * (1 - mid))
        i, j = np.indices(m.shape)
        e = m[i > j].sum() + 0.5 * m[i == j].sum()
        if e > we:
            hi = mid
        else:
            lo = mid
    s = (lo + hi) / 2
    return total * s, total * (1 - s)


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

    # ---- Gol beklentisi (saf model) -------------------------------------
    method = None
    g_h, g_a = ctx.goal.get(lg_h), ctx.goal.get(lg_a)
    elo_h, elo_a = ctx.elo_of(fx.get("elo_home") or home), ctx.elo_of(fx.get("elo_away") or away)
    if lg_h and lg_h == lg_a and g_h:
        lh, la = g_h.lambdas(home, away)
        rho, ht_h, ht_a = g_h.rho, g_h.ht_h, g_h.ht_a
        method = "Lig gol modeli (Dixon-Coles Poisson, gol + isabetli şut)"
    elif g_h or g_a:
        # Ligler arası (UEFA) ya da rakibi takip dışı maç
        g0 = g_h or g_a
        rho, ht_h, ht_a = -0.05, g0.ht_h, g0.ht_a
        U = getattr(ctx, "uefa", None) or {"c": None, "H": 0.25, "S": LEAGUE_STRENGTH,
                                            "S_other": OTHER_LEAGUE_STRENGTH, "n": 0}
        c = U["c"] if U["c"] is not None else np.mean([g.mu for g in (g_h, g_a) if g])
        S_h = U["S"].get(lg_h, U["S_other"]) if g_h else U["S_other"]
        S_a = U["S"].get(lg_a, U["S_other"]) if g_a else U["S_other"]
        att_h = g_h.att.get(home, 0) if g_h else 0.0
        de_h = g_h.de.get(home, 0) if g_h else 0.0
        att_a = g_a.att.get(away, 0) if g_a else 0.0
        de_a = g_a.de.get(away, 0) if g_a else 0.0
        lh = math.exp(c + U["H"] + att_h - de_a + S_h - S_a)
        la = math.exp(c + att_a - de_h + S_a - S_h)
        src = f"{U['n']} geçmiş UEFA maçından ölçülen lig güçleri" if U["n"] else "varsayılan lig güçleri"
        method = f"Ligler arası gol modeli ({src})"
        if not (g_h and g_a):
            unknown = away if g_h else home
            notes.append(f"{unknown} takip edilen liglerde değil; gücü o liglerden gelen UEFA takımlarının "
                         "ortalaması kabul edildi. Bu maçta tahmin güveni düşük.")
        if elo_h and elo_a:
            # Elo varsa güç farkını Elo belirler, toplam gol modelden gelir
            dr = elo_h - elo_a + 60
            we = 1 / (10 ** (-dr / 400) + 1)
            lh, la = lambdas_from_expectancy(we, lh + la)
            method += " + ClubElo güç farkı"
    else:
        return None

    mk_model = goal_markets(score_matrix(lh, la, rho))

    # ---- Oranlar: piyasa olasılığı -------------------------------------
    row = fx.get("odds_row")
    odds = {
        "1": get_odds(row, ["AvgH", "B365H", "PSH", "MaxH"]),
        "X": get_odds(row, ["AvgD", "B365D", "PSD", "MaxD"]),
        "2": get_odds(row, ["AvgA", "B365A", "PSA", "MaxA"]),
        "2.5 Üst": get_odds(row, ["Avg>2.5", "B365>2.5", "P>2.5", "Max>2.5"]),
        "2.5 Alt": get_odds(row, ["Avg<2.5", "B365<2.5", "P<2.5", "Max<2.5"]),
    }
    implied, margins = {}, {}
    for group in (("1", "X", "2"), ("2.5 Üst", "2.5 Alt")):
        if all(odds[k] for k in group):
            ssum = sum(1 / odds[k] for k in group)
            for k in group:
                implied[k] = (1 / odds[k]) / ssum
            margins["/".join(group)] = round(100 * (ssum - 1), 1)

    # ---- Nihai olasılık: model + piyasa karışımı ------------------------
    # Geçmiş testte piyasa oranları tek başına modelden isabetliydi; ikisinin
    # karışımı en iyi sonucu verdi. Oran yoksa saf model kullanılır.
    if "1" in implied:
        w = MODEL_WEIGHT
        sup = w * (mk_model["1"] - mk_model["2"]) + (1 - w) * (implied["1"] - implied["2"])
        o25 = (w * mk_model["2.5 Üst"] + (1 - w) * implied["2.5 Üst"]) if "2.5 Üst" in implied else None
        lh, la = fit_lambdas(lh, la, sup, o25, rho)
        method += f" · %{round(100 * w)} model + %{round(100 * (1 - w))} piyasa"
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

    # ---- Oran değerlendirmesi --------------------------------------------
    odds_eval = []
    for k in ("1", "X", "2", "2.5 Üst", "2.5 Alt"):
        if k not in implied:
            continue
        edge = mk_model[k] * odds[k] - 1
        odds_eval.append({
            "pazar": "MS " + k if k in ("1", "X", "2") else k,
            "oran": odds[k], "piyasa": pct(implied[k]), "model": pct(mk_model[k]), "nihai": pct(mk[k]),
            "fark": round(100 * (mk_model[k] - implied[k]), 1), "deger": round(100 * edge, 1),
            "durum": "Model yüksek görüyor" if edge >= VALUE_EDGE else ("Uyumlu" if edge > -0.04 else "Model düşük görüyor"),
        })
    for g, mj in margins.items():
        odds_eval.append({"pazar": f"Kâr marjı ({g})", "marj": mj})
    if not implied:
        notes.append("Bu maç için oran verisi yok; olasılıklar sadece modelden geliyor.")

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
        # Sadece beklentiye en yakın çizgiler (uç çizgiler zaten bariz, oranı düşük olur)
        near = sorted(block["cizgiler"], key=lambda r: abs(r["cizgi"] - block["toplam"]))[:2]
        for r in near:
            for side, key in (("Üst", "ust"), ("Alt", "alt")):
                p = r[key] / 100
                if 0.52 <= p <= 0.80:
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

    # En güçlü 2-3 bahis (nihai olasılığa göre, farklı pazarlardan)
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
    best = []
    for name, p, fo in pool[:3]:
        oo = None
        key = name.replace("MS ", "")
        if key in odds and odds[key]:
            oo = odds[key]
        best.append({"bahis": name, "olasilik": pct(p), "oran": oo, "adil_oran": fo,
                     "tip": "Yüksek olasılık", "risk": risk_of(p)})
    surpriz = [{"bahis": e["pazar"], "olasilik": e["model"], "oran": e["oran"], "deger": e["deger"]}
               for e in odds_eval if e.get("durum") == "Model yüksek görüyor"]

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
    if not (g_h and g_a):
        risks.append("Rakip takımın verisi yok; olasılıklar kaba tahmin, stake düşük tutulmalı.")
    if f_h and f_h["genel"] and f_h["genel"]["n"] < 8 or f_a and f_a["genel"] and f_a["genel"]["n"] < 8:
        risks.append("Takımlardan birinin veri sayısı az (yeni yükselen olabilir); güven düşük.")
    if not implied:
        risks.append("Oran verisi yok: olasılıklar saf modelden; iddaa oranını adil oranla karşılaştır.")

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
