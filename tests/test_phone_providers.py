"""
Tests for providers/phone/* (telecom / numbering intelligence).

All numbers are synthetic.  Network calls are intercepted with respx; nothing
here ever reaches a real API.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from config.settings import Settings
from core.http import HttpClient
from core.models import PhoneKind, ProviderState, TelecomResult
from core.normalize import normalize_indian_number
from providers.phone import twilio as twilio_mod
from providers.phone.abstractapi import ABSTRACT_URL, AbstractPhoneProvider
from providers.phone.india_mccmnc import AS_OF, INDIA_MCCMNC, SOURCE, decode_mccmnc
from providers.phone.libphonenumber import LibPhoneNumberProvider
from providers.phone.numverify import NUMVERIFY_URL, NumVerifyProvider
from providers.phone.phoneinfoga import UNAVAILABLE_REASON, PhoneInfogaProvider
from providers.phone.twilio import FORBIDDEN_FIELDS, TwilioLookupProvider, validate_fields
from providers.phone.veriphone import VERIPHONE_URL, VeriphoneProvider
from storage.cache import ResponseCache

MOBILE = "+919876543210"
LANDLINE = "+911123456789"
TOLL_FREE = "+9118001234567"

VERIPHONE_KEY = "veriphone-test-key-0123456789abcdef"
NUMVERIFY_KEY = "numverify-test-key-0123456789abcdef"
ABSTRACT_KEY = "abstract-test-key-SECRET-0123456789abcdef"
TWILIO_SID = "ACtest00000000000000000000000000"
TWILIO_TOKEN = "twilio-test-token-0123456789abcdef"
PHONEINFOGA_URL = "http://phoneinfoga.test:5000"


def make_settings(**env: Any) -> Settings:
    base: dict[str, Any] = {
        "OSINT_HTTP_MAX_RETRIES": 0,
        "OSINT_PER_HOST_RATE": 1000.0,
        "OSINT_RESPECT_ROBOTS": False,
        "OSINT_HTTP_TIMEOUT": 5.0,
    }
    base.update(env)
    return Settings(_env_file=None, **base)


def by_field(results: list[TelecomResult]) -> dict[str, TelecomResult]:
    return {r.field: r for r in results}


def assert_well_formed(results: list[TelecomResult], provider_prefix: str) -> None:
    assert results, "expected at least one TelecomResult"
    for r in results:
        assert r.provider.startswith(provider_prefix)
        assert r.field and isinstance(r.value, str) and r.value != ""
        assert 0.0 <= r.confidence <= 1.0
        assert isinstance(r.raw, dict)


# --------------------------------------------------------------------------- #
# libphonenumber (offline)
# --------------------------------------------------------------------------- #


async def test_libphonenumber_mobile() -> None:
    p = LibPhoneNumberProvider(make_settings())
    assert p.available and p.state == ProviderState.AVAILABLE
    results = await p.lookup(normalize_indian_number(MOBILE))
    await p.aclose()
    assert_well_formed(results, "libphonenumber")
    f = by_field(results)
    assert f["country"].value == "India"
    assert f["country_code"].value == "91"
    assert f["region_code"].value == "IN"
    assert f["e164"].value == MOBILE
    assert f["number_type"].value == PhoneKind.MOBILE.value
    assert f["is_valid"].value == "True"
    assert f["is_possible"].value == "True"
    assert "original_carrier" in f
    assert f["original_carrier"].confidence == 0.4
    assert "Mobile Number Portability" in f["original_carrier"].note
    assert f["timezones"].value == "Asia/Calcutta"
    assert f["mnp_region"].value == "True"
    assert f["metadata_version"].value  # e.g. 9.0.38
    assert f["metadata_version"].confidence == 1.0
    assert not p.errors


async def test_libphonenumber_landline() -> None:
    p = LibPhoneNumberProvider(make_settings())
    results = await p.lookup(normalize_indian_number(LANDLINE))
    await p.aclose()
    f = by_field(results)
    assert f["number_type"].value == PhoneKind.FIXED_LINE.value
    assert "original_carrier" not in f  # libphonenumber has no carrier for landlines -> skipped
    assert f["geocoder_description"].value == "New Delhi"
    assert f["geocoder_description"].confidence == 0.6
    assert "fixed lines" in f["geocoder_description"].note
    assert f["national_format"].value.startswith("0")


async def test_libphonenumber_toll_free() -> None:
    p = LibPhoneNumberProvider(make_settings())
    results = await p.lookup(normalize_indian_number(TOLL_FREE))
    await p.aclose()
    f = by_field(results)
    assert f["number_type"].value == PhoneKind.TOLL_FREE.value
    assert f["is_valid"].value == "True"
    assert "original_carrier" not in f
    assert f["e164"].value == TOLL_FREE


async def test_libphonenumber_never_emits_identity_fields() -> None:
    p = LibPhoneNumberProvider(make_settings())
    results = await p.lookup(normalize_indian_number(MOBILE))
    await p.aclose()
    for r in results:
        assert r.field not in {"name", "owner", "caller_name", "email", "address"}


# --------------------------------------------------------------------------- #
# Veriphone
# --------------------------------------------------------------------------- #

VERIPHONE_OK = {
    "status": "success", "phone": MOBILE, "phone_valid": True, "phone_type": "mobile",
    "phone_region": "India", "country": "India", "country_code": "IN", "country_prefix": "91",
    "international_number": "+91 98765 43210", "local_number": "098765 43210", "e164": MOBILE,
    "carrier": "Example Telecom", "timezone": ["Asia/Kolkata"],
}


def test_veriphone_missing_key_state() -> None:
    p = VeriphoneProvider(make_settings())
    assert p.state == ProviderState.MISSING_KEY
    assert not p.available
    assert "veriphone_api_key" in p.unavailable_reason()
    assert p.paid is False
    assert p.allow_current_mode is False


async def test_veriphone_parses_and_uses_bearer_header(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(VERIPHONE_URL).mock(return_value=httpx.Response(200, json=VERIPHONE_OK))
    settings = make_settings(VERIPHONE_API_KEY=VERIPHONE_KEY)
    async with HttpClient(settings, ResponseCache(":memory:")) as http:
        p = VeriphoneProvider(settings, http)
        assert p.available
        results = await p.lookup(normalize_indian_number(MOBILE))
        # second call served from cache: no extra request
        again = await p.lookup(normalize_indian_number(MOBILE))
    assert route.call_count == 1
    req = route.calls[0].request
    assert req.headers["Authorization"] == f"Bearer {VERIPHONE_KEY}"
    assert "mode" not in dict(req.url.params)  # mode=current (10 credits) never sent
    assert req.url.params["phone"] == MOBILE
    assert req.url.params["default_country"] == "IN"
    assert_well_formed(results, "veriphone")
    f = by_field(results)
    assert f["carrier"].value == "Example Telecom"
    assert f["carrier"].confidence == 0.6
    assert "original allocation" in f["carrier"].note
    assert f["phone_valid"].value == "True"
    assert f["timezone"].value == "Asia/Kolkata"
    assert f["e164"].value == MOBILE
    assert len(again) == len(results) and again[0].raw["from_cache"] is True
    assert not p.errors


@pytest.mark.parametrize("status,expect", [(402, "out of credits"), (429, "rate limited"),
                                           (500, "HTTP 500"), (401, "invalid API key")])
async def test_veriphone_http_errors_never_raise(respx_mock: respx.MockRouter, status: int,
                                                 expect: str) -> None:
    respx_mock.get(VERIPHONE_URL).mock(return_value=httpx.Response(status, json={"status": "error"}))
    settings = make_settings(VERIPHONE_API_KEY=VERIPHONE_KEY)
    async with HttpClient(settings) as http:
        p = VeriphoneProvider(settings, http)
        results = await p.lookup(normalize_indian_number(MOBILE))
    assert results == []
    assert len(p.errors) == 1 and expect in p.errors[0]
    assert VERIPHONE_KEY not in " ".join(p.errors)


async def test_veriphone_api_level_error(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(VERIPHONE_URL).mock(
        return_value=httpx.Response(200, json={"status": "error", "message": "invalid phone"}))
    settings = make_settings(VERIPHONE_API_KEY=VERIPHONE_KEY)
    async with HttpClient(settings) as http:
        p = VeriphoneProvider(settings, http)
        assert await p.lookup(normalize_indian_number(MOBILE)) == []
    assert p.errors and "invalid phone" in p.errors[0]


async def test_veriphone_network_error(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(VERIPHONE_URL).mock(side_effect=httpx.ConnectError("boom"))
    settings = make_settings(VERIPHONE_API_KEY=VERIPHONE_KEY)
    async with HttpClient(settings) as http:
        p = VeriphoneProvider(settings, http)
        assert await p.lookup(normalize_indian_number(MOBILE)) == []
    assert p.errors == ["veriphone: ConnectError"]


# --------------------------------------------------------------------------- #
# NumVerify
# --------------------------------------------------------------------------- #

NUMVERIFY_OK = {
    "valid": True, "number": "919876543210", "local_format": "09876543210",
    "international_format": MOBILE, "country_prefix": "+91", "country_code": "IN",
    "country_name": "India", "location": "", "carrier": "Example Telecom Ltd", "line_type": "mobile",
}


def test_numverify_missing_key_state() -> None:
    p = NumVerifyProvider(make_settings())
    assert p.state == ProviderState.MISSING_KEY and p.paid is False


async def test_numverify_parses(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(NUMVERIFY_URL).mock(return_value=httpx.Response(200, json=NUMVERIFY_OK))
    settings = make_settings(NUMVERIFY_API_KEY=NUMVERIFY_KEY)
    async with HttpClient(settings) as http:
        p = NumVerifyProvider(settings, http)
        results = await p.lookup(normalize_indian_number(MOBILE))
    req = route.calls[0].request
    assert req.headers["apikey"] == NUMVERIFY_KEY
    assert req.url.params["number"] == "919876543210"
    assert "apikey" not in str(req.url) and NUMVERIFY_KEY not in str(req.url)
    assert_well_formed(results, "numverify")
    f = by_field(results)
    assert f["valid"].value == "True"
    assert f["carrier"].value == "Example Telecom Ltd" and "Portability" in f["carrier"].note
    assert f["line_type"].value == "mobile"
    assert "location" not in f  # empty string skipped
    assert all(r.confidence == 0.6 for r in results)


@pytest.mark.parametrize("status", [402, 429, 500])
async def test_numverify_http_errors(respx_mock: respx.MockRouter, status: int) -> None:
    respx_mock.get(NUMVERIFY_URL).mock(return_value=httpx.Response(status, json={"message": "no"}))
    settings = make_settings(NUMVERIFY_API_KEY=NUMVERIFY_KEY)
    async with HttpClient(settings) as http:
        p = NumVerifyProvider(settings, http)
        assert await p.lookup(normalize_indian_number(MOBILE)) == []
    assert len(p.errors) == 1 and NUMVERIFY_KEY not in p.errors[0]


async def test_numverify_legacy_style_error_payload(respx_mock: respx.MockRouter) -> None:
    payload = {"success": False, "error": {"code": 104, "type": "usage_limit_reached", "info": "quota"}}
    respx_mock.get(NUMVERIFY_URL).mock(return_value=httpx.Response(200, json=payload))
    settings = make_settings(NUMVERIFY_API_KEY=NUMVERIFY_KEY)
    async with HttpClient(settings) as http:
        p = NumVerifyProvider(settings, http)
        assert await p.lookup(normalize_indian_number(MOBILE)) == []
    assert p.errors and "quota" in p.errors[0]


# --------------------------------------------------------------------------- #
# Abstract API
# --------------------------------------------------------------------------- #

ABSTRACT_OK = {
    "phone": "919876543210", "valid": True,
    "format": {"international": MOBILE, "local": "098765 43210"},
    "country": {"code": "IN", "name": "India", "prefix": "+91"},
    "location": "", "type": "mobile", "carrier": "Example Telecom",
}


def test_abstractapi_missing_key_state() -> None:
    p = AbstractPhoneProvider(make_settings())
    assert p.state == ProviderState.MISSING_KEY and p.paid is False


async def test_abstractapi_parses_and_key_never_reaches_cache(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(ABSTRACT_URL).mock(return_value=httpx.Response(200, json=ABSTRACT_OK))
    settings = make_settings(ABSTRACT_PHONE_API_KEY=ABSTRACT_KEY)
    cache = ResponseCache(":memory:")
    async with HttpClient(settings, cache) as http:
        p = AbstractPhoneProvider(settings, http)
        assert p.available
        results = await p.lookup(normalize_indian_number(MOBILE))
        cached = await p.lookup(normalize_indian_number(MOBILE))
    # the key WAS sent to the API as a query param (so the assertion below is meaningful) ...
    req = route.calls[0].request
    assert req.url.params["api_key"] == ABSTRACT_KEY
    assert req.url.params["phone"] == "919876543210"
    assert route.call_count == 1  # second lookup came from the manual cache
    # ... but never persisted: inspect every column of every row in the cache DB
    rows = cache._conn.execute("SELECT key, url, query, payload FROM cache").fetchall()
    assert len(rows) == 1
    dump = json.dumps(rows, default=str)
    assert ABSTRACT_KEY not in dump
    assert "api_key" not in dump
    assert rows[0][0].startswith("abstractapi:")
    assert rows[0][1] == ABSTRACT_URL
    assert_well_formed(results, "abstractapi")
    f = by_field(results)
    assert f["valid"].value == "True"
    assert f["international_format"].value == MOBILE
    assert f["local_format"].value == "098765 43210"
    assert f["country_code"].value == "IN" and f["country_name"].value == "India"
    assert f["country_prefix"].value == "+91"
    assert f["line_type"].value == "mobile"
    assert f["carrier"].value == "Example Telecom" and "Portability" in f["carrier"].note
    assert "location" not in f
    assert by_field(cached)["valid"].raw["from_cache"] is True
    assert not p.errors


@pytest.mark.parametrize("status", [402, 429, 500])
async def test_abstractapi_http_errors(respx_mock: respx.MockRouter, status: int) -> None:
    respx_mock.get(ABSTRACT_URL).mock(return_value=httpx.Response(status, json={"error": {"message": "x"}}))
    settings = make_settings(ABSTRACT_PHONE_API_KEY=ABSTRACT_KEY)
    cache = ResponseCache(":memory:")
    async with HttpClient(settings, cache) as http:
        p = AbstractPhoneProvider(settings, http)
        assert await p.lookup(normalize_indian_number(MOBILE)) == []
    assert len(p.errors) == 1 and ABSTRACT_KEY not in p.errors[0]
    assert cache.stats()["entries"] == 0  # errors are not cached


async def test_abstractapi_network_error_message_has_no_url(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(ABSTRACT_URL).mock(side_effect=httpx.ReadTimeout("timeout"))
    settings = make_settings(ABSTRACT_PHONE_API_KEY=ABSTRACT_KEY)
    async with HttpClient(settings) as http:
        p = AbstractPhoneProvider(settings, http)
        assert await p.lookup(normalize_indian_number(MOBILE)) == []
    assert p.errors == ["abstractapi: ReadTimeout"]


# --------------------------------------------------------------------------- #
# Twilio
# --------------------------------------------------------------------------- #

TWILIO_OK = {
    "calling_country_code": "91", "country_code": "IN", "phone_number": MOBILE,
    "national_format": "098765 43210", "valid": True, "validation_errors": [],
    "line_type_intelligence": {
        "carrier_name": "Example Telecom", "error_code": None,
        "mobile_country_code": "404", "mobile_network_code": "45", "type": "mobile",
    },
}


def test_twilio_missing_key_state() -> None:
    p = TwilioLookupProvider(make_settings(TWILIO_ACCOUNT_SID=TWILIO_SID))  # token missing
    assert p.state == ProviderState.MISSING_KEY
    assert p.paid is True
    assert "twilio_auth_token" in p.unavailable_reason()


@pytest.mark.parametrize("forbidden", sorted(FORBIDDEN_FIELDS))
def test_twilio_forbidden_fields_guard(forbidden: str) -> None:
    with pytest.raises(ValueError):
        validate_fields(("line_type_intelligence", forbidden))
    with pytest.raises(ValueError):
        TwilioLookupProvider(make_settings(), fields=(forbidden,))


def test_twilio_unknown_field_rejected_and_default_ok() -> None:
    with pytest.raises(ValueError):
        validate_fields(("something_else",))
    assert validate_fields(("line_type_intelligence",)) == ("line_type_intelligence",)
    assert TwilioLookupProvider(make_settings()).fields == ("line_type_intelligence",)
    assert twilio_mod.DEFAULT_FIELDS == ("line_type_intelligence",)


async def test_twilio_parses_with_basic_auth_and_mccmnc(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(f"https://lookups.twilio.com/v2/PhoneNumbers/{MOBILE}").mock(
        return_value=httpx.Response(200, json=TWILIO_OK))
    settings = make_settings(TWILIO_ACCOUNT_SID=TWILIO_SID, TWILIO_AUTH_TOKEN=TWILIO_TOKEN)
    cache = ResponseCache(":memory:")
    async with HttpClient(settings, cache) as http:
        p = TwilioLookupProvider(settings, http)
        assert p.available
        results = await p.lookup(normalize_indian_number(MOBILE))
    req = route.calls[0].request
    assert req.headers["Authorization"].startswith("Basic ")
    assert req.url.params["Fields"] == "line_type_intelligence"
    for name in FORBIDDEN_FIELDS:
        assert name not in str(req.url)
    # credentials are not in the cache DB
    dump = json.dumps(cache._conn.execute("SELECT key, url, query, payload FROM cache").fetchall())
    assert TWILIO_TOKEN not in dump and TWILIO_SID not in dump
    assert_well_formed(results, "twilio")
    f = by_field(results)
    assert f["valid"].value == "True"
    assert "validation_errors" not in f  # empty list skipped
    assert f["national_format"].value == "098765 43210"
    assert f["country_code"].value == "IN"
    assert f["line_type"].value == "mobile"
    assert f["carrier_name"].value == "Example Telecom"
    assert f["mobile_country_code"].value == "404" and f["mobile_network_code"].value == "45"
    assert f["operator_from_mccmnc"].value.startswith("Airtel")
    assert "Karnataka" in f["operator_from_mccmnc"].value
    assert f["operator_from_mccmnc"].confidence == 0.5
    assert not p.errors


async def test_twilio_guard_enforced_at_lookup_time() -> None:
    settings = make_settings(TWILIO_ACCOUNT_SID=TWILIO_SID, TWILIO_AUTH_TOKEN=TWILIO_TOKEN)
    p = TwilioLookupProvider(settings)
    p.fields = ("line_type_intelligence", "caller_name")  # someone mutates it after construction
    with pytest.raises(ValueError):
        await p.lookup(normalize_indian_number(MOBILE))
    await p.aclose()


@pytest.mark.parametrize("status", [402, 404, 429, 500])
async def test_twilio_http_errors(respx_mock: respx.MockRouter, status: int) -> None:
    respx_mock.get(f"https://lookups.twilio.com/v2/PhoneNumbers/{MOBILE}").mock(
        return_value=httpx.Response(status, json={"message": "err"}))
    settings = make_settings(TWILIO_ACCOUNT_SID=TWILIO_SID, TWILIO_AUTH_TOKEN=TWILIO_TOKEN)
    async with HttpClient(settings) as http:
        p = TwilioLookupProvider(settings, http)
        assert await p.lookup(normalize_indian_number(MOBILE)) == []
    assert len(p.errors) == 1 and TWILIO_TOKEN not in p.errors[0]


# --------------------------------------------------------------------------- #
# MCC / MNC table
# --------------------------------------------------------------------------- #


def test_mccmnc_table_shape() -> None:
    assert len(INDIA_MCCMNC) >= 80
    assert SOURCE.startswith("https://") and AS_OF
    for key, row in INDIA_MCCMNC.items():
        mcc, mnc = key.split("-")
        assert mcc in ("404", "405") and mnc.isdigit() and 2 <= len(mnc) <= 3
        assert row["operator"] and row["status"] in ("operational", "not_operational", "unknown")
    operators = {r["operator"] for r in INDIA_MCCMNC.values()}
    for needle in ("Jio", "Airtel", "Vi", "BSNL", "MTNL", "Aircel", "Tata", "Telenor", "Reliance"):
        assert any(needle in op for op in operators), needle


def test_decode_mccmnc() -> None:
    row = decode_mccmnc("404", "45")
    assert row and row["operator"].startswith("Airtel") and row["circle"] == "Karnataka"
    assert row["mcc"] == "404" and row["mnc"] == "45"
    jio = decode_mccmnc("405", "874")
    assert jio and "Jio" in jio["operator"] and jio["circle"] == "Mumbai"
    assert decode_mccmnc("404", "999") is None
    assert decode_mccmnc("310", "260") is None  # not India
    assert decode_mccmnc("", "45") is None
    # exact match wins over zero-padding (405-03 is RCom Bihar, 405-030 is Tata Gujarat)
    assert decode_mccmnc("405", "03")["operator"].startswith("Reliance")
    assert decode_mccmnc("405", "030")["operator"].startswith("Tata")
    # zero-padded fallback for stripped leading zeros
    assert decode_mccmnc("405", "25")["operator"].startswith("Tata")


# --------------------------------------------------------------------------- #
# PhoneInfoga sidecar
# --------------------------------------------------------------------------- #


def test_phoneinfoga_unavailable_when_url_unset() -> None:
    p = PhoneInfogaProvider(make_settings())
    assert p.state == ProviderState.NOT_INSTALLED
    assert not p.available
    assert p.unavailable_reason() == UNAVAILABLE_REASON
    assert "PHONEINFOGA_URL" in p.unavailable_reason()


async def test_phoneinfoga_lookup_without_url_returns_empty() -> None:
    p = PhoneInfogaProvider(make_settings())
    assert await p.lookup(normalize_indian_number(MOBILE)) == []
    assert p.errors and "PHONEINFOGA_URL" in p.errors[0]
    await p.aclose()


async def test_phoneinfoga_sidecar_flow(respx_mock: respx.MockRouter) -> None:
    base = PHONEINFOGA_URL
    health = respx_mock.get(f"{base}/api/").mock(
        return_value=httpx.Response(200, json={"success": True, "version": "2.11.0", "commit": "abc1234",
                                               "demo": False}))
    numbers = respx_mock.post(f"{base}/api/v2/numbers").mock(
        return_value=httpx.Response(200, json={"valid": True, "rawLocal": "9876543210",
                                               "local": "09876543210", "e164": MOBILE,
                                               "international": "919876543210",
                                               "countryCode": 91, "country": "IN", "carrier": ""}))
    local_dry = respx_mock.post(f"{base}/api/v2/scanners/local/dryrun").mock(
        return_value=httpx.Response(200, json={"success": True, "error": ""}))
    local_run = respx_mock.post(f"{base}/api/v2/scanners/local/run").mock(
        return_value=httpx.Response(200, json={"result": {"valid": True, "e164": MOBILE, "country": "IN",
                                                          "carrier": "Example Telecom",
                                                          "rawLocal": "9876543210",
                                                          "nested": {"ignored": True}}}))
    numverify_dry = respx_mock.post(f"{base}/api/v2/scanners/numverify/dryrun").mock(
        return_value=httpx.Response(200, json={"success": False,
                                               "error": "NUMVERIFY_API_KEY is not defined"}))
    numverify_run = respx_mock.post(f"{base}/api/v2/scanners/numverify/run").mock(
        return_value=httpx.Response(200, json={"result": {}}))
    google_dry = respx_mock.post(f"{base}/api/v2/scanners/googlesearch/dryrun").mock(
        return_value=httpx.Response(200, json={"success": True}))

    settings = make_settings(PHONEINFOGA_URL=base)
    async with HttpClient(settings, ResponseCache(":memory:")) as http:
        p = PhoneInfogaProvider(settings, http)
        assert p.available
        results = await p.lookup(normalize_indian_number(MOBILE))

    assert health.called and numbers.called and local_dry.called and local_run.called
    assert numverify_dry.called and not numverify_run.called  # dry-run failed -> run skipped
    assert not google_dry.called
    assert all("google" not in str(c.request.url) for c in respx_mock.calls)
    assert json.loads(numbers.calls[0].request.content) == {"number": "919876543210"}
    body = json.loads(local_run.calls[0].request.content)
    assert body["number"] == "919876543210" and "options" in body

    assert_well_formed(results, "phoneinfoga")
    f = {(r.provider, r.field): r for r in results}
    assert f[("phoneinfoga", "phoneinfoga_version")].value == "2.11.0 (abc1234)"
    assert f[("phoneinfoga", "e164")].value == MOBILE
    assert f[("phoneinfoga", "valid")].value == "True"
    assert ("phoneinfoga", "carrier") not in f  # empty carrier skipped
    assert f[("phoneinfoga:local", "carrier")].value == "Example Telecom"
    assert f[("phoneinfoga:local", "carrier")].confidence == 0.4
    assert "unmaintained" in f[("phoneinfoga:local", "carrier")].note
    assert ("phoneinfoga:local", "nested") not in f
    assert ("phoneinfoga:numverify", "valid") not in f
    assert not p.errors


async def test_phoneinfoga_health_failure(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{PHONEINFOGA_URL}/api/").mock(side_effect=httpx.ConnectError("down"))
    settings = make_settings(PHONEINFOGA_URL=PHONEINFOGA_URL)
    async with HttpClient(settings) as http:
        p = PhoneInfogaProvider(settings, http)
        assert await p.lookup(normalize_indian_number(MOBILE)) == []
    assert p.errors == ["phoneinfoga: ConnectError on /api/"]


async def test_phoneinfoga_partial_failure_keeps_health(respx_mock: respx.MockRouter) -> None:
    base = PHONEINFOGA_URL
    respx_mock.get(f"{base}/api/").mock(return_value=httpx.Response(200, json={"version": "2.11.0"}))
    respx_mock.post(f"{base}/api/v2/numbers").mock(return_value=httpx.Response(500, text="oops"))
    respx_mock.post(f"{base}/api/v2/scanners/local/dryrun").mock(return_value=httpx.Response(429))
    respx_mock.post(f"{base}/api/v2/scanners/numverify/dryrun").mock(return_value=httpx.Response(404))
    settings = make_settings(PHONEINFOGA_URL=base)
    async with HttpClient(settings) as http:
        p = PhoneInfogaProvider(settings, http)
        results = await p.lookup(normalize_indian_number(MOBILE))
    assert [r.field for r in results] == ["phoneinfoga_version"]
    assert any("HTTP 500" in e for e in p.errors)
    assert any("rate limited" in e for e in p.errors)
