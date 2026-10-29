"""Sistem ayarları. Lig listesi, model parametreleri, derbiler."""
from datetime import date

# football-data.co.uk lig kodları -> (Türkçe ad, ClubElo ülke kodu)
# "Gereksiz" alt ligler (İngiltere 3-5, İskoçya alt ligleri) bilerek yok.
LEAGUES = {
    "T1":  ("Türkiye Süper Lig",        "TUR"),
    "E0":  ("İngiltere Premier Lig",    "ENG"),
    "E1":  ("İngiltere Championship",   "ENG"),
    "SP1": ("İspanya La Liga",          "ESP"),
    "SP2": ("İspanya La Liga 2",        "ESP"),
    "I1":  ("İtalya Serie A",           "ITA"),
    "I2":  ("İtalya Serie B",           "ITA"),
    "D1":  ("Almanya Bundesliga",       "GER"),
    "D2":  ("Almanya 2. Bundesliga",    "GER"),
    "F1":  ("Fransa Ligue 1",           "FRA"),
    "F2":  ("Fransa Ligue 2",           "FRA"),
    "N1":  ("Hollanda Eredivisie",      "NED"),
    "P1":  ("Portekiz Liga Portugal",   "POR"),
    "B1":  ("Belçika Pro League",       "BEL"),
    "G1":  ("Yunanistan Süper Lig",     "GRE"),
    "SC0": ("İskoçya Premiership",      "SCO"),
}

COUNTRY_TR = {
    "TUR": "Türkiye", "ENG": "İngiltere", "ESP": "İspanya", "ITA": "İtalya",
    "GER": "Almanya", "FRA": "Fransa", "NED": "Hollanda", "POR": "Portekiz",
    "BEL": "Belçika", "GRE": "Yunanistan", "SCO": "İskoçya",
}

BASE_URL = "https://www.football-data.co.uk/mmz4281/{season}/{code}.csv"
FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"
CLUBELO_FIXTURES_URL = "http://api.clubelo.com/Fixtures"

TIMEZONE = "Europe/Istanbul"
DAYS_AHEAD = 1          # 0 = sadece bugün, 1 = bugün + yarın
FORM_N = 15             # form analizi için son maç sayısı
TIME_DECAY = 0.0030     # gol modelinde günlük ağırlık azalması (~230 gün yarı ömür)
SHRINK_K = 6            # az maçlı takımları lig ortalamasına çekme gücü
REF_SHRINK_K = 8        # hakem kart katsayısı için aynı mantık
DERBY_CARD_FACTOR = 1.15
VALUE_EDGE = 0.04       # model olasılığı x oran - 1 >= %4 ise "değerli"


def season_codes(today: date):
    """Ağustos ve sonrası yeni sezon sayılır. 2026-10 -> ['2627', '2526']"""
    start = today.year if today.month >= 7 else today.year - 1
    cur = f"{start % 100:02d}{(start + 1) % 100:02d}"
    prev = f"{(start - 1) % 100:02d}{start % 100:02d}"
    return [cur, prev]


# Derbi listesi (football-data takım adlarıyla). Sıra önemsiz.
DERBIES = [
    ({"Galatasaray", "Fenerbahce"}, "Kıtalararası Derbi, Türkiye'nin en büyük rekabeti"),
    ({"Galatasaray", "Besiktas"}, "İstanbul derbisi"),
    ({"Fenerbahce", "Besiktas"}, "İstanbul derbisi"),
    ({"Trabzonspor", "Fenerbahce"}, "Tarihi şampiyonluk rekabeti"),
    ({"Trabzonspor", "Galatasaray"}, "Tarihi şampiyonluk rekabeti"),
    ({"Trabzonspor", "Besiktas"}, "Büyük takımlar rekabeti"),
    ({"Goztep", "Karsiyaka"}, "İzmir derbisi"),
    ({"Arsenal", "Tottenham"}, "Kuzey Londra derbisi"),
    ({"Liverpool", "Everton"}, "Merseyside derbisi"),
    ({"Man United", "Man City"}, "Manchester derbisi"),
    ({"Man United", "Liverpool"}, "Kuzey-batı rekabeti"),
    ({"Chelsea", "Tottenham"}, "Londra derbisi"),
    ({"Arsenal", "Chelsea"}, "Londra derbisi"),
    ({"Real Madrid", "Barcelona"}, "El Clasico"),
    ({"Real Madrid", "Ath Madrid"}, "Madrid derbisi"),
    ({"Sevilla", "Betis"}, "Sevilla derbisi"),
    ({"Ath Bilbao", "Sociedad"}, "Bask derbisi"),
    ({"Barcelona", "Espanol"}, "Barcelona derbisi"),
    ({"Inter", "Milan"}, "Derby della Madonnina"),
    ({"Roma", "Lazio"}, "Derby della Capitale"),
    ({"Juventus", "Torino"}, "Derby della Mole"),
    ({"Juventus", "Inter"}, "Derby d'Italia"),
    ({"Genoa", "Sampdoria"}, "Derby della Lanterna"),
    ({"Dortmund", "Schalke 04"}, "Revier derbisi"),
    ({"Bayern Munich", "Dortmund"}, "Der Klassiker"),
    ({"Hamburg", "St Pauli"}, "Hamburg derbisi"),
    ({"Paris SG", "Marseille"}, "Le Classique"),
    ({"Lyon", "St Etienne"}, "Rhône derbisi"),
    ({"Nice", "Monaco"}, "Côte d'Azur derbisi"),
    ({"Ajax", "Feyenoord"}, "De Klassieker"),
    ({"Ajax", "PSV Eindhoven"}, "Hollanda zirve rekabeti"),
    ({"Benfica", "Sp Lisbon"}, "Lizbon derbisi"),
    ({"Porto", "Benfica"}, "O Clássico"),
    ({"Celtic", "Rangers"}, "Old Firm"),
    ({"Olympiakos", "Panathinaikos"}, "Ezeli rakipler derbisi"),
    ({"AEK", "Panathinaikos"}, "Atina derbisi"),
    ({"Club Brugge", "Cercle Brugge"}, "Brugge derbisi"),
    ({"Anderlecht", "Club Brugge"}, "Belçika klasiği"),
]
