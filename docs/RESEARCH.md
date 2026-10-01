# Phase 1 research: tools, APIs, Indian sources, boundaries

Research was performed on 2026-09-07/08 against the live web (official docs, repositories, pricing pages).
Where a claim could not be verified online it is marked *(unverified)*. Re-check before production use.

## 1. Open-source OSINT projects

| Project | What it does | Maintained? | License | Verdict |
|---|---|---|---|---|
| **PhoneInfoga** (sundowndev) | Go CLI/REST: `local` (libphonenumber 2022 metadata), `numverify` (apilayer), `googlesearch` (builds dork URLs, fetches nothing), `googlecse`, `ovh` (EU only). | README (Jan 2026): "stable but unmaintained… could be archived at any time"; last release v2.11.0 (Feb 2024); Homebrew formula deprecated Feb 2026. | GPL-3.0 | **Optional sidecar wrapper only** (`providers/phone/phoneinfoga.py` talks to `phoneinfoga serve --no-client` REST API; low confidence). Everything it does for +91 is reproduced natively by `phonenumbers` + our dork generator. GPL code never linked in-process. |
| **Sherlock** | Username enumeration over ~480 sites via public profile URLs. | Last release Sep 2025, 300+ open issues; library API undocumented, `SitesInformation()` makes network calls at construction. | MIT | **Excluded** in favour of Maigret. |
| **Maigret** | Username enumeration over ~4,200 sites with tag filtering, async library API (`maigret.search`). | Active (multiple 2026 releases). | MIT | **Wrapped, opt-in** with hard-coded filters: sites needing activation (guest tokens), protection (TLS fingerprinting / Cloudflare) or similar-search are dropped; cookies/bypass/proxy options never used. |
| **SpiderFoot** | Modular OSINT automation. Phone modules: `sfp_phone` (libphonenumber), numverify/abstract/twilio wrappers; no web search for numbers. Default presets include HIBP/IntelX/Dehashed/LeakIX breach modules. | Dormant since Nov 2023; pinned cryptography 3.4.8 etc.; docs site gone. | MIT | **Excluded** as dependency; event taxonomy used as inspiration. |
| **theHarvester** | Domain-centric e-mail/host harvesting; includes breach sources (HIBP, HudsonRock). | Active. | GPL-2.0 | **Excluded** (domain-centric, breach sources, GPL). |
| **Holehe / Ignorant** | Check whether an e-mail / phone is registered on services **via registration, login and password-recovery endpoints** (Instagram private API with hard-coded signature key, Snapchat validate_phone_number, Amazon sign-in). | Active. | GPL-3.0 | **Excluded — forbidden techniques** (account-recovery / ownership testing / private APIs). |
| **Truecaller / Eyecon** | Caller-ID databases. | — | proprietary | **Excluded**: no public lookup API; unofficial libraries require account login + OTP and drive the private app API; ToS forbid it. |
| **libphonenumber / `phonenumbers`** | Parsing, validation, number type, formatting, carrier/geocoder/timezone metadata. | 9.0.38 (Aug 2026), bi-weekly releases; Indian metadata refreshed 2026. | Apache-2.0 | **Reused** as mandatory first stage. Carrier = *original allocation* only (`is_mobile_number_portable_region("IN")` is True; ~14.5 M porting requests/month); geocoder gives only "India" for mobiles. |

## 2. Search APIs (verified against official pages)

* **Brave Search API** — `GET https://api.search.brave.com/res/v1/web/search`, `X-Subscription-Token`; quotes, `-term`, `site:`, `filetype:` inside `q`; `count≤20`, `offset 0–9`, `country=IN`, `search_lang`, `freshness`, `extra_snippets`. $5/1k, $5 free credit monthly, 50 QPS on the Search plan. ToS (1 Sep 2026): no storing/caching a database of results beyond transient use; no AI training; prohibited-use list includes "surveillance". → Primary provider, with snippet-persistence off by default.
* **SerpAPI** — `GET https://serpapi.com/search.json`, engines google/bing/duckduckgo/yandex/google_lens/google_reverse_image; free 250/month at 50/h; Starter $25/1k; Production $150 adds "U.S. Legal Shield"; data retained 31 days. Official client `serpapi` 1.1.0 (`google-search-results` deprecated).
* **Serper.dev** — `POST https://google.serper.dev/search`, `X-API-KEY`; 2,500 free queries; $50/50k → $0.30/1k at scale; credits expire in 6 months; docs behind login; no indemnity.
* **Tavily** — `POST https://api.tavily.com/search`, Bearer; `exact_match`, `include_domains`(≤300), `country`; 1,000 free credits/month (basic 1 credit, advanced 2); ToS §8.2 forbids government ID numbers in inputs.
* **Google Custom Search JSON API** — "closed to new customers… until January 1, 2027 to transition"; existing customers 100/day free then $5/1k up to 10k/day. → deprecated provider.
* **Bing Web Search API** — retired 11 Aug 2025 (Microsoft Lifecycle); "Grounding with Bing Search" gives no raw results and needs paid Azure. → excluded.
* **DuckDuckGo** — only an Instant-Answer API; `ddgs` (v9.16) scrapes `html.duckduckgo.com`, Google, Bing, Brave HTML ("for educational purposes only"); **SearXNG** engines also scrape Google/Bing. → excluded (no-scraping boundary).
* Others: **Exa** ($7/1k, no operators, include/exclude domains), **You.com** ($5/1k, operators supported, $100 signup credit), **Vertex AI / Gemini grounding** (no raw result lists). Not implemented; easy to add.

## 3. Phone-lookup APIs

* **Twilio Lookup v2** — `GET https://lookups.twilio.com/v2/PhoneNumbers/{E.164}?Fields=line_type_intelligence` ($0.008); validation-only free. `caller_name` is US-only; `sim_swap`, `identity_match`, `reassigned_number`, `pre_fill`, `phone_number_quality_score`, `sms_pumping_risk`, `line_status` are consent-gated / fraud / network probes → blocked by a code guard.
* **Veriphone v3** — `GET https://api.veriphone.io/v3/verify?phone=`, Bearer; 1,000 credits/month free; `mode=current` (ported carrier, 10 credits) disabled by default.
* **NumVerify** (apilayer marketplace) — `GET https://api.apilayer.com/number_verification/validate`, `apikey` header; free 100/month; $14.99/5k.
* **AbstractAPI** — `GET https://phonevalidation.abstractapi.com/v1/?api_key=&phone=`; 100 free; 1 rps.
* **IPQualityScore** (fraud scoring, "leaked" flag), **Telesign PhoneID** (sales pricing) → excluded.
* **Official Indian numbering data**: DoT National Numbering Plan 2003 (PDF), ITU-T E.212 MNC list; TRAI 140/160 series for telemarketing/transactional; MNP nationwide since 2015 (intra-circle since 2011). Sanchar Saathi / TAFCOP / Chakshu are authenticated citizen portals → not used.

## 4. Indian public sources (partly from direct checks; registry research agent was cut short)

* **Business directories**: Justdial terms prohibit "data mining, scraping, crawling… automated queries" and compiling listings; IndiaMART terms prohibit robots/spiders/scrapers. → search-mediated `site:` dorks + robots-permitted result pages only. Google Places API (New) Text Search **accepts E.164 phone numbers** (`regionCode=IN`; Enterprise SKU) — documented, so implemented.
* **Registries**: MCA21 (company/director master data; CAPTCHA; name/CIN/DIN search), GST (GSTIN/PAN search, CAPTCHA), eCourts (CAPTCHA), Udyam/FSSAI (ID-based verification), state RERA portals (agent/project registrations often publish phone numbers on public pages), CPPP/GeM tenders (public PDFs with contact numbers), professional registers (ICAI, ICSI, NMC, Bar Councils), SEBI/IRDAI lists. None offer phone-number search; all are reached indirectly through `site:` dorks. Indian Kanoon offers a documented paid API (`Authorization: Token`) for full-text judgment search.
* **Documents**: `filetype:` operators on Brave/SerpAPI/Serper/CSE; Tavily lacks filetype support; safe fetch with size/type limits; pypdf/python-docx/openpyxl parsing.
* **Reverse image**: TinEye REST API (paid bundles; docs behind JS/login — request shape taken from official client libraries, *unverified*), Google Lens via SerpAPI. Bing Visual Search retired with the Bing APIs. Facial-recognition services excluded.

## 5. Legal framework (India)

DPDP Act 2023 (Rules notified 13 Nov 2025; phased commencement to May 2027) — phone numbers are personal data;
Section 3(c)(ii) exempts data made public by the data principal or under a legal obligation (narrow); IT Act
2000 ss.43/66/66C/72A; BNS s.78 (stalking); TRAI TCCCPR. Details and operating guidance: `docs/LEGAL_AND_PRIVACY.md`.

## 6. Technical limitations identified

Partial search coverage; login-walled social platforms; heuristic Indian name/address extraction; unreliable
page dates; MNP and number recycling; small free API quotas; provider shutdown risk (Bing, Google CSE) → the
provider abstraction keeps at least four independent search providers.

## 7. Reuse decisions

Reused: `phonenumbers`; Maigret (wrapped, filtered, opt-in); PhoneInfoga (optional REST sidecar). Built ourselves:
normalisation & variants, adaptive query strategy with information gain, extractors, entity resolution,
contradiction detection, transparent scoring, evidence graph, reports, cache/evidence store, CLI and UI.
