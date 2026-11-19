from abc import ABC, abstractmethod
from urllib.parse import urlparse

from . import parsers


class BaseSiteAdapter(ABC):
    domain: str

    @abstractmethod
    def detect_kind(self, url: str) -> str: ...

    @abstractmethod
    def get_listing_selectors(self) -> dict: ...

    @abstractmethod
    def parse_listing(self, html: str, url: str) -> dict: ...

    @abstractmethod
    def parse_profile(self, html: str, url: str) -> dict: ...

    @abstractmethod
    def parse_store(self, html: str, url: str) -> dict: ...

    @abstractmethod
    def get_listing_urls(self, html: str, url: str) -> list[str]: ...

    @abstractmethod
    def get_company_profile_url(self, card_data: dict) -> str: ...

    @abstractmethod
    def get_company_store_url(self, card_data: dict) -> str: ...

    @abstractmethod
    def build_company(self, card, cat_id, url): ...


class InfoGuiaAdapter(BaseSiteAdapter):
    domain = "infoguia.com"

    def detect_kind(self, url: str) -> str:
        if "/is.asp" in url:
            return "profile"
        if "/shop/stores/" in url:
            return "store"
        return "listing"

    def get_listing_selectors(self) -> dict:
        return {
            "card": parsers.CARD_SELECTORS,
            "address": parsers.ADDRESS_SELECTORS,
            "phone": parsers.PHONE_SELECTORS,
            "whatsapp": parsers.WHATSAPP_SELECTORS,
            "schedule": parsers.SCHEDULE_SELECTORS,
            "description": parsers.DESCRIPTION_SELECTORS,
            "social": parsers.SOCIAL_SELECTORS,
            "product_card": parsers.PRODUCT_CARD_SELECTORS,
            "name_profile": parsers.NAME_SELECTORS_PROFILE,
        }

    def parse_listing(self, html: str, url: str) -> dict:
        return parsers.parse_listing(html, url)

    def parse_profile(self, html: str, url: str) -> dict:
        return parsers.parse_profile(html, url)

    def parse_store(self, html: str, url: str) -> dict:
        return parsers.parse_store(html, url)

    def get_listing_urls(self, html: str, url: str) -> list[str]:
        data = parsers.parse_listing(html, url)
        return data["next_pages"]

    def get_company_profile_url(self, card_data: dict) -> str:
        return card_data.get("profile_url", "")

    def get_company_store_url(self, card_data: dict) -> str:
        return card_data.get("store_url", "")

    def build_company(self, card, cat_id, url):
        return parsers.build_company(card, cat_id, url)


ADAPTERS: dict[str, BaseSiteAdapter] = {
    "infoguia.com": InfoGuiaAdapter(),
}


def get_adapter(domain: str) -> BaseSiteAdapter:
    adapter = ADAPTERS.get(domain)
    if adapter is None:
        raise ValueError(f"No adapter registered for domain: {domain}")
    return adapter


def get_adapter_for_url(url: str) -> BaseSiteAdapter:
    domain = urlparse(url).netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    for registered_domain, adapter in ADAPTERS.items():
        if domain == registered_domain or domain.endswith("." + registered_domain):
            return adapter
    raise ValueError(f"No adapter found for URL: {url}")
