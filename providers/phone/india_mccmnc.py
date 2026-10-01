"""
Offline MCC/MNC (ITU-T E.212) table for India (MCC 404 and 405).

BEST-EFFORT, VERIFY BEFORE RELYING ON IT.  The table was compiled on
``AS_OF`` from the public Wikipedia page listed in ``SOURCE`` (which itself is
derived from ITU-T operational bulletins and operator announcements).  Indian
MNCs are notoriously messy: circles were re-assigned during the Idea/Vodafone
merger (2018), the Tata/Telenor absorption into Airtel (2018-2019), Aircel's
bankruptcy (2018) and RCom's exit from voice services (2019).  Rows keep the
status reported by the source; "not_operational" codes are retained because
old SIMs / stale third-party data may still surface them.

An MCC/MNC identifies a *network*, never a person.  Because of nationwide
Mobile Number Portability the MNC reported for a number reflects the operator
whose network currently (or historically) serves it, which is not evidence
about the subscriber.

Public API
----------
``INDIA_MCCMNC``  - ``{"404-31": {"operator": ..., "circle": ..., "status": ..., "note": ...}, ...}``
``decode_mccmnc(mcc, mnc)`` - lookup helper returning a copy of the row (with
``mcc``/``mnc`` added) or ``None``.
"""

from __future__ import annotations

from typing import Optional, TypedDict

SOURCE = (
    "https://en.wikipedia.org/wiki/Mobile_Network_Codes_in_ITU_region_4xx_(Asia)"
    "  (India section, MCC 404/405)"
)
AS_OF = "2026-09-08"

OPERATIONAL = "operational"
NOT_OPERATIONAL = "not_operational"
UNKNOWN = "unknown"

# canonical operator labels
AIRTEL = "Airtel (Bharti Airtel)"
VI = "Vi (Vodafone Idea)"
BSNL = "BSNL"
MTNL = "MTNL"
JIO = "Jio (Reliance Jio Infocomm)"
RCOM = "Reliance Communications"
AIRCEL = "Aircel"
TATA = "Tata Docomo"
UNINOR = "Telenor India (Uninor)"
LOOP = "Loop Mobile"
MTS = "MTS (Sistema Shyam)"
VIDEOCON = "Videocon Telecom"
RAILWAYS = "Indian Railways GSM-R"
HFCL = "HFCL Infotel (Ping Mobile)"


class MccMncRow(TypedDict):
    operator: str
    circle: str
    status: str
    note: str


# (mcc, mnc, operator, circle, status, note)
_ROWS: list[tuple[str, str, str, str, str, str]] = [
    # ------------------------------------------------------------- MCC 404
    ("404", "01", VI, "Haryana", OPERATIONAL, "former Vodafone"),
    ("404", "02", AIRTEL, "Punjab", OPERATIONAL, ""),
    ("404", "03", AIRTEL, "Himachal Pradesh", OPERATIONAL, ""),
    ("404", "04", VI, "Delhi & NCR", NOT_OPERATIONAL, "former Idea"),
    ("404", "05", VI, "Gujarat", OPERATIONAL, "former Hutch/Fascel/Vodafone"),
    ("404", "07", VI, "Andhra Pradesh & Telangana", OPERATIONAL, "former Idea"),
    ("404", "09", RCOM, "Assam", UNKNOWN, "data-only as of 2020; RCom exited voice 2019"),
    ("404", "10", AIRTEL, "Delhi & NCR", OPERATIONAL, ""),
    ("404", "11", VI, "Delhi & NCR", OPERATIONAL, "former Vodafone"),
    ("404", "12", VI, "Haryana", NOT_OPERATIONAL, "former Escotel/Idea"),
    ("404", "13", VI, "Andhra Pradesh & Telangana", NOT_OPERATIONAL, "former Vodafone"),
    ("404", "14", VI, "Punjab", OPERATIONAL, "former Spice/Idea"),
    ("404", "15", VI, "Uttar Pradesh (East)", OPERATIONAL, "former Vodafone"),
    ("404", "16", AIRTEL, "North East", OPERATIONAL, "former Hexacom"),
    ("404", "17", AIRCEL, "West Bengal", NOT_OPERATIONAL, "bankrupt 2018"),
    ("404", "18", RCOM, "Himachal Pradesh", UNKNOWN, "data-only as of 2020"),
    ("404", "19", VI, "Kerala", NOT_OPERATIONAL, "former Escotel/Idea"),
    ("404", "20", VI, "Mumbai", OPERATIONAL, "former Hutchison Max/Orange/Hutch/Vodafone"),
    ("404", "21", LOOP, "Mumbai", NOT_OPERATIONAL, "former BPL Mobile; licence expired 2014"),
    ("404", "22", VI, "Maharashtra & Goa", OPERATIONAL, "former Idea"),
    ("404", "23", RCOM, "West Bengal", NOT_OPERATIONAL, "Reliance Telecom"),
    ("404", "24", VI, "Gujarat", NOT_OPERATIONAL, "former Idea"),
    ("404", "25", AIRCEL, "Bihar", NOT_OPERATIONAL, "bankrupt 2018"),
    ("404", "27", VI, "Maharashtra & Goa", NOT_OPERATIONAL, "former Vodafone"),
    ("404", "28", AIRCEL, "Odisha", NOT_OPERATIONAL, "bankrupt 2018"),
    ("404", "29", AIRCEL, "Assam", NOT_OPERATIONAL, "bankrupt 2018"),
    ("404", "30", VI, "Kolkata", OPERATIONAL, "former Vodafone/Command/Hutch"),
    ("404", "31", AIRTEL, "Kolkata", OPERATIONAL, ""),
    ("404", "33", AIRCEL, "North East", NOT_OPERATIONAL, "bankrupt 2018"),
    ("404", "34", BSNL, "Haryana", OPERATIONAL, "former CellOne"),
    ("404", "35", AIRCEL, "Himachal Pradesh", NOT_OPERATIONAL, "bankrupt 2018"),
    ("404", "36", RCOM, "Bihar & Jharkhand", UNKNOWN, "data-only as of 2020"),
    ("404", "37", AIRCEL, "Jammu & Kashmir", NOT_OPERATIONAL, "bankrupt 2018"),
    ("404", "38", BSNL, "Assam", OPERATIONAL, "former CellOne"),
    ("404", "40", AIRTEL, "Chennai", OPERATIONAL, ""),
    ("404", "41", AIRCEL, "Chennai", NOT_OPERATIONAL, "former RPG; bankrupt 2018"),
    ("404", "42", AIRCEL, "Tamil Nadu", NOT_OPERATIONAL, "bankrupt 2018"),
    ("404", "43", VI, "Tamil Nadu", OPERATIONAL, "former Vodafone"),
    ("404", "44", VI, "Karnataka", NOT_OPERATIONAL, "former Spice/Idea"),
    ("404", "45", AIRTEL, "Karnataka", OPERATIONAL, ""),
    ("404", "46", VI, "Kerala", OPERATIONAL, "former Vodafone"),
    ("404", "48", AIRCEL, "", NOT_OPERATIONAL, "Dishnet Wireless (Aircel group); circle unknown"),
    ("404", "49", AIRTEL, "Andhra Pradesh & Telangana", OPERATIONAL, ""),
    ("404", "50", RCOM, "North East", UNKNOWN, "data-only as of 2020"),
    ("404", "51", BSNL, "Himachal Pradesh", OPERATIONAL, "former CellOne"),
    ("404", "52", RCOM, "Odisha", UNKNOWN, "data-only as of 2020"),
    ("404", "53", BSNL, "Punjab", OPERATIONAL, "former CellOne"),
    ("404", "54", BSNL, "Uttar Pradesh (West)", OPERATIONAL, "former CellOne"),
    ("404", "55", BSNL, "Uttar Pradesh (East)", OPERATIONAL, "former CellOne"),
    ("404", "56", VI, "Uttar Pradesh (West)", OPERATIONAL, "former Idea"),
    ("404", "57", BSNL, "Gujarat", OPERATIONAL, "former CellOne"),
    ("404", "58", BSNL, "Madhya Pradesh & Chhattisgarh", OPERATIONAL, "former CellOne"),
    ("404", "59", BSNL, "Rajasthan", OPERATIONAL, "former CellOne"),
    ("404", "60", VI, "Rajasthan", OPERATIONAL, "former Vodafone"),
    ("404", "62", BSNL, "Jammu & Kashmir", OPERATIONAL, "former CellOne"),
    ("404", "64", BSNL, "Chennai", OPERATIONAL, "former CellOne"),
    ("404", "66", BSNL, "Maharashtra & Goa", OPERATIONAL, "former CellOne"),
    ("404", "67", RCOM, "Madhya Pradesh & Chhattisgarh", NOT_OPERATIONAL, ""),
    ("404", "68", MTNL, "Delhi & NCR", OPERATIONAL, "to be merged with BSNL"),
    ("404", "69", MTNL, "Mumbai", OPERATIONAL, "to be merged with BSNL"),
    ("404", "70", AIRTEL, "Rajasthan", OPERATIONAL, ""),
    ("404", "71", BSNL, "Karnataka", OPERATIONAL, "former CellOne"),
    ("404", "72", BSNL, "Kerala", OPERATIONAL, "former CellOne"),
    ("404", "73", BSNL, "Andhra Pradesh & Telangana", OPERATIONAL, "former CellOne"),
    ("404", "74", BSNL, "West Bengal", OPERATIONAL, "former CellOne"),
    ("404", "75", BSNL, "Bihar", OPERATIONAL, "former CellOne"),
    ("404", "76", BSNL, "Odisha", OPERATIONAL, "former CellOne"),
    ("404", "77", BSNL, "North East", OPERATIONAL, "former CellOne"),
    ("404", "78", VI, "Madhya Pradesh & Chhattisgarh", OPERATIONAL, "former Idea"),
    ("404", "79", BSNL, "Andaman & Nicobar", OPERATIONAL, "former CellOne"),
    ("404", "80", BSNL, "Tamil Nadu", OPERATIONAL, "former CellOne"),
    ("404", "81", BSNL, "Kolkata", OPERATIONAL, "former CellOne"),
    ("404", "82", VI, "", OPERATIONAL, "former Idea; circle not listed by source"),
    ("404", "83", RCOM, "Kolkata", UNKNOWN, "data-only as of 2020"),
    ("404", "84", VI, "Chennai", NOT_OPERATIONAL, "former Vodafone"),
    ("404", "85", RCOM, "West Bengal", UNKNOWN, "data-only as of 2020"),
    ("404", "86", VI, "Karnataka", OPERATIONAL, "former Vodafone"),
    ("404", "87", VI, "", NOT_OPERATIONAL, "former Idea; circle not listed by source"),
    ("404", "88", VI, "Punjab", NOT_OPERATIONAL, "former Vodafone"),
    ("404", "89", VI, "", NOT_OPERATIONAL, "former Idea; circle not listed by source"),
    ("404", "90", AIRTEL, "Maharashtra & Goa", OPERATIONAL, ""),
    ("404", "91", AIRCEL, "Kolkata", NOT_OPERATIONAL, "bankrupt 2018"),
    ("404", "92", AIRTEL, "Mumbai", OPERATIONAL, ""),
    ("404", "93", AIRTEL, "Madhya Pradesh & Chhattisgarh", OPERATIONAL, ""),
    ("404", "94", AIRTEL, "Tamil Nadu", OPERATIONAL, ""),
    ("404", "95", AIRTEL, "Kerala", OPERATIONAL, ""),
    ("404", "96", AIRTEL, "Haryana", OPERATIONAL, ""),
    ("404", "97", AIRTEL, "Uttar Pradesh (West)", OPERATIONAL, ""),
    ("404", "98", AIRTEL, "Gujarat", OPERATIONAL, ""),
    # ------------------------------------------------------------- MCC 405
    ("405", "01", RCOM, "Andhra Pradesh", NOT_OPERATIONAL, "CDMA"),
    ("405", "03", RCOM, "Bihar", UNKNOWN, "data-only as of 2020"),
    ("405", "04", RCOM, "Chennai", UNKNOWN, "data-only as of 2020"),
    ("405", "05", RCOM, "Delhi & NCR", UNKNOWN, "data-only as of 2020"),
    ("405", "06", RCOM, "Gujarat", UNKNOWN, "data-only as of 2020"),
    ("405", "07", RCOM, "Haryana", UNKNOWN, "data-only as of 2020"),
    ("405", "08", RCOM, "Himachal Pradesh", UNKNOWN, "data-only as of 2020"),
    ("405", "09", RCOM, "Jammu & Kashmir", UNKNOWN, "data-only as of 2020"),
    ("405", "10", RCOM, "Karnataka", UNKNOWN, "data-only as of 2020"),
    ("405", "11", RCOM, "Kerala", UNKNOWN, "data-only as of 2020"),
    ("405", "12", RCOM, "Kolkata", UNKNOWN, "data-only as of 2020"),
    ("405", "13", RCOM, "Maharashtra & Goa", UNKNOWN, "data-only as of 2020"),
    ("405", "14", RCOM, "Madhya Pradesh", UNKNOWN, "data-only as of 2020"),
    ("405", "15", RCOM, "Mumbai", UNKNOWN, "data-only as of 2020"),
    ("405", "17", RCOM, "Odisha", UNKNOWN, "data-only as of 2020"),
    ("405", "18", RCOM, "Punjab", UNKNOWN, "data-only as of 2020"),
    ("405", "19", RCOM, "Rajasthan", UNKNOWN, "data-only as of 2020"),
    ("405", "20", RCOM, "Tamil Nadu", UNKNOWN, "data-only as of 2020"),
    ("405", "21", RCOM, "Uttar Pradesh (East)", UNKNOWN, "data-only as of 2020"),
    ("405", "22", RCOM, "Uttar Pradesh (West)", UNKNOWN, "data-only as of 2020"),
    ("405", "23", RCOM, "West Bengal", UNKNOWN, "data-only as of 2020"),
    ("405", "024", HFCL, "Punjab", NOT_OPERATIONAL, "merged with Airtel 2019"),
    ("405", "025", TATA, "Andhra Pradesh & Telangana", NOT_OPERATIONAL, "merged with Airtel 2019"),
    ("405", "026", TATA, "Assam", NOT_OPERATIONAL, "merged with Airtel 2019"),
    ("405", "027", TATA, "Bihar & Jharkhand", NOT_OPERATIONAL, "merged with Airtel 2019"),
    ("405", "028", TATA, "Chennai", NOT_OPERATIONAL, "merged with Airtel 2019"),
    ("405", "029", TATA, "Delhi & NCR", NOT_OPERATIONAL, "merged with Airtel 2019"),
    ("405", "030", TATA, "Gujarat", NOT_OPERATIONAL, "merged with Airtel 2019"),
    ("405", "031", TATA, "Haryana", NOT_OPERATIONAL, "merged with Airtel 2019"),
    ("405", "032", TATA, "Himachal Pradesh", NOT_OPERATIONAL, "merged with Airtel 2019"),
    ("405", "033", TATA, "Jammu & Kashmir", NOT_OPERATIONAL, "merged with Airtel 2019"),
    ("405", "034", TATA, "Karnataka", NOT_OPERATIONAL, "merged with Airtel 2019"),
    ("405", "035", TATA, "Kerala", NOT_OPERATIONAL, "merged with Airtel 2019"),
    ("405", "036", TATA, "Kolkata", NOT_OPERATIONAL, "merged with Airtel 2019"),
    ("405", "037", TATA, "Maharashtra & Goa", NOT_OPERATIONAL, "merged with Airtel 2019"),
    ("405", "038", TATA, "Madhya Pradesh", NOT_OPERATIONAL, "merged with Airtel 2019"),
    ("405", "039", TATA, "Mumbai", NOT_OPERATIONAL, "merged with Airtel 2019"),
    ("405", "041", TATA, "Odisha", NOT_OPERATIONAL, "merged with Airtel 2019"),
    ("405", "042", TATA, "Punjab", NOT_OPERATIONAL, "merged with Airtel 2019"),
    ("405", "043", TATA, "Rajasthan", NOT_OPERATIONAL, "merged with Airtel 2019"),
    ("405", "044", TATA, "Tamil Nadu (incl. Chennai)", NOT_OPERATIONAL, "merged with Airtel 2019"),
    ("405", "045", TATA, "Uttar Pradesh (East)", NOT_OPERATIONAL, "merged with Airtel 2019"),
    ("405", "046", TATA, "Uttar Pradesh (West) & Uttarakhand", NOT_OPERATIONAL, "merged with Airtel 2019"),
    ("405", "047", TATA, "West Bengal", NOT_OPERATIONAL, "merged with Airtel 2019"),
    ("405", "048", RAILWAYS, "All circles", OPERATIONAL, "GSM-R 900 (railway operations network)"),
    ("405", "51", AIRTEL, "West Bengal", OPERATIONAL, ""),
    ("405", "52", AIRTEL, "Bihar & Jharkhand", OPERATIONAL, ""),
    ("405", "53", AIRTEL, "Odisha", OPERATIONAL, ""),
    ("405", "54", AIRTEL, "Uttar Pradesh (East)", OPERATIONAL, ""),
    ("405", "55", AIRTEL, "Jammu & Kashmir", OPERATIONAL, ""),
    ("405", "56", AIRTEL, "Assam", OPERATIONAL, ""),
    ("405", "66", VI, "Uttar Pradesh (West)", NOT_OPERATIONAL, "former Vodafone"),
    ("405", "67", VI, "West Bengal", OPERATIONAL, "former Vodafone"),
    ("405", "70", VI, "", OPERATIONAL, "former Idea; circle not listed by source"),
    ("405", "750", VI, "Jammu & Kashmir", OPERATIONAL, "former Vodafone"),
    ("405", "751", VI, "Assam", OPERATIONAL, "former Vodafone"),
    ("405", "752", VI, "Bihar & Jharkhand", NOT_OPERATIONAL, "former Vodafone"),
    ("405", "753", VI, "Odisha", OPERATIONAL, "former Vodafone"),
    ("405", "754", VI, "Himachal Pradesh", NOT_OPERATIONAL, "former Vodafone"),
    ("405", "755", VI, "North East", OPERATIONAL, "former Vodafone"),
    ("405", "756", VI, "Madhya Pradesh & Chhattisgarh", NOT_OPERATIONAL, "former Vodafone"),
    ("405", "799", VI, "Mumbai", NOT_OPERATIONAL, "former Idea"),
    ("405", "800", AIRCEL, "Delhi & NCR", NOT_OPERATIONAL, "bankrupt 2018"),
    ("405", "801", AIRCEL, "Andhra Pradesh & Telangana", NOT_OPERATIONAL, "bankrupt 2018"),
    ("405", "802", AIRCEL, "Gujarat", NOT_OPERATIONAL, "bankrupt 2018"),
    ("405", "803", AIRCEL, "Karnataka", NOT_OPERATIONAL, "bankrupt 2018"),
    ("405", "804", AIRCEL, "Maharashtra & Goa", NOT_OPERATIONAL, "bankrupt 2018"),
    ("405", "805", AIRCEL, "Mumbai", NOT_OPERATIONAL, "bankrupt 2018"),
    ("405", "806", AIRCEL, "Rajasthan", NOT_OPERATIONAL, "bankrupt 2018"),
    ("405", "807", AIRCEL, "Haryana", NOT_OPERATIONAL, "bankrupt 2018"),
    ("405", "808", AIRCEL, "Madhya Pradesh", NOT_OPERATIONAL, "bankrupt 2018"),
    ("405", "809", AIRCEL, "Kerala", NOT_OPERATIONAL, "bankrupt 2018"),
    ("405", "810", AIRCEL, "Uttar Pradesh (East)", NOT_OPERATIONAL, "bankrupt 2018"),
    ("405", "811", AIRCEL, "Uttar Pradesh (West)", NOT_OPERATIONAL, "bankrupt 2018"),
    ("405", "812", AIRCEL, "Punjab", NOT_OPERATIONAL, "licence cancelled (2012 Supreme Court order)"),
    ("405", "813", UNINOR, "Haryana", NOT_OPERATIONAL, "licence cancelled 2012"),
    ("405", "814", UNINOR, "Himachal Pradesh", NOT_OPERATIONAL, "licence cancelled 2012"),
    ("405", "815", UNINOR, "Jammu & Kashmir", NOT_OPERATIONAL, "licence cancelled 2012"),
    ("405", "816", UNINOR, "Punjab", NOT_OPERATIONAL, "licence cancelled 2012"),
    ("405", "817", UNINOR, "Rajasthan", NOT_OPERATIONAL, "licence cancelled 2012"),
    ("405", "818", UNINOR, "Uttar Pradesh (West)", NOT_OPERATIONAL, "merged with Airtel 2018"),
    ("405", "819", UNINOR, "Andhra Pradesh & Telangana", NOT_OPERATIONAL, "merged with Airtel 2018"),
    ("405", "820", UNINOR, "Karnataka", NOT_OPERATIONAL, "shut down 2012"),
    ("405", "821", UNINOR, "Kerala", NOT_OPERATIONAL, "shut down 2012"),
    ("405", "822", UNINOR, "Kolkata", NOT_OPERATIONAL, "shut down 2013"),
    ("405", "824", VIDEOCON, "Assam", NOT_OPERATIONAL, "licence cancelled 2012"),
    ("405", "825", VIDEOCON, "Bihar", NOT_OPERATIONAL, "shut down 2016"),
    ("405", "826", VIDEOCON, "Delhi & NCR", NOT_OPERATIONAL, "licence cancelled 2012"),
    ("405", "827", VIDEOCON, "Gujarat", NOT_OPERATIONAL, "shut down 2016"),
    ("405", "828", VIDEOCON, "Haryana", NOT_OPERATIONAL, "shut down 2016"),
    ("405", "834", VIDEOCON, "Madhya Pradesh", NOT_OPERATIONAL, "shut down 2016"),
    ("405", "840", JIO, "West Bengal", OPERATIONAL, ""),
    ("405", "841", VIDEOCON, "Uttar Pradesh (East)", NOT_OPERATIONAL, "shut down 2016"),
    ("405", "842", VIDEOCON, "Uttar Pradesh (West)", NOT_OPERATIONAL, "shut down 2016"),
    ("405", "844", UNINOR, "Delhi & NCR", NOT_OPERATIONAL, "merged with Airtel 2018"),
    ("405", "845", VI, "", NOT_OPERATIONAL, "former Idea; circle not listed by source"),
    ("405", "846", VI, "", NOT_OPERATIONAL, "former Idea; circle not listed by source"),
    ("405", "847", VI, "Karnataka", NOT_OPERATIONAL, "former Idea"),
    ("405", "848", VI, "", NOT_OPERATIONAL, "former Idea; circle not listed by source"),
    ("405", "849", VI, "", NOT_OPERATIONAL, "former Idea; circle not listed by source"),
    ("405", "850", VI, "", NOT_OPERATIONAL, "former Idea; circle not listed by source"),
    ("405", "851", VI, "Punjab", NOT_OPERATIONAL, "former Idea"),
    ("405", "852", VI, "", NOT_OPERATIONAL, "former Idea; circle not listed by source"),
    ("405", "853", VI, "", NOT_OPERATIONAL, "former Idea; circle not listed by source"),
    ("405", "854", JIO, "Andhra Pradesh & Telangana", OPERATIONAL, ""),
    ("405", "855", JIO, "Assam", OPERATIONAL, ""),
    ("405", "856", JIO, "Bihar & Jharkhand", OPERATIONAL, ""),
    ("405", "857", JIO, "Gujarat", OPERATIONAL, ""),
    ("405", "858", JIO, "Haryana", OPERATIONAL, ""),
    ("405", "859", JIO, "Himachal Pradesh", OPERATIONAL,
     "source lists 'Jio Pradesh'; HP per other public MNC lists - verify"),
    ("405", "860", JIO, "Jammu & Kashmir", OPERATIONAL,
     "source page lists Mumbai; other public MNC lists give J&K (Mumbai is 405-874) - verify"),
    ("405", "861", JIO, "Karnataka", OPERATIONAL, ""),
    ("405", "862", JIO, "Kerala", OPERATIONAL, ""),
    ("405", "863", JIO, "Madhya Pradesh & Chhattisgarh", OPERATIONAL, ""),
    ("405", "864", JIO, "Maharashtra & Goa", OPERATIONAL, ""),
    ("405", "865", JIO, "North East", OPERATIONAL, ""),
    ("405", "866", JIO, "Odisha", OPERATIONAL, ""),
    ("405", "867", JIO, "Punjab", OPERATIONAL, ""),
    ("405", "868", JIO, "Rajasthan", OPERATIONAL, ""),
    ("405", "869", JIO, "Tamil Nadu", OPERATIONAL, ""),
    ("405", "870", JIO, "Uttar Pradesh (West)", OPERATIONAL, ""),
    ("405", "871", JIO, "Uttar Pradesh (East)", OPERATIONAL, ""),
    ("405", "872", JIO, "Delhi & NCR", OPERATIONAL, ""),
    ("405", "873", JIO, "Kolkata", OPERATIONAL, ""),
    ("405", "874", JIO, "Mumbai", OPERATIONAL, ""),
    ("405", "875", UNINOR, "Assam", NOT_OPERATIONAL, "merged with Airtel 2018"),
    ("405", "876", UNINOR, "Bihar & Jharkhand", NOT_OPERATIONAL, "merged with Airtel 2018"),
    ("405", "877", UNINOR, "North East", NOT_OPERATIONAL, "licence cancelled 2012"),
    ("405", "878", UNINOR, "Odisha", NOT_OPERATIONAL, "shut down 2013"),
    ("405", "879", UNINOR, "Uttar Pradesh (East)", NOT_OPERATIONAL, "merged with Airtel 2018"),
    ("405", "880", UNINOR, "West Bengal", NOT_OPERATIONAL, "shut down 2013"),
    ("405", "887", MTS, "Andhra Pradesh", NOT_OPERATIONAL, "merged with RCom 2017"),
    ("405", "888", MTS, "Assam", NOT_OPERATIONAL, "merged with RCom 2017"),
    ("405", "889", MTS, "Bihar", NOT_OPERATIONAL, "merged with RCom 2017"),
    ("405", "890", MTS, "Delhi & NCR", NOT_OPERATIONAL, "merged with RCom 2017"),
    ("405", "891", MTS, "Gujarat", NOT_OPERATIONAL, "merged with RCom 2017"),
    ("405", "892", MTS, "Haryana", NOT_OPERATIONAL, "merged with RCom 2017"),
    ("405", "893", MTS, "Himachal Pradesh", NOT_OPERATIONAL, "merged with RCom 2017"),
    ("405", "894", MTS, "Jammu & Kashmir", NOT_OPERATIONAL, "merged with RCom 2017"),
    ("405", "895", MTS, "Karnataka", NOT_OPERATIONAL, "merged with RCom 2017"),
    ("405", "896", MTS, "Kerala", NOT_OPERATIONAL, "merged with RCom 2017"),
    ("405", "897", MTS, "Kolkata", NOT_OPERATIONAL, "merged with RCom 2017"),
    ("405", "898", MTS, "Madhya Pradesh", NOT_OPERATIONAL, "merged with RCom 2017"),
    ("405", "899", MTS, "Maharashtra", NOT_OPERATIONAL, "merged with RCom 2017"),
    ("405", "900", MTS, "Mumbai", NOT_OPERATIONAL, "merged with RCom 2017"),
    ("405", "901", MTS, "North East", NOT_OPERATIONAL, "merged with RCom 2017"),
    ("405", "902", MTS, "Odisha", NOT_OPERATIONAL, "merged with RCom 2017"),
    ("405", "903", MTS, "Punjab", NOT_OPERATIONAL, "merged with RCom 2017"),
    ("405", "904", MTS, "Tamil Nadu", NOT_OPERATIONAL, "merged with RCom 2017"),
    ("405", "905", MTS, "Uttar Pradesh (East)", NOT_OPERATIONAL, "merged with RCom 2017"),
    ("405", "906", MTS, "Uttar Pradesh (West)", NOT_OPERATIONAL, "merged with RCom 2017"),
    ("405", "907", MTS, "West Bengal", NOT_OPERATIONAL, "merged with RCom 2017"),
    ("405", "908", VI, "Andhra Pradesh & Telangana", NOT_OPERATIONAL, "former Idea"),
    ("405", "909", VI, "Delhi & NCR", NOT_OPERATIONAL, "former Idea"),
    ("405", "910", VI, "Haryana", NOT_OPERATIONAL, "former Idea"),
    ("405", "911", VI, "Maharashtra & Goa", NOT_OPERATIONAL, "former Spice/Idea"),
    ("405", "925", UNINOR, "Tamil Nadu", NOT_OPERATIONAL, "shut down 2012"),
    ("405", "926", UNINOR, "Mumbai", NOT_OPERATIONAL, "shut down 2013"),
    ("405", "927", UNINOR, "Gujarat", NOT_OPERATIONAL, "merged with Airtel 2018"),
    ("405", "928", UNINOR, "Madhya Pradesh", NOT_OPERATIONAL, "licence cancelled 2012"),
    ("405", "929", UNINOR, "Maharashtra & Goa", NOT_OPERATIONAL, "merged with Airtel 2018"),
]


def _build() -> dict[str, MccMncRow]:
    table: dict[str, MccMncRow] = {}
    for mcc, mnc, operator, circle, status, note in _ROWS:
        key = f"{mcc}-{mnc}"
        if key in table:  # pragma: no cover - guards against copy/paste duplicates
            raise ValueError(f"duplicate MCC/MNC row {key}")
        table[key] = MccMncRow(operator=operator, circle=circle, status=status, note=note)
    return table


INDIA_MCCMNC: dict[str, MccMncRow] = _build()


def decode_mccmnc(mcc: str, mnc: str) -> Optional[dict[str, str]]:
    """
    Decode an Indian MCC/MNC pair.

    Returns a *copy* of the table row with ``mcc``/``mnc`` (as matched) added,
    or ``None`` when the pair is unknown.  Matching is exact first; a two-digit
    MNC is then retried zero-padded to three digits because some data sources
    strip leading zeros (e.g. ``"30"`` for ``"030"``).  Note that in MCC 405 a
    two-digit and a three-digit code can be *different* networks, so exact
    matches always win.
    """
    mcc_s = "".join(ch for ch in str(mcc or "") if ch.isdigit())
    mnc_s = "".join(ch for ch in str(mnc or "") if ch.isdigit())
    if not mcc_s or not mnc_s:
        return None
    candidates = [mnc_s]
    if len(mnc_s) == 2:
        candidates.append(mnc_s.zfill(3))
    elif len(mnc_s) == 1:
        candidates.extend([mnc_s.zfill(2), mnc_s.zfill(3)])
    for candidate in candidates:
        row = INDIA_MCCMNC.get(f"{mcc_s}-{candidate}")
        if row is not None:
            return {"mcc": mcc_s, "mnc": candidate, **row}
    return None
