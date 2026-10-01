"""
Person-name extraction with Indian-name-aware heuristics (no heavy NLP).

Precision is favoured over recall: a wrong name creates a false candidate
identity, a missed name only reduces recall.  Every candidate carries a
confidence and the reason it was accepted.
"""

from __future__ import annotations

import re

from extractors.business_extractor import is_business_name
from extractors.text_utils import NameCandidate, normalise_name

HONORIFICS = r"(?:Mr|Mrs|Ms|Miss|Dr|Shri|Smt|Sri|Er|Adv|CA|Prof|Md|Mohd|Sh|Km|Kum|Sushri)\.?"
_TITLE_WORD = r"[A-Z][a-z]{1,20}(?:'[A-Za-z]+)?"
_NAME_SEQ = rf"{_TITLE_WORD}(?:[ \t]+{_TITLE_WORD}){{0,3}}"  # never crosses a line break

_LABELS = [
    "name", "contact person", "contact", "owner", "proprietor", "director", "managing director", "partner",
    "founder", "co-founder", "posted by", "seller", "listed by", "authorised signatory", "authorized signatory",
    "agent", "advocate", "dealer", "listed by", "by", "consultant", "manager", "propreitor", "prop",
]
_LABEL_RE = re.compile(
    r"(?i)\b(?P<label>" + "|".join(re.escape(l) for l in _LABELS) + r")\s*[:\-–]\s*(?:" + HONORIFICS + r"\s*)?"
    r"(?P<name>" + _NAME_SEQ + ")"
)
_HONORIFIC_RE = re.compile(r"\b" + HONORIFICS + r"\s+(?P<name>" + _NAME_SEQ + ")")
_RELATION_RE = re.compile(r"(?P<name>" + _NAME_SEQ + r")\s+(?:s/o|d/o|w/o|S/O|D/O|W/O|son of|daughter of|wife of)\s+"
                          r"(?P<parent>" + _NAME_SEQ + ")")
_PLAIN_RE = re.compile(r"\b(?P<name>" + _TITLE_WORD + r"(?:[ \t]+" + _TITLE_WORD + r"){1,2})\b")

SURNAMES: frozenset[str] = frozenset(s.lower() for s in """
Sharma Verma Kumar Singh Gupta Patel Reddy Nair Iyer Khan Das Roy Mishra Yadav Jain Agarwal Agrawal Mehta Shah Rao
Naidu Pillai Menon Choudhary Chaudhary Chauhan Rajput Bhat Joshi Kulkarni Deshpande Pandey Tiwari Dubey Saxena
Srivastava Sinha Malhotra Kapoor Chopra Bhatia Sethi Arora Khanna Bose Banerjee Chatterjee Mukherjee Ghosh Sen Dutta
Mondal Halder Gowda Hegde Shetty Kamath Prabhu Naik Sawant Patil Pawar Jadhav Shinde Gaikwad Bhosale Kadam Ansari
Qureshi Siddiqui Sheikh Syed Mirza Pathan Fernandes D'Souza Rodrigues Thomas George Varghese Mathew Kurian Philip
Xavier Gill Sandhu Dhillon Sidhu Brar Bajwa Kaur Grewal Randhawa Sodhi Bedi Chadha Anand Bhardwaj Trivedi Dwivedi
Chaturvedi Upadhyay Tripathi Shukla Ojha Jha Thakur Rathore Solanki Meena Bishnoi Saini Nagar Prajapati Suthar Soni
Goyal Bansal Mittal Garg Singhal Kansal Aggarwal Jindal Tayal Goel Bhalla Talwar Wadhwa Sachdeva Tandon Seth Mahajan
Sood Puri Vohra Ahluwalia Chawla Dhawan Kohli Nanda Bhandari Rawat Negi Bisht Rana Pant Pradhan Tamang Lama Rai
Gurung Barman Debnath Sarkar Saha Paul Biswas Karmakar Mahato Munda Oraon Tirkey Ekka Toppo Kujur Minz Hembram Soren
Murmu Tudu Hansda Marandi Kisku Chowdhury Barua Bhuyan Gogoi Saikia Bora Hazarika Kalita Deka Baruah Phukan Boro
Basumatary Brahma Sarma Devi Bhattacharya Chakraborty Ganguly Majumdar Sengupta Dasgupta Bhowmik Kar Nath Pal Mallick
Sardar Naskar Khatun Bibi Molla Laskar Talukdar Ahmed Ali Hussain Rahman Islam Uddin Akhtar Begum Bano Fatima Khatoon
Parveen Rizvi Naqvi Zaidi Abbasi Hashmi Farooqui Usmani Kazmi Jafri Baig Beg Lal Prasad Ram Mandal Mahto Sahu Sahoo
Behera Mohanty Panda Nayak Swain Jena Dash Mishra Rout Parida Samal Pattnaik Choudhury Mohapatra Padhi Reddy Rao
Raju Naidu Chowdary Varma Kumari Krishnan Raman Subramanian Venkatesan Murugan Rajan Sundaram Iyengar Srinivasan
Ramaswamy Natarajan Ganesan Balaji Kannan Pillai Kurup Panicker Warrier Namboothiri Nambiar Menon Nair Mathai Cherian
Jacob Abraham John Joseph Kutty Bhatt Desai Trivedi Modi Parikh Vyas Pandya Dave Rawal Thakkar Chauhan Solanki Rathod
Jadeja Gohil Parmar Vaghela Makwana Chavda Zala Sisodia Bhadoria Tomar Parihar Kushwaha Lodhi Maurya Kashyap Nishad
Sahni Bagga Marwah Bhasin Sarin Kakkar Suri Wahi Duggal Oberoi Rekhi Bindra Batra Luthra Kalra Uppal Mehra Kapur
Pahwa Sabharwal Gulati Madan Bajaj Bhagat Chandra Dayal Prakash Narayan Mohan Ranjan Kishore Nandan Bhushan Shankar
Kant Mani Swamy Acharya Bhattacharjee Roychowdhury Chakravarty Lahiri Sanyal Mitra Guha Basu Bagchi Tagore Deb Dey
Nag Saha Sur Seal Dhar Kundu Maity Samanta Jana Bera Manna Pramanik Adhikari Shrestha Karki Thapa Chettri Limbu Subba
""".split())

_STOPWORDS = frozenset(w.lower() for w in """
The And For With From India Indian Contact Phone Mobile Email Address Office Home About Services Service Company
Limited Private Ltd Pvt Enterprises Traders Trading Industries Solutions Technologies Systems Consultancy Associates
Agency Agencies Stores Store Shop Market Road Street Nagar Colony Sector Block Floor Tower Plaza Complex Building
Near Opposite Behind Main Cross Lane Marg Chowk Bazar Bazaar City Town District State Pin Pincode January February
March April May June July August September October November December Monday Tuesday Wednesday Thursday Friday
Saturday Sunday Call Now Whatsapp Click Here View More Details Best Top New Old Free Price Rate Sale Rent Wanted
Delhi Mumbai Bangalore Bengaluru Chennai Kolkata Hyderabad Pune Lucknow Jaipur Ahmedabad Surat Noida Gurgaon
Gurugram Chandigarh Indore Bhopal Nagpur Patna Kochi Coimbatore Thane Uttar Pradesh Madhya Maharashtra Karnataka
Tamil Nadu Kerala Gujarat Rajasthan Punjab Haryana Bihar Bengal Odisha Telangana Andhra Assam Goa Jharkhand
Hospital Clinic School College University Institute Academy Restaurant Hotel Cafe Bank Post Government Public
Sales Marketing Support Customer Care Helpline Toll Enquiry Inquiry Order Book Booking Register Registration Login
Terms Privacy Policy Copyright Rights Reserved Powered Website Web Site Online Page Home Profile User Member
Verified Trusted Rating Reviews Review Listing Listed Posted Updated Published Dated Report Tender Notice Bid
Gomti Vikas Rajendra Nehru Gandhi Ambedkar Shivaji Subhash Netaji Mahatma Indira Rajiv Lal Bahadur Model Civil
Lines Cantt Park Garden Vihar Enclave Extension Phase Industrial Area Estate Zone Ward Village Tehsil Taluk Mandal
Us Our Your Their His Her Its Khand Puram Pur Ganj Gunj Marg Path Road High Court Judgment Order Petition Respondent
Petitioner Appellant Applicant Witness Accused Complainant Prosecution Defence Hon Honourable Justice Sri Sree Om
""".split())

_BUSINESS_HINT = re.compile(
    r"\b(traders|enterprises|pvt|ltd|limited|llp|industries|solutions|technologies|services|agency|agencies|"
    r"stores?|associates|consultants?|consultancy|hospital|clinic|school|academy|institute|college|restaurant|"
    r"hotel|motors|builders|developers|realty|properties|textiles|garments|jewellers|electricals|electronics|"
    r"hardware|agro|foods|dairy|exports|logistics|transport|travels|tours|studio|events|foundation|trust|society|"
    r"finance|capital|bank|mart|emporium|bazaar|packers|movers|classes|coaching|diagnostics|pharmacy)\b", re.I)


def is_generic_name(name: str) -> bool:
    toks = normalise_name(name).split()
    if len(toks) < 2:
        return True
    if all(t in SURNAMES for t in toks) and len(toks) == 2 and toks[0] in {"kumar", "singh", "lal", "ram", "devi"}:
        return True
    return False


def _acceptable(name: str) -> bool:
    toks = name.split()
    if not 2 <= len(toks) <= 4:
        return False
    if any(t.lower() in _STOPWORDS for t in toks):
        return False
    if _BUSINESS_HINT.search(name) or is_business_name(name):
        return False
    if any(len(t) < 2 for t in toks):
        return False
    if name.isupper():
        return False
    return True


def _looks_indian(name: str) -> bool:
    return any(t.lower() in SURNAMES for t in name.split())


def _strip_trailing_junk(name: str) -> str:
    toks = name.split()
    while toks and toks[-1].lower() in _STOPWORDS:
        toks.pop()
    while toks and toks[0].lower() in _STOPWORDS:
        toks.pop(0)
    return " ".join(toks)


def extract_person_names(text: str, hints: dict | None = None) -> list[NameCandidate]:
    """Return person-name candidates with confidence >= 0.35, deduplicated by normalised name (best kept)."""
    if not text:
        return []
    text = text[:200_000]
    found: dict[str, NameCandidate] = {}

    def add(name: str, conf: float, start: int, end: int, reason: str) -> None:
        name = _strip_trailing_junk(name.strip())
        if not name or not _acceptable(name):
            return
        key = normalise_name(name)
        if not key or is_generic_name(name) and conf < 0.8:
            return
        prev = found.get(key)
        if prev is None or conf > prev.confidence:
            found[key] = NameCandidate(name=name, confidence=round(conf, 2), start=start, end=end, reason=reason)

    for m in _LABEL_RE.finditer(text):
        label = m.group("label").lower()
        conf = 0.9 if label in ("name", "contact person", "owner", "proprietor", "director", "managing director",
                                "partner", "founder", "co-founder", "authorised signatory", "authorized signatory") \
            else 0.8
        add(m.group("name"), conf, m.start("name"), m.end("name"), f"labelled:{label}")
    for m in _RELATION_RE.finditer(text):
        add(m.group("name"), 0.85, m.start("name"), m.end("name"), "relation:s/o-d/o-w/o")
        add(m.group("parent"), 0.6, m.start("parent"), m.end("parent"), "relation:parent-name")
    for m in _HONORIFIC_RE.finditer(text):
        add(m.group("name"), 0.85, m.start("name"), m.end("name"), "honorific")
    for m in _PLAIN_RE.finditer(text):
        name = m.group("name")
        # Precision over recall: unlabelled Title-Case phrases are only accepted when a token is a
        # known Indian surname.  Plain Title-Case ("Drip Irrigation", "High Court") is NOT a name.
        if _looks_indian(name):
            add(name, 0.6, m.start("name"), m.end("name"), "surname-list")
    for h in (hints or {}).get("known_names", []):
        i = text.lower().find(str(h).lower())
        if i >= 0:
            add(str(h), 0.7, i, i + len(str(h)), "hint")
    return sorted(found.values(), key=lambda c: (-c.confidence, c.start))
