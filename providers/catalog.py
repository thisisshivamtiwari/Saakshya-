"""
Catalogue of provider classes.

Each entry is ``"module.path:ClassName"``.  Modules are imported lazily so an
optional dependency that is missing (e.g. ``maigret``) only disables that one
provider - it is reported as NOT_INSTALLED by the registry.
"""

from __future__ import annotations

import importlib

PROVIDER_PATHS: list[str] = [
    # search ------------------------------------------------------------
    "providers.search.fixture:FixtureSearchProvider",
    "providers.search.brave:BraveSearchProvider",
    "providers.search.serpapi:SerpApiSearchProvider",
    "providers.search.google_cse:GoogleCSEProvider",
    "providers.search.serper:SerperSearchProvider",
    "providers.search.tavily:TavilySearchProvider",
    # phone / telecom ---------------------------------------------------
    "providers.phone.libphonenumber:LibPhoneNumberProvider",
    "providers.phone.numverify:NumVerifyProvider",
    "providers.phone.abstractapi:AbstractPhoneProvider",
    "providers.phone.veriphone:VeriphoneProvider",
    "providers.phone.twilio:TwilioLookupProvider",
    "providers.phone.phoneinfoga:PhoneInfogaProvider",
    # username ----------------------------------------------------------
    "providers.username.maigret:MaigretProvider",
    "providers.username.builtin:BuiltinProfileChecker",
    # places / business -------------------------------------------------
    "providers.business.google_places:GooglePlacesProvider",
    # image -------------------------------------------------------------
    "providers.image.tineye:TinEyeProvider",
    "providers.image.serpapi_lens:SerpApiLensProvider",
    # registries --------------------------------------------------------
    "providers.registry.indiankanoon:IndianKanoonProvider",
]


def load_provider_classes() -> tuple[list[type], dict[str, str]]:
    classes: list[type] = []
    errors: dict[str, str] = {}
    for path in PROVIDER_PATHS:
        module_name, _, class_name = path.partition(":")
        try:
            module = importlib.import_module(module_name)
            classes.append(getattr(module, class_name))
        except Exception as exc:  # ImportError or attribute errors for unfinished providers
            errors[path.split(".")[-1].split(":")[0]] = f"{type(exc).__name__}: {exc}"
    return classes, errors
