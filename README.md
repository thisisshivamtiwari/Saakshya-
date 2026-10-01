<div align="center">

# Saakshya · साक्ष्य

### Public-source phone intelligence for India. Evidence first. Associations, not accusations.

<a href="docs/assets/saakshya-pipeline.svg">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/saakshya-pipeline-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="docs/assets/saakshya-pipeline-light.svg">
  <img src="docs/assets/saakshya-pipeline.svg" alt="Saakshya pipeline: twelve stages from a normalised Indian phone number to an evidence-backed report" width="100%">
</picture>
</a>

<sub>The diagram follows your day or night theme. Download <a href="docs/assets/saakshya-pipeline.svg"><code>saakshya-pipeline.svg</code></a> and open it in a browser to hover each stage and flip the Day / Night switch. It contains no JavaScript.</sub>

`Python 3.11+` · `178 offline tests` · `MIT` · `no scraping` · `no breach data` · `no logins`

</div>

---

> **Notice.** This report contains information discovered from publicly accessible or authorized sources.
> Public-source associations are not proof of identity. Information may be outdated, inaccurate, duplicated, or
> associated with another person who previously used the number.

*Saakshya* (साक्ष्य) is the Hindi and Sanskrit word for **evidence**. That one word is the whole design.

## The problem in one paragraph

Type an Indian phone number into a search engine and you get a mess: a Justdial listing from 2019, a PDF tender,
a classified ad for a second-hand car, a forum post saying "wrong number", a LinkedIn page that may or may not be
the same person. A human investigator can make sense of that pile, slowly. Most "phone lookup" tools cannot. They
either return a carrier name that portability made meaningless years ago, or they hand you a single confident name
with no explanation, often pulled from sources nobody should be touching.

Both failures are dangerous. In India a mobile number is routinely **recycled**, **shared** by a family, **listed**
by an employee, or **posted** by someone else entirely. A tool that says "this number belongs to X" without
showing why is not intelligence. It is a rumour with a user interface.

## What Saakshya does differently

Saakshya behaves like a careful investigator rather than a lookup box. Give it one number you are authorised to
research and it runs a staged investigation across lawful public sources, then tells you three things for every
single claim: **where it came from, when, and how much to trust it.**

| A typical lookup script | Saakshya |
|---|---|
| Searches once and prints links | Plans staged queries, measures the information gain of each, and stops when results repeat |
| Says "belongs to Rahul Sharma" | Says "appears with the name Rohan Verma on 8 independent public sources, here they are" |
| Merges everything into one profile | Keeps conflicting names as **separate candidates** and writes the contradiction down |
| Reports a carrier as if it were current | Labels carrier data as *original allocation*, because portability broke prefixes |
| Hides how the score was made | Shows a point ledger: +40 exact match, +25 same name on two domains, -30 conflicting name |
| Treats any website as truth | Grades every source A (official) to E (unknown) |
| Guesses or "finds" other numbers | Reports only numbers **publicly co-listed** on the same page, with the URL |
| Uses whatever data it can reach | Refuses breach data, logins, OTP probes, private APIs and scraping, and tests enforce it |

## Five ideas the engine is built on

**1. No conclusion without evidence.** The atomic unit is a `Finding`: a value, the exact text around it, the
source URL, the source grade, the publication date when known, and an extraction confidence. Entities, scores and
reports are all assembled from findings. Nothing else is allowed to exist.

**2. Three strengths of association, never blurred.**
`DIRECT` means the number is literally on the page next to the claim. `INDIRECT` means the number is on the page
but elsewhere. `INFERRED` means the number is not there at all and the link is a correlation. An inferred link is
never silently upgraded.

**3. Disagreement is data.** If a 2019 classified ad says *Amit Kumar, Delhi* and a 2024 tender says *Rohan Verma,
Lucknow*, Saakshya does not pick a winner. It creates two candidates, records a `NAME_CONFLICT` and a
`TEMPORAL_CHANGE`, and tells you the number's public association changed over time. It does not claim to know why.

**4. Search like an investigator, not a crawler.** Queries run in stages: exact number first, then documents,
profiles, businesses, registries and classifieds, then the names, e-mails and usernames those results revealed.
Every query is scored by how many new sources it produced. Branches that only return what is already known are
cut. A depth setting bounds the total cost.

**5. The boundary is part of the product.** Saakshya only reads what is public and lawfully reachable:
documented APIs, search results, and pages that robots.txt permits. This is not a limitation bolted on at the
end. It is why the output can be defended, repeated and shown to someone else.

## See it work in 30 seconds, with no API keys

The repository ships a fully fictional scenario (22 synthetic pages on `.example` hosts) so you can watch the
whole pipeline run offline.

```bash
git clone https://github.com/thisisshivamtiwari/Saakshya-.git && cd Saakshya-
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py investigate --phone "+91 98765 43210" --offline
```

```
  ✓ normalize        +91******3210 (mobile), 13 search variants
  ✓ telecom          14 telecom records from 1 provider(s)
  ✓ search           10 sources, 43 findings, 14 leads from 4 queries
  ✓ documents        2 documents (2 parsed)
  ✓ social           4 public profile references
  ✓ business         4 public business references
  ✓ registries       3 public registry / court / tender sources
  ✓ classifieds      3 classified / marketplace listings
  ✓ page_fetch       9 pages fetched, 1 blocked by robots.txt, 42 new findings
  ✓ lead_expansion   3 leads investigated over 1 round(s)
  ✓ correlation      4 candidate entities, 6 contradictions, 2 co-listed numbers
  ✓ scoring          top candidate 'Rohan Verma' 100% (STRONG_MATCH)

  Candidate identity            Rohan Verma
  Confidence                    100% (STRONG_MATCH) — analytical estimate
  Possible location             Lucknow, Uttar Pradesh
  Candidates / contradictions   4 / 6
  Amit Kumar        person   25%   CONTRADICTORY   (2019 classified, Delhi)
```

Read that output closely, because it shows the character of the tool:

* One page was **not fetched** because its robots.txt said no. The engine obeyed and said so.
* The top candidate scores 100 points and is still only a `STRONG_MATCH`, not a `FACT`, because another name is
  publicly attached to the same number. The label is withheld on purpose.
* The older Delhi association is kept, scored low, and marked `CONTRADICTORY` instead of being discarded.
* The office number `+91 91234 56780` is reported because a public contact page lists both numbers together.

The complete generated report is in [docs/example_report/](docs/example_report/) as Markdown, HTML, JSON and CSV.

## What you get at the end

A report an investigator can verify line by line, in this order: disclaimer, investigation metadata (providers
used, stages, case reference, who authorised it), the normalised number, telecom facts, executive summary,
candidate identities with *why linked* and the score ledger, names, e-mails, usernames, social profiles,
businesses, dated addresses and locations, public alternate numbers, documents, timeline, evidence graph,
contradictions, confidence scores, source quality, the full source list, every search query that was run,
limitations and a timestamp.

Every claim carries one of two labels: **CONFIRMED PUBLIC FACT** or **ANALYTICAL INFERENCE**.

Formats: `report.html`, `report.md`, `report.json` (schema 1.0), `csv/*.csv`, optional `report.pdf`, plus a
Streamlit workstation with tabs for each section.

## How confidence is calculated

There is no black box. Each candidate gets a ledger, shown in the report with the findings behind every line.

```
+40 exact phone match          +25 same name on two or more domains   +15 same business
+10 same location              +10 same e-mail                        +10 same username
+10 three or more independent sources    +10 official or primary source    +5 direct association
-30 contradictory location     -30 contradictory name                 -50 evidence it belongs to someone else
-15 only low-grade sources     -20 inferred only                      -10 only stale evidence (over 3 years)
```

The percentage is the clamped total. `FACT` requires an A or B grade source that displays the number, at least
two independent domains, and no contradiction. Everything else is `STRONG_MATCH`, `POSSIBLE_MATCH`,
`WEAK_ASSOCIATION`, `UNVERIFIED` or `CONTRADICTORY`. The score is always described as an analytical estimate.

Source grades: **A** official or primary · **B** reputable secondary · **C** established directory ·
**D** user-generated · **E** unknown.

## What Saakshya will never do

| Never | Why |
|---|---|
| Query breach dumps, paste sites or leak channels | Stolen data is not public data |
| Log in, call private APIs, or scrape authenticated pages | Unauthorised access |
| Probe "forgot password", registration or OTP flows | That is account enumeration, which is why Holehe and Ignorant are excluded |
| Use Truecaller-style private caller-ID APIs | No lawful public API exists |
| Touch subscriber records, call records, SIM status or location | Restricted telecom data |
| Look up Aadhaar, PAN, bank or voter data | Restricted identity data |
| Generate, guess or test alternate numbers | Only publicly co-listed numbers are reported |
| Scrape search engines or directories | Only documented APIs and robots-permitted pages |
| Run facial recognition | Out of scope, permanently |

`tests/test_boundaries.py` scans the codebase for forbidden endpoints and techniques, so a regression fails the
build. The legal reasoning, including India's DPDP Act 2023 and its narrow "publicly available" exemption, is in
[docs/LEGAL_AND_PRIVACY.md](docs/LEGAL_AND_PRIVACY.md).

## Who it is for

Fraud and risk analysts checking a number in a complaint. Journalists verifying a source or a scam network.
Due-diligence teams checking a vendor's listed contact. Trust and safety teams triaging reports. Researchers
studying how public data about Indian phone numbers ages and conflicts. In every case the user must be
**authorised** to research the number, and the report records that authorisation.

It is not for finding, following, contacting or monitoring a person.

---

## Installation

Requires Python 3.11 or newer (developed and tested on 3.14).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt            # core, UI and tests
pip install weasyprint                     # optional: PDF reports
pip install "maigret>=0.6.5,<0.7"          # optional: opt-in username checks on public profile pages
cp .env.example .env                       # add only the keys you have; every provider is optional
python -m pytest -q                        # 178 tests, no network required
```

## Configuration

Keys live in `.env`, are held as secrets, and are never logged. A missing key simply disables that provider and
the report says so. Run `python main.py providers` to see the live status.

| Category | Variable | Provider | Cost |
|---|---|---|---|
| Search (primary) | `BRAVE_API_KEY` | Brave Search API | $5 free credit a month, then $5 per 1,000 |
| Search | `TAVILY_API_KEY` | Tavily | 1,000 free credits a month |
| Search | `SERPAPI_KEY` | SerpAPI | **PAID OPTIONAL**, 250 free a month |
| Search | `SERPER_API_KEY` | Serper.dev | **PAID OPTIONAL**, 2,500 free queries |
| Search (deprecated) | `GOOGLE_CSE_API_KEY`, `GOOGLE_CSE_CX` | Google Programmable Search | closed to new customers, ends 2027-01-01 |
| Phone | none | libphonenumber | free, offline, always on |
| Phone | `VERIPHONE_API_KEY` | Veriphone | 1,000 free credits a month |
| Phone | `NUMVERIFY_API_KEY` | NumVerify | 100 free a month |
| Phone | `ABSTRACT_PHONE_API_KEY` | AbstractAPI | 100 free |
| Phone | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` | Twilio Lookup, line type only | **PAID OPTIONAL** |
| Phone | `PHONEINFOGA_URL` | local PhoneInfoga sidecar | free, upstream unmaintained |
| Business | `GOOGLE_PLACES_API_KEY` | Google Places text search by phone | **PAID OPTIONAL** |
| Registry | `INDIANKANOON_API_TOKEN` | Indian Kanoon judgments | **PAID OPTIONAL** |
| Image | `TINEYE_API_KEY` | TinEye reverse image | **PAID OPTIONAL** |
| Username | `GITHUB_TOKEN` | raises the GitHub public API limit | free |

Full provider matrix with endpoints, pricing and exclusions: [docs/PROVIDERS.md](docs/PROVIDERS.md).

## Usage

```bash
python main.py investigate --phone "+919876543210"                 # STANDARD depth
python main.py investigate --phone "+919876543210" --quick --json  # numbering facts and exact search only
python main.py investigate --phone "+919876543210" --deep --output report/
python main.py investigate --phone "+919876543210" --providers brave,tavily --no-social --no-documents
python main.py investigate --phone "+919876543210" --case CASE-42 --authorization "Client X, fraud inquiry"
python main.py investigate --phone "+919876543210" --offline       # synthetic fixture, no network
python main.py plan --phone "+919876543210" --deep                 # dry run: print the query plan only
python main.py normalize "(98)76543210"                            # normalisation and search variants
python main.py providers                                           # which providers are configured
python main.py history                                             # stored investigations
python main.py ui                                                  # Streamlit workstation
```

| Depth | Queries | Leads | Page fetches | What runs |
|---|---|---|---|---|
| `--quick` | 12 | 0 | 0 | numbering facts and exact-match search |
| standard | 60 | 8 | 15 | all public-source stages and one round of leads |
| `--deep` | 150 | 25 | 40 | recursive leads to depth 3 and opt-in username checks |

"Deep" only ever means more public queries. It never means deeper access.

## Architecture

```
main.py                 CLI: investigate, normalize, plan, providers, history, export, ui
config/                 settings from .env, all keys held as secrets
core/                   data models, normaliser, query strategy, engine, evidence sink, HTTP client, logging
providers/              one class per external source, each optional
  search/               brave, serpapi, serper, tavily, google_cse, fixture
  phone/                libphonenumber, veriphone, numverify, abstractapi, twilio, phoneinfoga
  username/ business/ registry/ image/
collectors/             one stage each: telecom, search, documents, social, business, registries,
                        classifieds, page_fetch, leads
extractors/             phones, e-mails, profile URLs, Indian names, businesses, addresses, dates, documents
correlation/            dedup, entity resolution, contradictions, timeline, co-listed numbers, graph
scoring/                confidence ledger, lead relevance, source quality, information gain
reports/                JSON, Markdown, HTML, CSV, PDF
storage/                response cache, evidence store, bounded source snapshots (all SQLite or JSON)
ui/                     Streamlit app
fixtures/               the fictional offline scenario
tests/                  178 tests, fully offline
```

Shared infrastructure every provider uses: per-host rate limits, bounded retries with back-off, a response
cache, robots.txt enforcement, size and content-type limits, and logs that mask numbers as `+91******3210`.

Design contract: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Research behind the tool and API choices,
including why PhoneInfoga, Sherlock, SpiderFoot, theHarvester and Holehe were wrapped or rejected:
[docs/RESEARCH.md](docs/RESEARCH.md).

## Honest limitations

Search coverage is partial, so an empty result proves nothing. Platforms behind login walls contribute only
search snippets. Name and address extraction for Indian text is heuristic and weaker on regional scripts. Many
pages carry no reliable date. Carrier hints predate portability. Scores are estimates for triage, never grounds
for a decision. The full list is in [docs/LIMITATIONS.md](docs/LIMITATIONS.md).

## Roadmap

* Extraction for Hindi and other Indic scripts, with transliteration
* More lawful search back-ends and a self-hosted OpenStreetMap phone-tag provider
* Case management across several numbers with strict purpose limitation and retention timers
* A FastAPI and React front end with authentication and audit logging
* Cited, post-hoc summaries of the evidence, never used as a source

## Responsible use

Use Saakshya only for numbers you are authorised to research and only for a lawful purpose. Record that purpose
with `--case` and `--authorization`. Delete `data/` and `output/` when the purpose is served. Treat every report
as personal data. Do not use this tool to locate, contact, monitor or harass anyone.
