# Legal, privacy and ethical boundaries

> This document explains the boundaries the engine enforces and the legal framework that motivates them.
> It is engineering guidance, **not legal advice**. Obtain counsel before deploying the tool in production,
> especially for commercial use.

## 1. What the engine does — and what it refuses to do

| Allowed (implemented) | Forbidden (never implemented, tested for absence) |
|---|---|
| Parsing / validating numbers offline with libphonenumber | Telecom subscriber databases, CDRs, HLR probes, SIM-swap or live status checks |
| Documented search APIs (Brave, SerpAPI, Serper, Tavily, legacy Google CSE) with `site:`/`filetype:` operators | Scraping search engines' HTML (DuckDuckGo, Google, Bing via `ddgs`, SearXNG engines) |
| Fetching public pages that a search engine surfaced, honouring robots.txt, size and content-type limits | Crawling, CAPTCHA solving, rate-limit evasion, TLS/browser fingerprint impersonation, proxies to bypass blocks |
| Documented phone-metadata APIs (Veriphone, NumVerify, AbstractAPI, Twilio line-type only) | Twilio `caller_name`, `sim_swap`, `identity_match`, `reassigned_number`, IPQS "leaked" flags, Truecaller/Eyecon private APIs |
| Public profile *pages* discovered through search; optional unauthenticated checks of public profile URLs (Maigret, with bypass features disabled) | Logging in, private APIs, "forgot password"/registration/OTP probes (Holehe, Ignorant), contact synchronisation |
| Documented public registry APIs (Indian Kanoon) and `site:` dorks on public registry pages | Submitting registry search forms, bypassing CAPTCHA on MCA21/GST/eCourts, Aadhaar/PAN/bank/voter lookups |
| Reporting **publicly co-listed** alternate numbers with source, URL, date, confidence, reason | Generating, brute-forcing, or *testing* candidate numbers; account-recovery hints |
| Recording that a *public article* mentions a breach as context | Querying breach corpora, paste sites, Telegram leak channels, dark-web indexes |
| Reverse image search on a public image URL through documented APIs (optional) | Facial recognition (PimEyes, FaceCheck, Clearview-style services) |

`tests/test_boundaries.py` greps the codebase for forbidden endpoints and keywords so a regression cannot slip in
unnoticed.

## 2. Indian legal framework (as of September 2026)

### Digital Personal Data Protection Act, 2023 (DPDP Act) and DPDP Rules, 2025

* The Act was notified on 11 August 2023. MeitY notified the **DPDP Rules, 2025 on 13 November 2025** with
  phased commencement (14 November 2025, 14 November 2026 and 14 May 2027 for different provisions).
  Sources: [Shardul Amarchand Mangaldas summary](https://www.amsshardul.com/insight/enforcement-of-the-dpdp-act-and-notification-of-the-dpdp-rules/),
  [Wikipedia](https://en.wikipedia.org/wiki/Digital_Personal_Data_Protection_Rules,_2025).
* A phone number that identifies an individual is **personal data**: *"'personal data' means any data about an
  individual who is identifiable by or in relation to such data"* (s.2(t)). Running searches, storing findings and
  generating reports is **processing** (s.2(x): collection, recording, organisation, storage, retrieval, use,
  combination, indexing, disclosure …).
* **Publicly available data exemption** — Section 3(c) says the Act shall *"not apply to … (ii) personal data that is
  made or caused to be made publicly available by — (A) the Data Principal to whom such personal data relates; or
  (B) any other person who is under an obligation under any law for the time being in force in India to make such
  personal data publicly available."* The statutory illustration is an individual blogging their views on social
  media. (Text extracted from the Gazette PDF published by PRS India.)
  * This exemption is narrower than "anything on the internet": data made public by a *third party without a legal
    obligation* (a classified ad posted by someone else, a leaked list, a scraped directory) is **not** covered.
  * That is exactly why the engine distinguishes DIRECT (the person/business published the number themselves on
    their own page, listing or filing), INDIRECT and INFERRED associations, and why it keeps source, date and
    quality for every finding.
* Penalties under Section 33 / the Schedule run up to ₹250 crore for security-safeguard failures and up to ₹50 crore
  for other breaches. Treat every investigation as processing that needs a **lawful purpose**, **purpose
  limitation**, **data minimisation**, **retention limits** and **security safeguards** even where an exemption may
  apply.

### Information Technology Act, 2000

* s.43 / s.66 — unauthorised access to a computer resource, downloading data without permission, etc. Bypassing
  authentication, CAPTCHAs or technical access controls would engage these sections; the engine never does.
* s.66C (identity theft), s.66D (cheating by personation), s.66E (privacy violation — images of private areas),
  s.72 / s.72A (breach of confidentiality, disclosure in breach of lawful contract).

### Bharatiya Nyaya Sanhita, 2023

* s.78 (stalking) covers monitoring a woman's use of the internet/e-mail; using this tool to follow, monitor or
  contact a person is out of scope and potentially criminal. The tool must never be used for harassment.

### Telecom rules

* TRAI's TCCCPR 2018 (and 2024–25 amendments) govern commercial communication and the 140/160 numbering series;
  the engine recognises those series and labels them as telemarketing/transactional allocations.
* TRAI/DoT citizen services (Sanchar Saathi, TAFCOP, Chakshu) are authenticated citizen portals; they are **not**
  used.
* Mobile Number Portability is nationwide; prefix-based operator/circle hints are labelled "original allocation".

### Contract / terms of service

* Directory sites (Justdial, IndiaMART, TradeIndia, Sulekha …) forbid scraping and automated queries in their terms.
  The engine therefore never fetches their search forms and only follows individual result pages surfaced by a search
  API when robots.txt allows it.
* Search-API terms (notably Brave's) restrict building databases of results. The persistent evidence store keeps
  URLs, titles and *our own* page excerpts, not provider snippets, unless `OSINT_STORE_PROVIDER_SNIPPETS=true`.
* Google Places, Twilio, Veriphone, SerpAPI, Tavily etc. all prohibit unlawful, harassing or privacy-violating use;
  several require you to be the data controller with a privacy policy.

### GDPR / other jurisdictions

If a data subject is in the EU/UK the GDPR applies to you as controller; "publicly available" is **not** an
exemption under GDPR. Similar caveats exist elsewhere. Use the tool only where you have a lawful basis.

## 3. Operating an authorised investigation

Record, for every case (the `--case` and `--authorization` options store this in the report metadata):

1. **Who authorised** the investigation, **why** (purpose), and the legal basis relied on.
2. **Scope**: the number(s) in scope; nothing else is expanded except public co-listed numbers of the same entity.
3. **Retention**: delete the evidence store, snapshots and reports when the purpose is fulfilled
   (`data/` and `output/` directories; `python main.py history` lists stored investigations).
4. **Access control**: reports contain personal data; store them encrypted and share on a need-to-know basis.
5. **Accuracy**: never act on a POSSIBLE/WEAK/UNVERIFIED association; verify DIRECT sources manually via the URLs.
6. **Data-subject rights**: be prepared to disclose and delete on request.

## 4. Ethical guard-rails built into the reports

* Every report starts with the disclaimer: *"This report contains information discovered from publicly accessible or
  authorized sources. Public-source associations are not proof of identity. Information may be outdated,
  inaccurate, duplicated, or associated with another person who previously used the number."*
* Every claim is labelled **CONFIRMED PUBLIC FACT** (only FACT-level, DIRECT evidence from A/B sources on multiple
  independent domains) or **ANALYTICAL INFERENCE**.
* Contradictory identities are shown as separate candidates; the engine never merges them silently.
* Addresses are dated and never asserted as "current".
* Confidence percentages are transparent point ledgers, explicitly described as estimates.
