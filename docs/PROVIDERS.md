# Providers and sources

Every external source is a *provider* behind `providers/base.py`. A provider is used only when its keys are
configured; otherwise it is listed as `missing_key` / `not_installed` and skipped. `python main.py providers`
shows the live status. Pricing/availability below was checked in September 2026 — re-verify before relying on it.

Legend: **FREE** · **FREE-TIER** (free quota, paid beyond) · **PAID OPTIONAL PROVIDER** · **DEPRECATED** · **EXCLUDED**

## Search (web discovery)

| Provider | Name | Status | Env | Notes |
|---|---|---|---|---|
| Brave Search API | `brave` | FREE-TIER | `BRAVE_API_KEY` | Primary. `GET https://api.search.brave.com/res/v1/web/search`, header `X-Subscription-Token`, `country=IN`. Supports quotes, `site:`, `filetype:`. $5 free credit/month (~1,000 queries), then $5/1k. ToS restricts building databases of results → snippets are not persisted unless `OSINT_STORE_PROVIDER_SNIPPETS=true`; also forbids use for "surveillance" — keep to lawful, authorised research. |
| SerpAPI | `serpapi` | PAID OPTIONAL PROVIDER | `SERPAPI_KEY` | Google (google.co.in, gl=in), Bing, DuckDuckGo, Yandex via a scrape-on-your-behalf service; free 250 searches/month, Starter $25/1k, Legal Shield from $150/month. Key is a query parameter → cached manually so it never enters the cache DB. |
| Serper.dev | `serper` | PAID OPTIONAL PROVIDER | `SERPER_API_KEY` | `POST https://google.serper.dev/search`, header `X-API-KEY`; 2,500 free queries then from $0.30–$1.00/1k; no indemnity. |
| Tavily | `tavily` | FREE-TIER | `TAVILY_API_KEY` | `POST https://api.tavily.com/search`, Bearer auth, `exact_match`, `include_domains` (site: is translated), no `filetype:`; 1,000 free credits/month. Terms forbid submitting government IDs (never done). |
| Google Programmable Search JSON API | `google_cse` | DEPRECATED | `GOOGLE_CSE_API_KEY`, `GOOGLE_CSE_CX` | Closed to new customers; shuts down 2027-01-01. Works only for existing CSE projects (100 free/day, $5/1k). |
| Fixture | `fixture` | FREE | — | Offline synthetic corpus for demos/tests (`--offline`). Never used online. |
| Bing Web Search API | — | EXCLUDED | — | Retired by Microsoft on 11 Aug 2025; the replacement (Grounding with Bing) returns no raw results. |
| DuckDuckGo / `ddgs` / SearXNG | — | EXCLUDED | — | No official web-search API; the libraries scrape HTML (DDG params are "for individual use"). Violates the no-scraping boundary. |
| Exa / You.com | — | not implemented | — | Legitimate paid options with permissive APIs; easy to add as `SearchProvider` subclasses. |

## Phone / numbering intelligence

| Provider | Name | Status | Env | Notes |
|---|---|---|---|---|
| libphonenumber (`phonenumbers` 9.x) | `libphonenumber` | FREE, offline | — | Validation, E.164/national/international formats, number type, timezones, *original allocation* carrier (labelled; India has nationwide MNP), geocoder area for fixed lines. Always on. |
| Veriphone v3 | `veriphone` | FREE-TIER | `VERIPHONE_API_KEY` | `GET https://api.veriphone.io/v3/verify`, Bearer auth; 1,000 credits/month free. `mode=current` (ported carrier, 10 credits) is disabled by class attribute. |
| NumVerify (apilayer) | `numverify` | FREE-TIER | `NUMVERIFY_API_KEY` | `GET https://api.apilayer.com/number_verification/validate`, header `apikey`; 100 req/month free. |
| AbstractAPI Phone Validation | `abstractapi` | FREE-TIER | `ABSTRACT_PHONE_API_KEY` | `GET https://phonevalidation.abstractapi.com/v1/`; 100 free requests. Key in URL → manual caching. |
| Twilio Lookup v2 | `twilio` | PAID OPTIONAL PROVIDER | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` | Only `Fields=line_type_intelligence` ($0.008/request). A code guard rejects caller-name, SIM-swap, identity-match, reassigned-number, pre-fill, quality-score, SMS-pumping and line-status packages. |
| PhoneInfoga sidecar | `phoneinfoga` | FREE (optional) | `PHONEINFOGA_URL` | Wraps a locally running `phoneinfoga serve --no-client` (REST `/api/v2/numbers`, `local` + `numverify` scanners only). Upstream is unmaintained (README, Jan 2026; Homebrew formula deprecated); results carry low confidence and are never identity evidence. GPL-3 code stays out-of-process. |
| India MCC/MNC table | (internal) | FREE | — | 250-row operator/circle table (Wikipedia/ITU-derived, best effort) used to decode MCC/MNC returned by APIs. |
| IPQualityScore, Telesign, Truecaller, Eyecon | — | EXCLUDED | — | Fraud-scoring "leaked" flags, sales-only pricing, or no lawful API (Truecaller has no public lookup API; unofficial libraries need login/OTP). |

## Username correlation (opt-in: `--username-enum`, DEEP depth)

| Provider | Name | Status | Env | Notes |
|---|---|---|---|---|
| Built-in public APIs | `builtin` | FREE | `GITHUB_TOKEN` (optional) | GitHub REST `users/{login}`, GitLab `api/v4/users?username=`, Keybase lookup. INFERRED only. |
| Maigret | `maigret` | FREE (optional package) | — | `pip install "maigret>=0.6.5,<0.7"`. Unauthenticated GETs on public profile URLs; sites with activation/protection/similar-search are hard-filtered; no cookies/bypass/proxies ever passed. |
| Sherlock, Holehe, Ignorant | — | EXCLUDED | — | Sherlock: CLI-only internals, network calls at import; Holehe/Ignorant test e-mail/phone ownership through registration/login/password-recovery endpoints — forbidden techniques. |

## Business / places

| Provider | Name | Status | Env | Notes |
|---|---|---|---|---|
| Google Places API (New) Text Search | `google_places` | PAID OPTIONAL PROVIDER (monthly credit) | `GOOGLE_PLACES_API_KEY` | `POST https://places.googleapis.com/v1/places:searchText` with an E.164 `textQuery` and `regionCode=IN`; phone-number searches bill under the Text Search Enterprise SKU. |
| Justdial, IndiaMART, TradeIndia, Sulekha, ExportersIndia … | (search-mediated) | FREE via search APIs | — | Their terms prohibit scraping/automated queries; reached only through `site:` dorks and robots-permitted result pages. |
| OpenStreetMap Overpass | — | not implemented | — | Country-wide regex on `phone=*` tags is too heavy for the public instance; could be added against a self-hosted Overpass. |

## Public registries / courts

| Provider | Name | Status | Env | Notes |
|---|---|---|---|---|
| Indian Kanoon API | `indiankanoon` | PAID OPTIONAL PROVIDER | `INDIANKANOON_API_TOKEN` | `POST https://api.indiankanoon.org/search/?formInput=&pagenum=0`, `Authorization: Token …`; per-page pricing. Judgments are A-quality primary sources. |
| MCA21, GST, eCourts, Udyam, FSSAI, RERA (state portals), SEBI, ICAI, NMC, GeM, CPPP tenders | (search-mediated) | FREE | — | Name/ID-only, CAPTCHA-protected portals: never queried directly. Their public pages and PDFs are discovered with `site:` dorks (see `core/strategy.py` REGISTRY_QUERIES). |
| Election rolls, TAFCOP/Sanchar Saathi, telecom subscriber data, Aadhaar/PAN | — | EXCLUDED | — | Restricted or authenticated citizen services. |

## Documents & images

| Provider | Name | Status | Env | Notes |
|---|---|---|---|---|
| `filetype:` dorks + safe fetch | (collector) | FREE | — | pdf/xls/xlsx/doc/docx/ppt/pptx; robots.txt, 5 MB and content-type limits; pypdf / python-docx / openpyxl parsing; no macros. |
| TinEye | `tineye` | PAID OPTIONAL PROVIDER | `TINEYE_API_KEY` | `GET https://api.tineye.com/rest/search/?url=` with `x-api-key` (shape from TinEye's official client libraries; docs need JS/login — verify before use). |
| Google Lens via SerpAPI | `serpapi_lens` | PAID OPTIONAL PROVIDER | `SERPAPI_KEY` | `engine=google_lens`; public image URLs only; never facial identification. |
| PimEyes, FaceCheck, Clearview | — | EXCLUDED | — | Facial recognition against private databases. |

## Excluded open-source projects (evaluated in `docs/RESEARCH.md`)

SpiderFoot (dormant since 2023, CVE-laden pins, breach modules in default presets), theHarvester (domain-centric,
breach sources), Sherlock, Holehe, Ignorant, PhoneInfoga-as-dependency (unmaintained; wrapped as optional sidecar
instead). `phonenumbers`, Maigret (wrapped) and the SpiderFoot event taxonomy (as inspiration only) were reused.
