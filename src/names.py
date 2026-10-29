"""Takım adı eşleştirme. Farklı kaynaklar aynı takımı farklı yazar
(ör. "Manchester City" / "Man City", "Fenerbahçe" / "Fenerbahce")."""
import difflib
import re
import unicodedata

# Başka kaynaktaki ad -> football-data adı. Eşleşmeyen takım olursa buraya ekle.
ALIASES = {
    "Manchester City": "Man City", "Manchester United": "Man United",
    "Tottenham Hotspur": "Tottenham", "Newcastle United": "Newcastle",
    "Nottingham Forest": "Nott'm Forest", "Forest": "Nott'm Forest",
    "Wolverhampton Wanderers": "Wolves", "West Ham United": "West Ham",
    "Brighton & Hove Albion": "Brighton", "Brighton and Hove Albion": "Brighton",
    "Bayern München": "Bayern Munich", "FC Bayern München": "Bayern Munich", "Bayern": "Bayern Munich",
    "Borussia Dortmund": "Dortmund", "Bayer 04 Leverkusen": "Leverkusen", "Bayer Leverkusen": "Leverkusen",
    "Borussia Mönchengladbach": "M'gladbach", "Gladbach": "M'gladbach",
    "Eintracht Frankfurt": "Ein Frankfurt", "Frankfurt": "Ein Frankfurt",
    "VfB Stuttgart": "Stuttgart", "SC Freiburg": "Freiburg", "TSG Hoffenheim": "Hoffenheim",
    "1. FC Köln": "FC Koln", "Koeln": "FC Koln", "1. FSV Mainz 05": "Mainz", "Mainz 05": "Mainz",
    "RB Leipzig": "RB Leipzig", "VfL Wolfsburg": "Wolfsburg", "Union Berlin": "Union Berlin",
    "Atlético de Madrid": "Ath Madrid", "Atlético Madrid": "Ath Madrid", "Atletico Madrid": "Ath Madrid",
    "Atletico": "Ath Madrid", "Athletic Club": "Ath Bilbao", "Athletic Bilbao": "Ath Bilbao", "Bilbao": "Ath Bilbao",
    "Real Sociedad": "Sociedad", "Real Betis": "Betis", "Celta Vigo": "Celta", "RC Celta": "Celta",
    "Villarreal CF": "Villarreal", "Rayo Vallecano": "Vallecano", "Espanyol": "Espanol",
    "Internazionale": "Inter", "Inter Milan": "Inter", "FC Internazionale Milano": "Inter",
    "AC Milan": "Milan", "AS Roma": "Roma", "SS Lazio": "Lazio", "SSC Napoli": "Napoli",
    "ACF Fiorentina": "Fiorentina", "Atalanta BC": "Atalanta", "Bologna FC": "Bologna",
    "Paris Saint-Germain": "Paris SG", "Paris": "Paris SG", "PSG": "Paris SG",
    "Olympique de Marseille": "Marseille", "Olympique Lyonnais": "Lyon", "OGC Nice": "Nice",
    "AS Monaco": "Monaco", "LOSC Lille": "Lille", "Lille OSC": "Lille", "Stade Rennais": "Rennes",
    "RC Lens": "Lens", "RC Strasbourg": "Strasbourg", "Saint-Etienne": "St Etienne", "Stade Brestois": "Brest",
    "Sporting CP": "Sp Lisbon", "Sporting": "Sp Lisbon", "SC Braga": "Sp Braga", "Braga": "Sp Braga",
    "FC Porto": "Porto", "SL Benfica": "Benfica", "Vitória SC": "Guimaraes", "Vitoria Guimaraes": "Guimaraes",
    "PSV": "PSV Eindhoven", "AZ": "AZ Alkmaar", "FC Twente": "Twente", "FC Utrecht": "Utrecht",
    "Go Ahead Eagles": "Go Ahead Eagles", "Feyenoord Rotterdam": "Feyenoord", "AFC Ajax": "Ajax",
    "Club Brugge": "Club Brugge", "Brugge": "Club Brugge", "Union Saint-Gilloise": "St. Gilloise",
    "Royale Union Saint-Gilloise": "St. Gilloise", "Union SG": "St. Gilloise", "KRC Genk": "Genk",
    "KAA Gent": "Gent", "RSC Anderlecht": "Anderlecht", "Royal Antwerp": "Antwerp",
    "Olympiacos": "Olympiakos", "Olympiacos FC": "Olympiakos", "AEK Athens": "AEK", "PAOK Thessaloniki": "PAOK",
    "Panathinaikos FC": "Panathinaikos",
    "Celtic FC": "Celtic", "Rangers FC": "Rangers", "Heart of Midlothian": "Hearts", "Aberdeen FC": "Aberdeen",
    "Fenerbahçe": "Fenerbahce", "Beşiktaş": "Besiktas", "Galatasaray AŞ": "Galatasaray",
    "İstanbul Başakşehir": "Buyuksehyr", "Istanbul Basaksehir": "Buyuksehyr", "Başakşehir": "Buyuksehyr",
    "Basaksehir": "Buyuksehyr", "Istanbul": "Buyuksehyr",
    "Göztepe": "Goztep", "Goztepe": "Goztep", "Goeztepe": "Goztep", "Samsunspor": "Samsunspor",
    "Trabzonspor": "Trabzonspor",
    "Atleti": "Ath Madrid", "Man Utd": "Man United", "B. Dortmund": "Dortmund", "Leipzig": "RB Leipzig",
    "N.E.C.": "Nijmegen", "NEC Nijmegen": "Nijmegen", "Sint-Truidense": "St Truiden", "Sint-Truiden": "St Truiden",
    "B. Mönchengladbach": "M'gladbach", "Ath. Bilbao": "Ath Bilbao", "Athletic": "Ath Bilbao",
    "Spurs": "Tottenham", "Newcastle Utd": "Newcastle", "Nott'm Forest": "Nott'm Forest",
    "PAOK": "PAOK", "Başakşehir FK": "Buyuksehyr", "Samsunspor": "Samsunspor",
    "Sporting Braga": "Sp Braga", "Sporting Gijon": "Sp Gijon", "Sporting Gijón": "Sp Gijon",
    "Racing Santander": "Santander", "Deportivo La Coruna": "La Coruna", "Deportivo": "La Coruna",
    "CD Castellon": "Castellon", "FC Andorra": "Andorra", "Real Oviedo": "Oviedo",
    "Real Valladolid": "Valladolid", "R. Valladolid": "Valladolid", "Real Zaragoza": "Zaragoza",
    "UD Las Palmas": "Las Palmas", "CD Leganes": "Leganes", "Cadiz CF": "Cadiz", "Granada CF": "Granada",
    "Fortuna Sittard": "For Sittard", "ADO Den Haag": "Den Haag", "PEC Zwolle": "Zwolle",
    "Estrela Amadora": "Estrela", "Casa Pia AC": "Casa Pia", "CD Nacional": "Nacional",
    "Çaykur Rizespor": "Rizespor", "Gaziantep FK": "Gaziantep", "Fatih Karagümrük": "Karagumruk",
    "Eyüpspor": "Eyupspor", "Amed Sportif Faaliyetler": "Amedspor", "Amed SFK": "Amedspor",
    "Çorum FK": "Corum", "Erzurumspor FK": "Erzurumspor", "Gençlerbirliği": "Genclerbirligi",
    "Greuther Fürth": "Greuther Furth", "1. FC Nürnberg": "Nurnberg", "Hertha BSC": "Hertha",
    "Hannover 96": "Hannover", "1. FC Kaiserslautern": "Kaiserslautern", "Eintracht Braunschweig": "Braunschweig",
    "Arminia Bielefeld": "Bielefeld", "VfL Bochum": "Bochum", "Dynamo Dresden": "Dresden",
    "Hellas Verona": "Verona", "SV Zulte Waregem": "Waregem", "Zulte Waregem": "Waregem",
    "Stade Lavallois": "Laval", "Energie Cottbus": "Cottbus", "Royal Antwerp FC": "Antwerp",
    "Standard Liege": "Standard", "Standard Liège": "Standard", "Sporting Charleroi": "Charleroi",
    "KV Mechelen": "Mechelen", "Cercle Brugge KSV": "Cercle Brugge", "OH Leuven": "Oud-Heverlee Leuven",
    "Westerlo": "Westerlo", "Sint-Truidense VV": "St Truiden", "Dender": "Dender", "Pau": "Pau FC", "Red Star FC": "Red Star", "Queens Park Rangers": "QPR",
    "West Bromwich Albion": "West Brom", "Sheffield Utd": "Sheffield United",
}

# football-data adı -> ClubElo adı (Elo puanı aramak için)
ALIASES_ELO = {
    "Bayern Munich": "Bayern", "Ein Frankfurt": "Frankfurt", "M'gladbach": "Gladbach",
    "FC Koln": "Koeln", "Ath Madrid": "Atletico", "Ath Bilbao": "Bilbao",
    "Sp Lisbon": "Sporting", "Sp Braga": "Braga", "PSV Eindhoven": "PSV", "AZ Alkmaar": "AZ",
    "Club Brugge": "Brugge", "Paris SG": "Paris SG", "St Etienne": "Saint-Etienne",
    "Nott'm Forest": "Forest", "Buyuksehyr": "Istanbul", "Goztep": "Goeztepe",
    "St. Gilloise": "Union SG", "Espanol": "Espanyol", "Vallecano": "Rayo Vallecano",
}

_DROP = r"\b(fc|cf|sc|ac|afc|sk|fk|as|ss|us|ssc|acf|ogc|losc|rc|rcd|cd|sl|kaa|krc|rsc|vfb|vfl|tsg|bc|jk|1)\b"


def norm(s):
    s = unicodedata.normalize("NFKD", str(s).replace("ı", "i").replace("İ", "I"))
    s = s.encode("ascii", "ignore").decode().lower()
    s = re.sub(_DROP, " ", s)
    return re.sub(r"[^a-z0-9]", "", s)


def build_matcher(teams, team_country=None):
    """team_country: {takım: ülke kodu}. Verilirse aynı ülke içinde kelime bazlı eşleştirme
    de yapılır (ör. "SV Zulte Waregem" -> "Waregem", "Energie Cottbus" -> "Cottbus")."""
    teams = set(teams)
    by_norm = {norm(t): t for t in teams}
    team_country = team_country or {}

    def match(name, country=None):
        if not name:
            return None
        if name in teams:
            return name
        if name in ALIASES and ALIASES[name] in teams:
            return ALIASES[name]
        n = norm(name)
        if n in by_norm:
            return by_norm[n]
        hit = difflib.get_close_matches(n, list(by_norm), n=1, cutoff=0.84)
        if hit:
            return by_norm[hit[0]]
        if country:
            words = [norm(w) for w in re.split(r"[\s\-/]+", str(name))]
            words = [w for w in words if len(w) >= 4]
            pool = [t for t in teams if team_country.get(t) == country]
            hits = [t for t in pool if norm(t) in words]
            if len(hits) == 1:
                return hits[0]
        return None

    return match
