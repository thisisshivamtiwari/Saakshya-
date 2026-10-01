# Known limitations

## What the engine cannot do (by design)

* It cannot tell you **who owns a number**. It reports public associations with evidence, dates and confidence.
* It cannot obtain subscriber records, call-detail records, live location, SIM status, current carrier via
  network probes, Aadhaar/PAN/bank data, private profiles, or breach/leak data. It never will.
* It cannot guess alternate numbers. Only numbers **publicly co-listed** with the same page/entity are reported.
* It does not scrape search engines or directories. Coverage is bounded by the documented search APIs you
  configure (Brave, SerpAPI, Serper, Tavily, legacy Google CSE).

## Coverage and data quality

* **Search-engine coverage is partial.** Indexes favour recent, popular pages; many Indian directory pages,
  PDFs and regional-language pages are not indexed or not returned for exact-phrase queries. Absence of results
  is not evidence of absence.
* **Provider snippets are short.** Findings from snippets alone have less context; page fetching (robots.txt
  permitting) improves extraction but many platforms (LinkedIn, Facebook, Instagram, X) are behind login walls
  or disallow fetching, so their evidence stays snippet-level.
* **Name extraction is heuristic.** Indian names are detected with labelled patterns and a surname list. Names
  outside the list, transliterated names, and Hindi/regional-script text are under-recognised. Businesses named
  after people ("Sharma Traders") can look like persons and vice versa.
* **Address parsing is heuristic** (pincode/city/keyword based); classification (residential/commercial/office)
  is a keyword guess and is labelled as such.
* **Dates** come from page metadata or labelled text; many pages have no reliable date, so timeline entries are
  often "unknown".
* **Carrier/circle hints are historical.** India has nationwide Mobile Number Portability; libphonenumber's
  carrier map reflects original allocation, and the geocoder returns only "India" for mobiles.
* **Recycled numbers.** DoT/TRAI allow deactivated numbers to be reallocated; older public associations may
  refer to a previous holder. The temporal-change contradiction exists precisely for this; it cannot resolve it.
* **Entity resolution is conservative.** Different names are never merged without a strong key (email,
  platform username, website). This may split one real person into two candidates (e.g. maiden/married names).
* **Confidence scores are point ledgers**, not probabilities. They are useful for triage, not for decisions.

## Operational limits

* Query budgets (QUICK 12 / STANDARD 60 / DEEP 150) and information-gain cut-offs bound cost; deep-web
  coverage requires larger budgets and paid plans.
* Free API tiers are small (Brave ~1,000/month, Tavily 1,000 credits, Veriphone 1,000 credits, NumVerify and
  AbstractAPI 100). The engine caches responses (72 h default) to conserve quota.
* Rate limits are honoured with back-off; if a provider keeps returning 429 the stage records an error.
* Page fetching downloads at most 5 MB per document and never executes active content, but documents are still
  parsed in-process; run in a sandbox for hostile sources.
* The Streamlit UI runs the investigation in a background thread of the Streamlit process; long DEEP runs
  should use the CLI.

## Legal caveats

See `docs/LEGAL_AND_PRIVACY.md`. The "publicly available" exemption in India's DPDP Act is narrow; you remain
responsible for lawful purpose, retention and access control of the reports.
