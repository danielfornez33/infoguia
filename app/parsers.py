import json
import re
import unicodedata
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

PHONE_RE = re.compile(r"(?:\+?58)?[\s.\-]*\(?0?\d{3,4}\)?[\s.\-]*\d{3}[\s.\-]*\d{4}")
DIGITS_RE = re.compile(r"\D+")
SPACE_RE = re.compile(r"\s+")
STORE_LINK = 'a[href*="/shop/stores/"]'
PROFILE_LINK = 'a[href*="/is.asp"]'
PRICE_RE = re.compile(r"[\$Bs\.]+\s*[\d.,]+")
SKU_RE = re.compile(r"(?:SKU|C[oó]digo|Ref|Modelo)[\s:./\-]*([A-Za-z0-9\-]+)", re.IGNORECASE)

ADDRESS_SELECTORS = [
    'section[aria-labelledby^="direccion-empresa"] span',
    '.company-address',
    '.address',
    '[itemprop="streetAddress"]',
    '.dir-empresa',
]

PHONE_SELECTORS = [
    'section[aria-labelledby^="telefonos-empresa"] .telefono-desktop',
    'section[aria-labelledby^="telefonos-empresa"] a[href^="tel:"]',
    '.company-phone a[href^="tel:"]',
    '[itemprop="telephone"]',
    '.tel-empresa .telefono-desktop',
]

WHATSAPP_SELECTORS = [
    "a.whatsapp-click-stats",
    'a[href*="web.whatsapp.com/send"]',
    'a[href*="wa.me/"]',
    '.whatsapp-link',
    '[data-whatsapp]',
]

SCHEDULE_SELECTORS = [
    'section[aria-labelledby^="horarios-empresa"]',
    '.company-schedule',
    '.schedule',
    '[itemprop="openingHours"]',
    '.horarios-empresa',
]

CARD_SELECTORS = [
    "div.box-announce.dimensions-box-ads",
    "div.box-announce",
    ".company-card",
    ".listing-item",
    '[itemtype="http://schema.org/LocalBusiness"]',
]

NAME_SELECTORS_PROFILE = [
    "h1#companyName",
    "h1.company-name",
    "h1[itemprop='name']",
    ".profile-title h1",
    "h1",
]

DESCRIPTION_SELECTORS = [
    "#descripcion",
    ".company-description",
    ".profile-description",
    '[itemprop="description"]',
    ".desc",
    "p.desc",
]

PRODUCT_CARD_SELECTORS = [
    "article.pr-card",
    ".ps-product",
    ".product-card",
    '[itemtype="http://schema.org/Product"]',
    ".shop-product",
]

SOCIAL_SELECTORS = [
    "a.social-network-stats",
    'a[href*="instagram.com"]',
    'a[href*="facebook.com"]',
    'a[href*="twitter.com"]',
    'a[href*="x.com"]',
    'a[href*="linkedin.com"]',
    'a[href*="youtube.com"]',
    'a[href*="tiktok.com"]',
]

DAY_ORDER = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

DAY_NAMES = {
    "lunes": "monday", "lun": "monday", "lu": "monday", "mon": "monday",
    "martes": "tuesday", "mar": "tuesday", "ma": "tuesday", "tue": "tuesday",
    "miércoles": "wednesday", "miercoles": "wednesday", "mie": "wednesday",
    "mi": "wednesday", "wed": "wednesday",
    "jueves": "thursday", "jue": "thursday", "ju": "thursday", "thu": "thursday",
    "viernes": "friday", "vie": "friday", "vi": "friday", "fri": "friday",
    "sábado": "saturday", "sabado": "saturday", "sáb": "saturday",
    "sa": "saturday", "sat": "saturday",
    "domingo": "sunday", "dom": "sunday", "do": "sunday", "sun": "sunday",
}


def clean(value: str | None) -> str:
    if not value:
        return ""
    return SPACE_RE.sub(" ", value).strip()


def digits(value: str | None) -> str:
    return DIGITS_RE.sub("", value or "")


def normalize_phone(value: str | None) -> str:
    raw = str(value or "").split(";")[0]
    raw = re.sub(r"(?i)\bext\.?\b.*$", "", raw)
    number = digits(raw)
    if not number:
        return ""
    if number.startswith("0058"):
        number = number[2:]
    if number.startswith("58"):
        rest = number[2:]
        if len(rest) == 10:
            return "+58" + rest
        if len(rest) == 11 and rest.startswith("0"):
            return "+58" + rest[1:]
        return "+" + number
    if number.startswith("0"):
        if len(number) == 11:
            return "+58" + number[1:]
        if len(number) == 10:
            return "+58" + number
    if len(number) == 10:
        return "+58" + number
    return "+" + number


def normalize_name(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return SPACE_RE.sub(" ", text).strip()


def normalize_email(value: str | None) -> str:
    return (value or "").strip().lower()


def normalize_price(value: str | None) -> str:
    if not value:
        return ""
    value = clean(value)
    match = PRICE_RE.search(value)
    if match:
        return match.group(0).strip()
    return value


def split_phones(value: str | None) -> list[str]:
    found = PHONE_RE.findall(value or "")
    result: list[str] = []
    for item in found:
        normalized = normalize_phone(item)
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def text_of(node) -> str:
    if node is None:
        return ""
    return clean(node.get_text(" ", strip=True))


def first_text(nodes, skip_contains: str | None = None) -> str:
    for node in nodes:
        value = text_of(node)
        if not value:
            continue
        if skip_contains and skip_contains in value:
            continue
        return value
    return ""


def multi_select(soup, selectors: list[str], limit: int = 0):
    for selector in selectors:
        try:
            results = soup.select(selector)
            if results:
                return results[:limit] if limit else results
        except Exception:
            continue
    return []


def multi_select_all(soup, selectors: list[str], limit: int = 0):
    results = []
    seen: set[int] = set()
    for selector in selectors:
        try:
            for node in soup.select(selector):
                node_id = id(node)
                if node_id not in seen:
                    seen.add(node_id)
                    results.append(node)
        except Exception:
            continue
    return results[:limit] if limit else results


def multi_select_one(soup, selectors: list[str]):
    for selector in selectors:
        try:
            result = soup.select_one(selector)
            if result:
                return result
        except Exception:
            continue
    return None


def city_from_address(address: str) -> str:
    parts = [part.strip() for part in (address or "").split(",") if part.strip()]
    return parts[-1] if parts else ""


def urbanization_from_address(address: str) -> str:
    parts = [part.strip() for part in (address or "").split(",") if part.strip()]
    if len(parts) >= 2:
        return parts[-2]
    return ""


def network_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "instagram" in host:
        return "instagram"
    if "facebook" in host:
        return "facebook"
    if "twitter" in host or host.endswith("x.com"):
        return "x"
    if "linkedin" in host:
        return "linkedin"
    if "youtube" in host:
        return "youtube"
    if "tiktok" in host:
        return "tiktok"
    if "wa.me" in host or "whatsapp" in host:
        return "whatsapp"
    return host or "other"


def query_value(url: str, key: str) -> str | None:
    values = parse_qs(urlparse(url).query).get(key)
    return values[0] if values else None


def extract_schema_org(soup: BeautifulSoup) -> dict:
    data: dict = {}
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            parsed = json.loads(script.string or "")
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict) and item.get("@type"):
                        data[item["@type"]] = item
            elif isinstance(parsed, dict) and parsed.get("@type"):
                data[parsed["@type"]] = parsed
        except (json.JSONDecodeError, TypeError):
            continue
    return data


def extract_sku(node) -> str:
    for attr in ("data-sku", "data-product-sku", "data-item-sku"):
        value = node.get(attr)
        if value:
            return clean(value)
    text = text_of(node)
    match = SKU_RE.search(text)
    if match:
        return match.group(1)
    return ""


def extract_availability(node) -> str:
    for selector in ('[itemprop="availability"]', ".availability", ".stock", ".product-stock"):
        try:
            el = node.select_one(selector)
            if el:
                text = text_of(el).lower()
                if "disponible" in text or "available" in text or "in stock" in text:
                    return "in_stock"
                if "agotado" in text or "out of stock" in text or "unavailable" in text:
                    return "out_of_stock"
                return text
        except Exception:
            continue
    return ""


def parse_schedule_text(raw: str) -> dict:
    result = {"days": [], "twenty_four_seven": False, "raw_text": raw}
    lower = (raw or "").lower().strip()
    if not lower:
        return result
    if "24/7" in lower or "24 horas" in lower or "todos los días" in lower or "todos los dias" in lower:
        result["twenty_four_seven"] = True
        return result

    time_re = re.compile(r"(\d{1,2}[:\.]?\d{0,2}\s*(?:am|pm|a\.m\.|p\.m\.)?)", re.IGNORECASE)
    day_pattern = re.compile(
        r"\b(" + "|".join(re.escape(d) for d in sorted(DAY_NAMES.keys(), key=len, reverse=True)) + r")\.?\b",
        re.IGNORECASE,
    )

    day_schedule: dict[str, dict] = {}
    segments = day_pattern.split(lower)

    i = 0
    while i < len(segments):
        seg = segments[i].strip()
        if day_pattern.match(seg):
            day_en = DAY_NAMES.get(seg.lower())
            if not day_en:
                i += 1
                continue
            time_text = ""
            if i + 1 < len(segments):
                next_seg = segments[i + 1]
                is_range = bool(re.match(r"\s*(a|al|to|-|–|—)\s*", next_seg, re.IGNORECASE))
                if is_range and i + 3 < len(segments):
                    end_day_str = segments[i + 2].strip()
                    end_day_en = DAY_NAMES.get(end_day_str.lower())
                    if end_day_en:
                        time_text = segments[i + 3] if i + 3 < len(segments) else ""
                        start_idx = DAY_ORDER.index(day_en)
                        end_idx = DAY_ORDER.index(end_day_en)
                        if start_idx <= end_idx:
                            days_range = DAY_ORDER[start_idx:end_idx + 1]
                        else:
                            days_range = DAY_ORDER[start_idx:] + DAY_ORDER[:end_idx + 1]
                        times = time_re.findall(time_text)
                        is_closed = "cerrado" in time_text.lower() or "closed" in time_text.lower()
                        for d in days_range:
                            if is_closed:
                                day_schedule[d] = {"day": d, "open": "", "close": "", "is_closed": True}
                            elif len(times) >= 2:
                                day_schedule[d] = {"day": d, "open": times[0].strip(), "close": times[1].strip()}
                            elif len(times) == 1:
                                day_schedule[d] = {"day": d, "open": times[0].strip(), "close": ""}
                            else:
                                day_schedule[d] = {"day": d, "open": "", "close": ""}
                        i += 4
                        continue
                    time_text = next_seg
                else:
                    time_text = next_seg
            times = time_re.findall(time_text)
            is_closed = "cerrado" in time_text.lower() or "closed" in time_text.lower()
            if is_closed:
                day_schedule[day_en] = {"day": day_en, "open": "", "close": "", "is_closed": True}
            elif len(times) >= 2:
                day_schedule[day_en] = {"day": day_en, "open": times[0].strip(), "close": times[1].strip()}
            elif len(times) == 1:
                day_schedule[day_en] = {"day": day_en, "open": times[0].strip(), "close": ""}
            else:
                day_schedule[day_en] = {"day": day_en, "open": "", "close": ""}
            i += 2
        else:
            i += 1

    result["days"] = [day_schedule[d] for d in DAY_ORDER if d in day_schedule]
    return result


def extract_address_enriched(card) -> dict:
    address = ""
    urbanization = ""
    for selector in ADDRESS_SELECTORS:
        try:
            nodes = card.select(selector)
            if nodes:
                address = first_text(nodes, skip_contains="(+")
                if not urbanization:
                    urbanization = urbanization_from_address(address)
                break
        except Exception:
            continue
    if not address:
        schema = card.select_one('[itemprop="address"]')
        if schema:
            street = schema.select_one('[itemprop="streetAddress"]')
            if street:
                address = text_of(street)
    return {"address": address, "urbanization": urbanization, "city": city_from_address(address)}


def build_company(card, cat_id: str | None, page_url: str) -> dict | None:
    link = multi_select_one(card, [
        "a.ads-text-link",
        'a[href*="/is.asp"]',
        "a.company-link",
        'a[itemprop="url"]',
    ])
    if link is None:
        return None
    href = link.get("href")
    if not href:
        return None
    profile_url = urljoin(page_url, href)
    clte = link.get("data-company")
    if not clte:
        clte = query_value(profile_url, "clte")
    if not clte:
        clte = query_value(profile_url, "emp")
    if not clte:
        return None

    addr_info = extract_address_enriched(card)
    address = addr_info["address"]
    city = addr_info["city"]

    schedule_node = multi_select_one(card, SCHEDULE_SELECTORS)
    schedule = text_of(schedule_node) if schedule_node else ""

    description = text_of(multi_select_one(card, DESCRIPTION_SELECTORS))

    display_phones: list[str] = []
    for node in multi_select(card, PHONE_SELECTORS):
        value = text_of(node)
        if value:
            display_phones.extend(split_phones(value) or [value])
        tel_href = node.get("href", "")
        if tel_href.startswith("tel:"):
            display_phones.extend(split_phones(tel_href[4:]) or [tel_href[4:]])

    display_whatsapp: list[str] = []
    for node in multi_select(card, WHATSAPP_SELECTORS):
        value = node.get("data-phone-number") or node.get("data-whatsapp") or ""
        if value:
            display_whatsapp.extend(split_phones(value) or [value])
        href = node.get("href", "")
        if "web.whatsapp.com/send" in href:
            phone = query_value(href, "phone")
            if phone:
                display_whatsapp.extend(split_phones(phone) or [phone])
        elif "wa.me/" in href:
            phone = href.split("wa.me/")[-1].split("?")[0]
            if phone:
                display_whatsapp.extend(split_phones(phone) or [phone])

    phones = list(dict.fromkeys(display_phones))
    whatsapp = list(dict.fromkeys(display_whatsapp))

    rating = extract_rating(card)
    store = card.select_one(STORE_LINK)
    contacts = []
    for value in phones:
        contacts.append({"type": "phone", "value": value})
    for value in whatsapp:
        contacts.append({"type": "whatsapp", "value": value})

    return {
        "clte": clte,
        "name": text_of(link),
        "profile_url": profile_url,
        "address": address,
        "city": city,
        "schedule": schedule,
        "phones": phones,
        "whatsapp": whatsapp,
        "contacts": contacts,
        "rating_pct": rating,
        "verified": card.select_one("img.btn-verified-customer") is not None
        or card.select_one(".verified-badge") is not None,
        "description": description,
        "store_url": urljoin(page_url, store.get("href")) if store else "",
        "cat_id": cat_id,
    }


def extract_rating(card) -> float | None:
    rating_node = multi_select_one(card, [
        ".star-rating-precise",
        ".star-rating",
        ".rating",
        '[itemprop="aggregateRating"]',
    ])
    if not rating_node:
        return None
    style = rating_node.get("style", "")
    match = re.search(r"--rating:\s*([\d.]+)%", style)
    if match:
        return float(match.group(1))
    width = rating_node.get("data-width") or rating_node.get("style", "")
    match = re.search(r"width:\s*([\d.]+)", str(width))
    if match:
        return float(match.group(1))
    value = rating_node.get("data-rating") or rating_node.get("content")
    if value:
        try:
            return float(value)
        except (ValueError, TypeError):
            pass
    text = text_of(rating_node)
    match = re.search(r"([\d.]+)\s*/\s*([\d.]+)", text)
    if match:
        try:
            return float(match.group(1)) / float(match.group(2)) * 100
        except (ValueError, ZeroDivisionError):
            pass
    match = re.search(r"([\d.]+)\s*(?:de|/|★)\s*([\d.]+)?", text)
    if match:
        try:
            rating_val = float(match.group(1))
            max_val = float(match.group(2) or "5")
            return rating_val / max_val * 100
        except (ValueError, ZeroDivisionError):
            pass
    return None


def parse_listing(html: str, page_url: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    cat_id = query_value(page_url, "cat")

    companies = []
    cards = multi_select(soup, CARD_SELECTORS)
    for card in cards:
        company = build_company(card, cat_id, page_url)
        if company:
            companies.append(company)

    next_pages: list[str] = []
    for node in soup.select(".pagination a.other-pages, .pagination a[href], a.next-page, a[rel='next']"):
        href = node.get("href")
        if href:
            url = urljoin(page_url, href)
            if url not in next_pages and url != page_url:
                next_pages.append(url)

    discovered: list[str] = []
    categories: dict[str, str] = {}
    for node in soup.select('a[href*="/ct.asp"]'):
        href = node.get("href")
        if not href:
            continue
        url = urljoin(page_url, href)
        if url not in discovered:
            discovered.append(url)
        category_id = query_value(url, "cat")
        if category_id:
            title = clean(node.get("title") or node.get_text(" ", strip=True))
            if title:
                categories[category_id] = title

    return {
        "companies": companies,
        "next_pages": next_pages,
        "discovered": discovered,
        "categories": [{"cat_id": key, "name": value} for key, value in categories.items()],
    }


def extract_branches_enriched(soup: BeautifulSoup) -> list[dict]:
    branches: dict[str, dict] = {}
    for node in soup.select("[data-branch-idbranch]"):
        branch_key = node.get("data-branch-idbranch") or "0"
        if branch_key in branches:
            continue
        address = clean(node.get("data-branch-address"))
        urbanization = clean(node.get("data-branch-urbanization"))
        email = normalize_email(node.get("data-branch-email"))
        phone_text = node.get("data-branch-phone") or ""
        whatsapp_text = node.get("data-branch-whatsapp") or ""
        phones = split_phones(phone_text)
        whatsapp = split_phones(whatsapp_text)
        contacts = [{"type": "phone", "value": value} for value in phones]
        contacts.extend({"type": "whatsapp", "value": value} for value in whatsapp)
        if email:
            contacts.append({"type": "email", "value": email})
        branches[branch_key] = {
            "branch_key": branch_key,
            "urbanization": urbanization,
            "address": address,
            "city": city_from_address(address),
            "phones": " ".join(phones),
            "whatsapp": " ".join(whatsapp),
            "email": email,
            "contacts": contacts,
        }
    return list(branches.values())


def extract_full_description(soup: BeautifulSoup) -> str:
    modal_desc = soup.select_one("#fullDescription .modal-description-text")
    if modal_desc:
        return clean(modal_desc.get_text(strip=True))
    return ""


def extract_categories_from_profile(soup: BeautifulSoup) -> list[dict]:
    categories = []
    seen_ids: set[str] = set()
    for node in soup.select(".profile-sec-categories-btns a[href*='/ct.asp']"):
        href = node.get("href")
        if not href:
            continue
        title = clean(node.get("title") or node.get_text(strip=True))
        if not title:
            continue
        category_id = query_value(href, "cat")
        if category_id and category_id not in seen_ids:
            seen_ids.add(category_id)
            categories.append({"cat_id": category_id, "name": title})
    return categories


def extract_socials_enriched(soup: BeautifulSoup) -> list[dict]:
    socials = []
    seen_urls: set[str] = set()
    for node in multi_select_all(soup, SOCIAL_SELECTORS):
        href = node.get("href")
        if not href or not href.startswith("http"):
            continue
        if href in seen_urls:
            continue
        seen_urls.add(href)
        socials.append({"network": network_from_url(href), "url": href})
    return socials


def extract_categories_from_profile(soup: BeautifulSoup) -> list[dict]:
    categories = []
    seen_ids: set[str] = set()
    # Buscar específicamente en la sección de categorías del perfil
    for node in soup.select(".profile-sec-categories-btns a[href*='/ct.asp']"):
        href = node.get("href")
        if not href:
            continue
        category_id = query_value(href, "cat")
        title = clean(node.get("title") or node.get_text(strip=True))
        if category_id and title and category_id not in seen_ids:
            seen_ids.add(category_id)
            categories.append({"cat_id": category_id, "name": title})
    return categories


def extract_categories_enriched(soup: BeautifulSoup, page_url: str) -> list[dict]:
    categories = []
    seen_ids: set[str] = set()
    for node in soup.select('a[href*="/ct.asp"]'):
        href = node.get("href")
        if not href:
            continue
        category_id = query_value(urljoin(page_url, href), "cat")
        if not category_id or category_id in seen_ids:
            continue
        title = clean(node.get("title") or node.get_text(" ", strip=True))
        if title:
            seen_ids.add(category_id)
            categories.append({"cat_id": category_id, "name": title})
    return categories


def parse_products(soup: BeautifulSoup, page_url: str) -> list[dict]:
    products: list[dict] = []
    seen: set[str] = set()

    for node in multi_select_all(soup, PRODUCT_CARD_SELECTORS):
        title = text_of(
            node.select_one(".pr-card-title")
            or node.select_one(".ps-product__title")
            or node.select_one(".product-title")
            or node.select_one('[itemprop="name"]')
            or node.select_one("h3, h4")
        )
        if not title or title in seen:
            continue
        seen.add(title)
        image = node.select_one("img")
        image_url = ""
        if image:
            image_url = (
                image.get("data-src")
                or image.get("data-lazy-src")
                or image.get("data-original")
                or image.get("src")
                or ""
            )
        link = node.select_one("a[href]")
        price_node = node.select_one(".ps-product__price") or node.select_one(".price")
        price_node = price_node or node.select_one('[itemprop="price"]')
        price = normalize_price(text_of(price_node)) if price_node else ""
        sku = extract_sku(node)
        description = text_of(
            node.select_one(".product-description")
            or node.select_one(".pr-card-desc")
            or node.select_one('[itemprop="description"]')
        )
        availability = extract_availability(node)
        products.append({
            "name": title,
            "price": price,
            "image_url": image_url if isinstance(image_url, str) else "",
            "url": urljoin(page_url, link.get("href")) if link and link.get("href") else "",
            "sku": sku,
            "description": description,
            "availability": availability,
        })

    return products


def extract_full_description(soup: BeautifulSoup) -> str:
    modal_desc = soup.select_one("#fullDescription .modal-description-text")
    if modal_desc:
        return clean(modal_desc.get_text(strip=True))
    return ""


def extract_structured_schedule(soup: BeautifulSoup) -> dict | None:
    schedule_node = multi_select_one(soup, SCHEDULE_SELECTORS)
    if not schedule_node:
        return None
    raw = text_of(schedule_node)
    if not raw:
        return None
    parsed = parse_schedule_text(raw)
    return parsed


def extract_meta_description(soup: BeautifulSoup) -> str:
    meta = soup.select_one('meta[name="description"]')
    if meta:
        desc = clean(meta.get("content"))
        if desc:
            return desc
    og = soup.select_one('meta[property="og:description"]')
    if og:
        desc = clean(og.get("content"))
        if desc:
            return desc
    return ""


def parse_profile(html: str, page_url: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    name = text_of(multi_select_one(soup, NAME_SELECTORS_PROFILE))
    branches = extract_branches_enriched(soup)
    socials = extract_socials_enriched(soup)
    
    # Extraer categorías del perfil (más específico que el general)
    categories = extract_categories_from_profile(soup)
    if not categories:
        categories = extract_categories_enriched(soup, page_url)
    
    products = parse_products(soup, page_url)

    store = soup.select_one(STORE_LINK)
    store_url = urljoin(page_url, store.get("href")) if store and store.get("href") else ""

    # Priorizar descripción completa del modal
    description = extract_full_description(soup)
    if not description:
        description = extract_meta_description(soup)
    if not description:
        desc_node = multi_select_one(soup, DESCRIPTION_SELECTORS)
        description = text_of(desc_node)

    rating = extract_rating(soup)
    verified = (
        soup.select_one("img.btn-verified-customer") is not None
        or soup.select_one(".verified-badge") is not None
    )

    schedule = extract_structured_schedule(soup)
    schema_data = extract_schema_org(soup)

    return {
        "name": name,
        "description": description,
        "verified": verified,
        "rating_pct": rating,
        "store_url": store_url,
        "branches": branches,
        "socials": socials,
        "categories": categories,
        "products": products,
        "schedule": schedule,
        "schema_data": schema_data,
    }


def parse_store(html: str, page_url: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    title = text_of(
        soup.select_one("h2.fs-text-1")
        or soup.select_one("h1.store-name")
        or soup.select_one("h1")
    )
    return {"name": title, "products": parse_products(soup, page_url)}
