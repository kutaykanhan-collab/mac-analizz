"""Canlı gol modeli. Sitedeki JavaScript sürümüyle (docs/canli.js) birebir aynı formül.

Fikir: Maç öncesi gol beklentisi (lh, la) kalan süreye dağıtılır, sonra maçta olanlarla
güncellenir:
  1) xG temposu: Takımın şu ana kadarki xG'si, maç öncesi beklentiyle harmanlanır.
     T0 = maç öncesi beklentinin "kaç dakikalık gözlem" kadar ağır bastığı.
  2) Skor durumu: Geride olan takım daha çok risk alır (x geri), önde olan geri çekilir (x ileri).
  3) Kırmızı kart: Eksik kalanın temposu düşer, rakibininki artar.
  4) Baskı (momentum): Son 10 dakikanın baskısı, sonraki 10 dakikanın temposunu etkiler.
"""
import math

DEFAULT = {"T0": 90.0, "beta": 0.3, "trail": 1.1, "lead": 0.95, "red_self": 0.75, "red_opp": 1.25,
           "stoppage1": 2.0, "stoppage2": 5.0, "window": 10, "g": 0.0, "scale": 1.0}


def _W(u, total, g):
    """Zaman profili: gol hızı maç ilerledikçe (1 + g*(u/total - 0.5)) oranında artar.
    W, 0'dan u'ya kadar biriken ağırlık (g=0 ise düz)."""
    return u + g * (u * u / (2 * total) - 0.5 * u)


def remaining_minutes(minute, half, p=DEFAULT):
    """minute: ekranda görünen dakika (1-90, uzatmada 45/90). half: 1 ya da 2."""
    if half == 1:
        return max(0.5, 45 - minute) + p["stoppage1"] * (1 if minute < 45 else 0.5) + 45 + p["stoppage2"]
    return max(0.5, 90 - minute) + (p["stoppage2"] if minute < 90 else p["stoppage2"] / 2)


def elapsed_minutes(minute, half, p=DEFAULT):
    if half == 1:
        return max(minute, 0.5)
    return minute + p["stoppage1"]


def rates(lh, la, minute, half, xg_h, xg_a, gh, ga, red_h, red_a, mom, p=DEFAULT):
    """Kalan süre için ev/dep gol beklentisi ve sonraki 10 dk beklentisi.
    mom: son 10 dakikanın ortalama baskısı, -1 (dep) .. +1 (ev)."""
    total = 90 + p["stoppage1"] + p["stoppage2"]
    g = p.get("g", 0.0)
    bh, ba = p.get("scale", 1.0) * lh / total, p.get("scale", 1.0) * la / total
    e = elapsed_minutes(minute, half, p)
    R = remaining_minutes(minute, half, p)
    end = e + R
    so_far = _W(e, total, g)
    T0 = p["T0"]
    # xG temposu: şu ana kadarki xG, şu ana kadar beklenenle karşılaştırılır (T0 = önselin ağırlığı)
    fh = (T0 * bh + xg_h) / (T0 * bh + bh * so_far) if T0 < 1e6 else 1.0
    fa = (T0 * ba + xg_a) / (T0 * ba + ba * so_far) if T0 < 1e6 else 1.0
    rh, ra = bh * fh, ba * fa
    d = gh - ga
    if d < 0:
        rh, ra = rh * p["trail"], ra * p["lead"]
    elif d > 0:
        rh, ra = rh * p["lead"], ra * p["trail"]
    rh *= p["red_self"] ** red_h * p["red_opp"] ** red_a
    ra *= p["red_self"] ** red_a * p["red_opp"] ** red_h
    w = min(p["window"], R)
    W_next = _W(e + w, total, g) - so_far
    W_rest = _W(end, total, g) - _W(e + w, total, g)
    next_h = rh * math.exp(p["beta"] * mom) * W_next
    next_a = ra * math.exp(-p["beta"] * mom) * W_next
    return {"rem_h": next_h + rh * W_rest, "rem_a": next_a + ra * W_rest, "next_h": next_h, "next_a": next_a, "R": R}


def pois(k, lam):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def outputs(r, gh, ga):
    lam = r["rem_h"] + r["rem_a"]
    p_goal = 1 - math.exp(-lam)
    p_next10 = 1 - math.exp(-(r["next_h"] + r["next_a"]))
    share_h = r["rem_h"] / lam if lam > 0 else 0.5
    res = {"1": 0.0, "X": 0.0, "2": 0.0}
    over = {}
    tot = {}
    for i in range(11):
        for j in range(11):
            pr = pois(i, r["rem_h"]) * pois(j, r["rem_a"])
            fh, fa = gh + i, ga + j
            res["1" if fh > fa else ("X" if fh == fa else "2")] += pr
            tot[fh + fa] = tot.get(fh + fa, 0) + pr
    cur = gh + ga
    for line in (cur + 0.5, cur + 1.5, cur + 2.5):
        over[line] = sum(v for k, v in tot.items() if k > line)
    return {"p_goal": p_goal, "p_next10": p_next10, "next_home": p_goal * share_h,
            "next_away": p_goal * (1 - share_h), "sonuc": res, "ust": over}
