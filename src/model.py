"""İstatistik modelleri.

Gol:      Dixon-Coles düzeltmeli Poisson. Her takım için hücum/savunma gücü,
          ev sahibi avantajı ve zaman ağırlığı (yakın maçlar daha önemli).
Korner,
şut,kart: Çarpımsal model. Beklenen = lig ortalaması x takımın üretme katsayısı
          x rakibin izin verme katsayısı. Dağılım lig verisinden ölçülen
          saçılıma göre Poisson ya da Negatif Binom.
"""
import math

import numpy as np
import pandas as pd
from scipy.optimize import minimize, minimize_scalar
from scipy.stats import nbinom, poisson

from config import REF_SHRINK_K, RIDGE, SHRINK_K, SOT_MIX, TIME_DECAY

MAXG = 10


# --------------------------------------------------------------------------
# Gol modeli
# --------------------------------------------------------------------------
def _weights(dates, ref_date):
    days = (ref_date - dates).dt.days.clip(lower=0).to_numpy(float)
    return np.exp(-TIME_DECAY * days)


def _tau(x, y, lh, la, rho):
    if x == 0 and y == 0:
        return 1 - lh * la * rho
    if x == 0 and y == 1:
        return 1 + lh * rho
    if x == 1 and y == 0:
        return 1 + la * rho
    if x == 1 and y == 1:
        return 1 - rho
    return 1.0


class GoalModel:
    def __init__(self, df: pd.DataFrame, ref_date, ridge=RIDGE):
        df = df[df["Date"] < ref_date]
        self.teams = sorted(set(df.HomeTeam) | set(df.AwayTeam))
        self.idx = {t: i for i, t in enumerate(self.teams)}
        n = len(self.teams)
        hi = df.HomeTeam.map(self.idx).to_numpy()
        ai = df.AwayTeam.map(self.idx).to_numpy()
        hg_real = df.FTHG.to_numpy(float)
        ag_real = df.FTAG.to_numpy(float)
        # Takım gücü, gerçek gol ile isabetli şuttan beklenen golün karışımından
        # hesaplanır (şans faktörünü azaltır, geçmiş testte isabeti artırdı).
        hg, ag = hg_real.copy(), ag_real.copy()
        if SOT_MIX < 1 and {"HST", "AST"}.issubset(df.columns):
            ok = df.HST.notna().to_numpy() & df.AST.notna().to_numpy()
            if ok.sum() > 50:
                k = (hg_real[ok].sum() + ag_real[ok].sum()) / max(df.HST[ok].sum() + df.AST[ok].sum(), 1)
                hg[ok] = SOT_MIX * hg_real[ok] + (1 - SOT_MIX) * k * df.HST.to_numpy(float)[ok]
                ag[ok] = SOT_MIX * ag_real[ok] + (1 - SOT_MIX) * k * df.AST.to_numpy(float)[ok]
        w = _weights(df.Date, ref_date)
        self.n_matches = len(df)

        def nll(p):
            att, de, home, mu = p[:n], p[n:2 * n], p[2 * n], p[2 * n + 1]
            llh = mu + home + att[hi] - de[ai]
            lla = mu + att[ai] - de[hi]
            lh, la = np.exp(llh), np.exp(lla)
            f = np.sum(w * (lh - hg * llh + la - ag * lla)) + ridge * (att @ att + de @ de)
            rh, ra = w * (lh - hg), w * (la - ag)
            g = np.zeros_like(p)
            np.add.at(g[:n], hi, rh)
            np.add.at(g[:n], ai, ra)
            np.add.at(g[n:2 * n], ai, -rh)
            np.add.at(g[n:2 * n], hi, -ra)
            g[:n] += 2 * ridge * att
            g[n:2 * n] += 2 * ridge * de
            g[2 * n] = rh.sum()
            g[2 * n + 1] = rh.sum() + ra.sum()
            return f, g

        x0 = np.zeros(2 * n + 2)
        x0[2 * n + 1] = math.log(max(hg.mean(), 0.5)) if len(hg) else 0.3
        res = minimize(nll, x0, jac=True, method="L-BFGS-B")
        p = res.x
        self.att = dict(zip(self.teams, p[:n]))
        self.de = dict(zip(self.teams, p[n:2 * n]))
        self.home = p[2 * n]
        self.mu = p[2 * n + 1]

        # Dixon-Coles rho
        lh = np.exp(self.mu + self.home + p[:n][hi] - p[n:2 * n][ai])
        la = np.exp(self.mu + p[:n][ai] - p[n:2 * n][hi])
        low = (hg_real <= 1) & (ag_real <= 1)

        def rho_nll(r):
            s = 0.0
            for x, y, a, b, ww in zip(hg_real[low], ag_real[low], lh[low], la[low], w[low]):
                t = _tau(int(x), int(y), a, b, r)
                if t <= 0:
                    return 1e9
                s -= ww * math.log(t)
            return s

        self.rho = minimize_scalar(rho_nll, bounds=(-0.2, 0.2), method="bounded").x if low.any() else 0.0

        # İlk yarı / maç sonu gol oranı (ev ve deplasman ayrı)
        if {"HTHG", "HTAG"}.issubset(df.columns):
            d = df.dropna(subset=["HTHG", "HTAG"])
            ww = _weights(d.Date, ref_date)
            self.ht_h = float(np.sum(ww * d.HTHG) / max(np.sum(ww * d.FTHG), 1e-9))
            self.ht_a = float(np.sum(ww * d.HTAG) / max(np.sum(ww * d.FTAG), 1e-9))
        else:
            self.ht_h = self.ht_a = 0.44

    def has(self, team):
        return team in self.idx

    def lambdas(self, home, away, neutral=False):
        ha = 0.0 if neutral else self.home
        lh = math.exp(self.mu + ha + self.att.get(home, 0) - self.de.get(away, 0))
        la = math.exp(self.mu + self.att.get(away, 0) - self.de.get(home, 0))
        return lh, la

    def avg_total(self):
        return math.exp(self.mu + self.home) + math.exp(self.mu)


def score_matrix(lh, la, rho=0.0):
    h = poisson.pmf(np.arange(MAXG + 1), lh)
    a = poisson.pmf(np.arange(MAXG + 1), la)
    m = np.outer(h, a)
    for x in (0, 1):
        for y in (0, 1):
            m[x, y] *= _tau(x, y, lh, la, rho)
    return m / m.sum()


def goal_markets(m):
    """Skor matrisinden tüm gol pazarlarının olasılıkları."""
    i, j = np.indices(m.shape)
    tot = i + j
    out = {
        "1": m[i > j].sum(), "X": m[i == j].sum(), "2": m[i < j].sum(),
        "KG Var": m[(i > 0) & (j > 0)].sum(),
    }
    out["1X"] = out["1"] + out["X"]
    out["X2"] = out["X"] + out["2"]
    out["12"] = out["1"] + out["2"]
    out["KG Yok"] = 1 - out["KG Var"]
    for line in (0.5, 1.5, 2.5, 3.5, 4.5):
        out[f"{line} Üst"] = m[tot > line].sum()
        out[f"{line} Alt"] = 1 - out[f"{line} Üst"]
    flat = [((a, b), m[a, b]) for a in range(5) for b in range(5)]
    flat.sort(key=lambda t: -t[1])
    out["top_scores"] = [(f"{a}-{b}", float(p)) for (a, b), p in flat[:5]]
    return {k: (float(v) if not isinstance(v, list) else v) for k, v in out.items()}


def fit_lambdas(lh0, la0, sup_target=None, over25_target=None, rho=0.0):
    """Gol beklentisini hedef olasılıklara (ör. model+piyasa karışımı) uyacak şekilde
    ayarlar. sup_target = P(1)-P(2), over25_target = P(2.5 Üst)."""
    from scipy.optimize import minimize as _min

    def loss(x):
        lh, la = math.exp(x[0]), math.exp(x[1])
        m = score_matrix(lh, la, rho)
        i, j = np.indices(m.shape)
        e = 0.0
        if sup_target is not None:
            e += ((m[i > j].sum() - m[i < j].sum()) - sup_target) ** 2
        if over25_target is not None:
            e += (m[(i + j) > 2.5].sum() - over25_target) ** 2
        else:  # toplam gol modeldeki gibi kalsın
            e += 0.05 * ((lh + la) - (lh0 + la0)) ** 2
        return e

    r = _min(loss, [math.log(lh0), math.log(la0)], method="Nelder-Mead",
             options={"xatol": 1e-4, "fatol": 1e-8, "maxiter": 400})
    return math.exp(r.x[0]), math.exp(r.x[1])


def lambdas_from_probs(p_home, p_away, total):
    """Kupa / ligler arası maç: Elo'nun verdiği 1-2 olasılık farkını ve
    beklenen toplam golü tutturan ev/deplasman gol beklentisini bulur."""
    target = p_home - p_away

    def diff(s):
        lh, la = total * s, total * (1 - s)
        m = score_matrix(lh, la)
        i, j = np.indices(m.shape)
        return (m[i > j].sum() - m[i < j].sum()) - target

    lo, hi = 0.05, 0.95
    for _ in range(40):
        mid = (lo + hi) / 2
        if diff(mid) > 0:
            hi = mid
        else:
            lo = mid
    s = (lo + hi) / 2
    return total * s, total * (1 - s)


# --------------------------------------------------------------------------
# Korner / şut / kart modeli
# --------------------------------------------------------------------------
class CountModel:
    """hcol/acol: ev/deplasman takımının o istatistikteki değeri (ör. HC/AC)."""

    def __init__(self, df, hcol, acol, ref_date, ref_col=None):
        self.ok = hcol in df.columns and acol in df.columns
        if not self.ok:
            return
        d = df[df["Date"] < ref_date].dropna(subset=[hcol, acol])
        if len(d) < 30:
            self.ok = False
            return
        w = _weights(d.Date, ref_date)
        self.lh = float(np.average(d[hcol], weights=w))  # ev sahibi ortalaması
        self.la = float(np.average(d[acol], weights=w))  # deplasman ortalaması
        tot = (d[hcol] + d[acol]).to_numpy(float)
        mean = np.average(tot, weights=w)
        var = np.average((tot - mean) ** 2, weights=w)
        self.phi = max(var / mean, 1.0) if mean > 0 else 1.0

        acc = {}
        for (team, val, opp_val, base_for, base_against), ww in zip(
            list(zip(d.HomeTeam, d[hcol], d[acol], [self.lh] * len(d), [self.la] * len(d)))
            + list(zip(d.AwayTeam, d[acol], d[hcol], [self.la] * len(d), [self.lh] * len(d))),
            np.concatenate([w, w]),
        ):
            a = acc.setdefault(team, [0.0, 0.0, 0.0])
            a[0] += ww * (val / base_for if base_for else 1)
            a[1] += ww * (opp_val / base_against if base_against else 1)
            a[2] += ww
        self.f = {t: (s1 + SHRINK_K) / (n + SHRINK_K) for t, (s1, s2, n) in acc.items()}
        self.a = {t: (s2 + SHRINK_K) / (n + SHRINK_K) for t, (s1, s2, n) in acc.items()}

        # Hakem katsayısı (sadece hakem sütunu olan liglerde)
        self.ref = {}
        if ref_col and ref_col in d.columns:
            rd = d.dropna(subset=[ref_col])
            if len(rd):
                rw = _weights(rd.Date, ref_date)
                rt = (rd[hcol] + rd[acol]).to_numpy(float) / mean
                g = pd.DataFrame({"r": rd[ref_col].str.strip(), "v": rt * rw, "w": rw})
                g = g.groupby("r").sum()
                for r, row in g.iterrows():
                    self.ref[r] = {
                        "factor": (row.v + REF_SHRINK_K) / (row.w + REF_SHRINK_K),
                        "avg": float(row.v / row.w * mean) if row.w else None,
                        "n": int((rd[ref_col].str.strip() == r).sum()),
                    }

    def expect(self, home, away, factor=1.0, neutral=False):
        hb, ab = (self.lh, self.la) if not neutral else ((self.lh + self.la) / 2,) * 2
        eh = hb * self.f.get(home, 1) * self.a.get(away, 1) * factor
        ea = ab * self.f.get(away, 1) * self.a.get(home, 1) * factor
        return eh, ea

    def p_over(self, mean, line):
        k = math.floor(line)
        if self.phi <= 1.05:
            return float(1 - poisson.cdf(k, mean))
        n = mean / (self.phi - 1)
        return float(1 - nbinom.cdf(k, n, 1 / self.phi))

    def interval(self, mean, lo=0.2, hi=0.8):
        """Olasılığın %60'ını kapsayan aralık."""
        if self.phi <= 1.05:
            d = poisson(mean)
        else:
            d = nbinom(mean / (self.phi - 1), 1 / self.phi)
        return int(d.ppf(lo)), int(d.ppf(hi))


def side_rates(model_list, team):
    """Takım bir ligde yoksa (kupa rakibi) nötr katsayı döner."""
    for cm in model_list:
        if cm.ok and team in cm.f:
            return cm, cm.f[team], cm.a[team]
    return None, 1.0, 1.0


# --------------------------------------------------------------------------
# Ligler arası güç kalibrasyonu (geçmiş UEFA maç sonuçlarından)
# --------------------------------------------------------------------------
def fit_league_strength(games, prior, other_prior, prior_weight=4.0):
    """games: [(lig_ev, lig_dep, att_ev, de_ev, att_dep, de_dep, gol_ev, gol_dep)]
    lig None ise takım takip dışı liglerdendir ("DIGER").
    Model: log(ev gol) = c + H + att_ev - de_dep + S_ev - S_dep
           log(dep gol) = c + att_dep - de_ev + S_dep - S_ev
    Premier Lig S=0 sabit. S değerleri önsel tahmine doğru çekilir (az veri olabilir).
    Dönen: c, H, {lig: S}, S_diger"""
    leagues = sorted({g[0] for g in games if g[0]} | {g[1] for g in games if g[1]} | set(prior)) 
    leagues = [l for l in leagues if l != "E0"]
    idx = {l: i for i, l in enumerate(leagues)}
    n = len(leagues)
    pri = np.array([prior.get(l, -0.3) for l in leagues] + [other_prior])
    gh = np.array([g[6] for g in games], float)
    ga = np.array([g[7] for g in games], float)
    base_h = np.array([g[2] - g[5] for g in games])
    base_a = np.array([g[4] - g[3] for g in games])

    def sidx(l):
        if l == "E0":
            return -1
        return idx[l] if l else n

    ih = np.array([sidx(g[0]) for g in games])
    ia = np.array([sidx(g[1]) for g in games])

    def nll(p):
        c, H, S = p[0], p[1], np.append(p[2:], 0.0)  # son eleman E0 (indeks -1) = 0
        d = S[ih] - S[ia]
        llh = c + H + base_h + d
        lla = c + base_a - d
        f = np.sum(np.exp(llh) - gh * llh + np.exp(lla) - ga * lla)
        return f + prior_weight * np.sum((p[2:] - pri) ** 2)

    x0 = np.concatenate([[0.2, 0.25], pri])
    r = minimize(nll, x0, method="L-BFGS-B")
    p = r.x
    S = {l: float(p[2 + i]) for i, l in enumerate(leagues)}
    S["E0"] = 0.0
    return float(p[0]), float(p[1]), S, float(p[2 + n])
