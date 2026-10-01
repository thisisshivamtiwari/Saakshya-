"""Indian number normalisation (spec section 3) - synthetic numbers only."""

import pytest

from core.models import PhoneKind, mask_phone
from core.normalize import looks_like_indian_number, normalize_indian_number


@pytest.mark.parametrize("raw", [
    "+91 98765 43210", "+919876543210", "919876543210", "09876543210", "9876543210", "98-7654-3210",
    "(98)76543210", "+91 0 98765 43210", "0091 9876543210", "+91-98765-43210", "9876 543 210 ", "091 9876543210",
])
def test_all_formats_normalise_to_e164(raw):
    r = normalize_indian_number(raw)
    assert r.e164 == "+919876543210"
    assert r.is_valid and r.is_indian and r.ok
    assert r.kind == PhoneKind.MOBILE
    assert r.subscriber == "9876543210"
    assert r.masked == "+91******3210"


def test_formats_and_variants():
    r = normalize_indian_number("+919876543210")
    assert r.national == "098765 43210"
    assert r.international == "+91 98765 43210"
    for v in ("+919876543210", "919876543210", "09876543210", "9876543210", "98765 43210", "+91 98765 43210",
              "98-7654-3210"):
        assert v in r.variants
    assert r.quoted_variants[0] == '"+919876543210"'
    assert any("Portability" in n for n in r.notes)


def test_landline_toll_free_and_service_numbers():
    land = normalize_indian_number("011-23456789")
    assert land.e164 == "+911123456789" and land.kind == PhoneKind.FIXED_LINE and land.is_valid
    assert any("0" + land.subscriber[:2] + "-" in v for v in land.variants)
    patna = normalize_indian_number("+91 6123456789")  # 612 = Patna STD code, not a mobile
    assert patna.kind == PhoneKind.FIXED_LINE
    tf = normalize_indian_number("1800 123 4567")
    assert tf.e164 == "+9118001234567" and tf.kind == PhoneKind.TOLL_FREE
    tm = normalize_indian_number("+91 1409876543")
    assert tm.kind == PhoneKind.TELEMARKETING
    short = normalize_indian_number("12345")
    assert not short.is_valid and short.kind == PhoneKind.SERVICE and short.warnings


def test_invalid_and_international():
    us = normalize_indian_number("+1 415 555 2671")
    assert not us.is_indian and not us.ok and "not Indian" in us.warnings[0]
    assert us.variants == []
    bad = normalize_indian_number("abc")
    assert bad.kind == PhoneKind.INVALID and not bad.e164
    eleven = normalize_indian_number("98765432101")
    assert not eleven.is_valid
    empty = normalize_indian_number("")
    assert not empty.is_valid


def test_mask_and_predicate():
    assert mask_phone("+919876543210") == "+91******3210"
    assert mask_phone("9876543210") == "******3210"
    assert looks_like_indian_number("98765 43210")
    assert looks_like_indian_number("+91-9876543210")
    assert not looks_like_indian_number("12345")
