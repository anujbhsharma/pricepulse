"""Retailer price providers.

Each provider knows how to recognize its URLs (``matches``) and how to turn
a product page into a :class:`PriceSample` (``fetch``).

Honesty note: the scraping providers below are implemented against the
schema.org JSON-LD structured data that most large retailers embed in their
product pages for search engines. They are unit-tested against saved fixture
HTML only — they have NOT been verified against live pages. Live markup
drifts, bot walls appear, and prices move; treat live results as
best-effort and sanity-check anything that looks wrong before acting on it.
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PriceSample:
    price: float
    currency: str
    in_stock: bool


class Provider(Protocol):
    """Structural contract every provider follows."""

    name: str

    def matches(self, url: str) -> bool:
        """True if this provider handles the given product URL."""
        ...

    def fetch(self, url: str) -> PriceSample:
        """Download the product page and extract the current price."""
        ...


_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Stores that are known to block unauthenticated scraping. Costco.ca, for
# example, hides prices behind a membership login, so there is nothing
# useful for a scraper to read. These resolve to ManualProvider instead.
_MANUAL_DOMAINS = ("costco.ca", "costco.com")


def _walk_offers(node):
    """Yield every dict in a JSON-LD tree that looks like a schema.org Offer."""
    if isinstance(node, dict):
        kind = node.get("@type")
        kinds = kind if isinstance(kind, list) else [kind]
        if "Offer" in kinds or "AggregateOffer" in kinds:
            yield node
        for value in node.values():
            yield from _walk_offers(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_offers(item)


def _offer_price(offer: dict) -> float | None:
    raw = offer.get("price", offer.get("lowPrice"))
    if raw is None:
        return None
    try:
        return float(str(raw).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _offer_in_stock(offer: dict) -> bool:
    availability = str(offer.get("availability", ""))
    return "OutOfStock" not in availability and "SoldOut" not in availability


class JsonLdProvider:
    """Generic provider: parse schema.org JSON-LD ``Offer`` blocks.

    This works on many retailers (Best Buy, Walmart, Amazon, manufacturer
    stores) because they embed this data for search engines. Fixture-tested
    only — see the module docstring.
    """

    name = "jsonld"

    def matches(self, url: str) -> bool:
        return url.startswith("http://") or url.startswith("https://")

    def fetch(self, url: str) -> PriceSample:
        return self.parse(self._download(url))

    def _download(self, url: str) -> str:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": _BROWSER_UA, "Accept-Language": "en-CA,en;q=0.9"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")

    def parse(self, html: str) -> PriceSample:
        """Extract the best offer from JSON-LD blocks in saved HTML.

        Split out from :meth:`fetch` so tests can run without network.
        """
        blocks = re.findall(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html,
            re.DOTALL | re.IGNORECASE,
        )
        offers = []
        for block in blocks:
            try:
                offers.extend(_walk_offers(json.loads(block.strip())))
            except json.JSONDecodeError:
                continue
        priced = [(offer, _offer_price(offer)) for offer in offers]
        priced = [(offer, price) for offer, price in priced if price is not None]
        if not priced:
            raise ValueError("no priced Offer found in page JSON-LD")
        # Marketplace listings often carry several offers; prefer in-stock
        # ones, then take the lowest price.
        in_stock = [(o, p) for o, p in priced if _offer_in_stock(o)]
        offer, price = min(in_stock or priced, key=lambda item: item[1])
        currency = str(offer.get("priceCurrency", "CAD"))
        return PriceSample(
            price=price, currency=currency, in_stock=_offer_in_stock(offer)
        )


class BestBuyCAProvider(JsonLdProvider):
    """Best Buy Canada.

    Best Buy product pages embed JSON-LD offers; the generic parsing rules
    apply, including the lowest-in-stock-offer preference for marketplace
    listings. Fixture-tested only — not verified against live Best Buy
    pages.
    """

    name = "bestbuy-ca"

    def matches(self, url: str) -> bool:
        return "bestbuy.ca" in url.lower()


class WalmartCAProvider(JsonLdProvider):
    """Walmart Canada.

    Same JSON-LD approach as the generic provider. Walmart's marketplace
    listings can surface third-party seller offers, so the parsed price is
    the lowest in-stock offer found — check who the seller is before
    treating it as the headline price. Fixture-tested only.
    """

    name = "walmart-ca"

    def matches(self, url: str) -> bool:
        return "walmart.ca" in url.lower()


class ManualProvider:
    """For stores that bot-wall scrapers.

    Costco.ca is the canonical example: prices sit behind a membership
    login, so there is nothing honest for a scraper to report. Track the
    product and log prices by hand::

        pricepulse record "Galaxy S26 FE" 865.99

    (Tip: same-day delivery apps like Instacart list Costco inventory with
    visible prices and no login — handy for filling these in.)
    """

    name = "manual"

    def matches(self, url: str) -> bool:
        return False  # never auto-selected; used as an explicit fallback

    def fetch(self, url: str) -> PriceSample:
        raise RuntimeError(
            "manual provider has no scraper — "
            "use `pricepulse record <name> <price>` instead"
        )


PROVIDERS: list[Provider] = [
    BestBuyCAProvider(),
    WalmartCAProvider(),
    JsonLdProvider(),
]


def resolve_provider(url: str) -> Provider:
    """Pick the best provider for a URL, falling back to manual entry."""
    lowered = url.lower()
    if any(domain in lowered for domain in _MANUAL_DOMAINS):
        return ManualProvider()
    for provider in PROVIDERS:
        if provider.matches(url):
            return provider
    return ManualProvider()
