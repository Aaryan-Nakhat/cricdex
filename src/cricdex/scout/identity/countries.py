"""One country code per cricket nation.

Every source spells nations differently: the LLM taxonomy mixes cricket abbreviations with ISO codes
(RSA and ZAF, SRI and LKA, BAN and BGD, IRE and IRL, WI and WIN), Cricsheet names teams in full
("United States of America"), Wikipedia's `{{cr|SA}}` flag templates use cricket codes and Wikidata
carries ISO 3166-1 alpha-3 codes on country items. `normalise` maps all of them to one code.

The canonical code is ISO 3166-1 alpha-3, except for the cricket sides that are not ISO countries:
ENG (England), SCO (Scotland) and WIN (West Indies, a multi-nation team). Ireland's cricket team
covers the whole island and is IRL. A British passport (GBR) is read as ENG, the usual case for a
professional cricketer; a Scottish player is caught by the more specific sources first.
"""

from __future__ import annotations

# Cricket sides that are not ISO 3166-1 countries.
CRICKET_ONLY = frozenset({"ENG", "SCO", "WIN"})

# Caribbean nations whose players represent the West Indies.
WEST_INDIES = frozenset(
    {
        "JAM",  # Jamaica
        "TTO",  # Trinidad and Tobago
        "BRB",  # Barbados
        "GUY",  # Guyana
        "ATG",  # Antigua and Barbuda
        "LCA",  # Saint Lucia
        "GRD",  # Grenada
        "KNA",  # Saint Kitts and Nevis
        "VCT",  # Saint Vincent and the Grenadines
        "DMA",  # Dominica
        "AIA",  # Anguilla
        "MSR",  # Montserrat
        "VGB",  # British Virgin Islands
        "VIR",  # US Virgin Islands
        "SXM",  # Sint Maarten
    }
)

# Non-ISO spellings → canonical code (ISO alpha-3 unless CRICKET_ONLY).
_ALIASES: dict[str, str] = {
    "RSA": "ZAF",
    "SA": "ZAF",
    "SAF": "ZAF",
    "SRI": "LKA",
    "SL": "LKA",
    "BAN": "BGD",
    "BD": "BGD",
    "IRE": "IRL",
    "WI": "WIN",
    "WIS": "WIN",
    "NED": "NLD",
    "HOL": "NLD",
    "ZIM": "ZWE",
    "UAE": "ARE",
    "NZ": "NZL",
    "NEP": "NPL",
    "GER": "DEU",
    "DEN": "DNK",
    "MAS": "MYS",
    "MAL": "MYS",
    "OMA": "OMN",
    "SIN": "SGP",
    "HK": "HKG",
    "KSA": "SAU",
    "SUI": "CHE",
    "POR": "PRT",
    "CRO": "HRV",
    "BRN": "BHR",
    "KUW": "KWT",
    "PHI": "PHL",
    "INA": "IDN",
    "GRE": "GRC",
    "TAN": "TZA",
    "NGR": "NGA",
    "BOT": "BWA",
    "ZAM": "ZMB",
    "CAY": "CYM",
    "BER": "BMU",
    "SAM": "WSM",
    "FIJ": "FJI",
    "JER": "JEY",
    "GUE": "GGY",
    "IOM": "IMN",
    "BUL": "BGR",
    "CHI": "CHL",
    "BHU": "BTN",
    "MYA": "MMR",
    "MAW": "MWI",  # Malawi's sporting code
    "MGL": "MNG",  # Mongolia's sporting code
    "GB-SCT": "SCO",  # ISO 3166-2 subdivision code for Scotland
    "GBR": "ENG",
    "UK": "ENG",
    "GB": "ENG",
    "IND": "IND",
    "AUS": "AUS",
    "PAK": "PAK",
    "AFG": "AFG",
    "USA": "USA",
    "US": "USA",
    "CAN": "CAN",
    "NAM": "NAM",
    "UGA": "UGA",
    "PNG": "PNG",
    "SCO": "SCO",
    "ENG": "ENG",
    "WAL": "ENG",  # Welsh players play for England
    "WLS": "ENG",
    "NIR": "IRL",
    "SWZ": "SWZ",
    "TLS": "TLS",
    "TCA": "TCA",
    "SHN": "SHN",
    "COK": "COK",
    "CIV": "CIV",
}

# Full names (Cricsheet team names, Wikipedia / Wikidata country labels) → canonical code.
_NAMES: dict[str, str] = {
    "india": "IND",
    "australia": "AUS",
    "england": "ENG",
    "united kingdom": "ENG",
    "great britain": "ENG",
    "wales": "ENG",
    "scotland": "SCO",
    "ireland": "IRL",
    "republic of ireland": "IRL",
    "northern ireland": "IRL",
    "south africa": "ZAF",
    "new zealand": "NZL",
    "pakistan": "PAK",
    "sri lanka": "LKA",
    "bangladesh": "BGD",
    "afghanistan": "AFG",
    "west indies": "WIN",
    "zimbabwe": "ZWE",
    "netherlands": "NLD",
    "kingdom of the netherlands": "NLD",
    "united arab emirates": "ARE",
    "united states": "USA",
    "united states of america": "USA",
    "usa": "USA",
    "canada": "CAN",
    "nepal": "NPL",
    "oman": "OMN",
    "namibia": "NAM",
    "papua new guinea": "PNG",
    "hong kong": "HKG",
    "singapore": "SGP",
    "malaysia": "MYS",
    "kenya": "KEN",
    "uganda": "UGA",
    "tanzania": "TZA",
    "nigeria": "NGA",
    "rwanda": "RWA",
    "botswana": "BWA",
    "ghana": "GHA",
    "germany": "DEU",
    "italy": "ITA",
    "france": "FRA",
    "spain": "ESP",
    "portugal": "PRT",
    "austria": "AUT",
    "belgium": "BEL",
    "denmark": "DNK",
    "sweden": "SWE",
    "norway": "NOR",
    "finland": "FIN",
    "switzerland": "CHE",
    "czech republic": "CZE",
    "czechia": "CZE",
    "hungary": "HUN",
    "romania": "ROU",
    "bulgaria": "BGR",
    "serbia": "SRB",
    "slovenia": "SVN",
    "croatia": "HRV",
    "greece": "GRC",
    "cyprus": "CYP",
    "malta": "MLT",
    "luxembourg": "LUX",
    "estonia": "EST",
    "gibraltar": "GIB",
    "guernsey": "GGY",
    "jersey": "JEY",
    "isle of man": "IMN",
    "israel": "ISR",
    "turkey": "TUR",
    "kuwait": "KWT",
    "qatar": "QAT",
    "bahrain": "BHR",
    "saudi arabia": "SAU",
    "iran": "IRN",
    "maldives": "MDV",
    "bhutan": "BTN",
    "myanmar": "MMR",
    "thailand": "THA",
    "cambodia": "KHM",
    "indonesia": "IDN",
    "philippines": "PHL",
    "japan": "JPN",
    "south korea": "KOR",
    "china": "CHN",
    "mongolia": "MNG",
    "uzbekistan": "UZB",
    "timor-leste": "TLS",
    "east timor": "TLS",
    "fiji": "FJI",
    "samoa": "WSM",
    "vanuatu": "VUT",
    "cook islands": "COK",
    "argentina": "ARG",
    "brazil": "BRA",
    "chile": "CHL",
    "peru": "PER",
    "mexico": "MEX",
    "panama": "PAN",
    "costa rica": "CRI",
    "belize": "BLZ",
    "suriname": "SUR",
    "bahamas": "BHS",
    "bermuda": "BMU",
    "cayman islands": "CYM",
    "turks and caicos island": "TCA",
    "turks and caicos islands": "TCA",
    "st helena": "SHN",
    "saint helena": "SHN",
    "cameroon": "CMR",
    "ivory coast": "CIV",
    "côte d'ivoire": "CIV",
    "gambia": "GMB",
    "the gambia": "GMB",
    "sierra leone": "SLE",
    "mali": "MLI",
    "malawi": "MWI",
    "mozambique": "MOZ",
    "zambia": "ZMB",
    "lesotho": "LSO",
    "eswatini": "SWZ",
    "swaziland": "SWZ",
    "seychelles": "SYC",
    "jamaica": "WIN",
    "trinidad and tobago": "WIN",
    "barbados": "WIN",
    "guyana": "WIN",
    "antigua and barbuda": "WIN",
    "saint lucia": "WIN",
    "grenada": "WIN",
    "saint kitts and nevis": "WIN",
    "saint vincent and the grenadines": "WIN",
    "dominica": "WIN",
}


def normalise(value: object) -> str | None:
    """Any spelling of a cricket nation → its canonical code, or None when unknown / empty.

    Accepts codes ("RSA", "zaf", "WI") and names ("South Africa", "United States of America").
    A three-letter code nobody listed is passed through upper-cased (it is already ISO alpha-3 for
    the associate nations the taxonomy names, e.g. "KEN", "NAM").
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in {"unknown", "none", "null", "n/a", "-"}:
        return None
    up = s.upper()
    if up in _ALIASES:
        return _ALIASES[up]
    if up in WEST_INDIES:
        return "WIN"
    low = s.lower()
    if low in _NAMES:
        return _NAMES[low]
    if len(up) == 3 and up.isalpha():
        return up
    return None


def team_country(team: str | None) -> str | None:
    """A Cricsheet international team name ("Sri Lanka") → code; None for non-national sides."""
    if not team:
        return None
    return _NAMES.get(team.strip().lower())


def all_codes() -> frozenset[str]:
    """Every canonical code this module can produce (for tests and validation)."""
    return frozenset(_ALIASES.values()) | frozenset(_NAMES.values())


# A Wikipedia title's disambiguator names the nation as an adjective ("Imran Khan (Trinidad and
# Tobago cricketer)", "Usman Tariq (Pakistani cricketer)"); `title_country` reads it.
_DEMONYMS = {
    "afghan": "AFG", "australian": "AUS", "bangladeshi": "BGD", "english": "ENG",
    "indian": "IND", "irish": "IRL", "kenyan": "KEN", "namibian": "NAM", "nepalese": "NPL",
    "nepali": "NPL", "dutch": "NLD", "new zealand": "NZL", "omani": "OMN", "pakistani": "PAK",
    "scottish": "SCO", "south african": "ZAF", "sri lankan": "LKA", "zimbabwean": "ZWE",
    "west indian": "WIN", "jamaican": "WIN", "barbadian": "WIN", "trinidadian": "WIN",
    "guyanese": "WIN", "antiguan": "WIN", "american": "USA", "canadian": "CAN", "emirati": "ARE",
    "ugandan": "UGA", "welsh": "ENG",
}  # fmt: skip


def title_country(title: str | None) -> str | None:
    """The nation a Wikipedia title's "(X cricketer)" disambiguator names, or None."""
    import re

    m = re.search(r"\(([^(),]+?) cricketer\b", title or "")
    if not m:
        return None
    x = m.group(1).strip()
    return _DEMONYMS.get(x.lower()) or normalise(x)
