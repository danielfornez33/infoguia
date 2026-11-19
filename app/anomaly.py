from dataclasses import dataclass, field

from bs4 import BeautifulSoup

CAPTCHA_INDICATORS = [
    "g-recaptcha",
    "cf-turnstile",
    "h-captcha",
    "challenge-platform",
    "just a moment",
    "enable javascript and cookies to continue",
    "checking your browser before accessing",
    "attention required: access denied",
    "ray id",
]

EMPTY_PAGE_INDICATORS = [
    "page not found",
    "404",
    "not found",
    "no results",
    "temporarily unavailable",
    "maintenance",
    "error 5",
]

STRUCTURE_MARKERS = [
    "div.box-announce",
    "a.ads-text-link",
    "h1#companyName",
    "[data-branch-idbranch]",
    "a.social-network-stats",
]


@dataclass
class AnomalyDetection:
    captcha_detected: bool = False
    captcha_type: str = ""
    empty_page: bool = False
    structure_changed: bool = False
    missing_markers: list[str] = field(default_factory=list)
    reason: str = ""

    @property
    def is_anomalous(self) -> bool:
        return self.captcha_detected or self.empty_page or self.structure_changed


def detect_captcha(html: str) -> tuple[bool, str]:
    lower = html.lower()
    for indicator in CAPTCHA_INDICATORS:
        if indicator in lower:
            return True, indicator
    return False, ""


def detect_empty_page(html: str, soup: BeautifulSoup | None = None) -> bool:
    if not html or len(html.strip()) < 100:
        return True
    text_lower = html.lower()
    for indicator in EMPTY_PAGE_INDICATORS:
        if indicator in text_lower:
            soup = soup or BeautifulSoup(html, "lxml")
            body_text = soup.get_text(" ", strip=True).lower()
            if len(body_text) < 500:
                return True
    return False


def detect_structure_changes(html: str, expected_markers: list[str] | None = None) -> tuple[bool, list[str]]:
    markers = expected_markers or STRUCTURE_MARKERS
    soup = BeautifulSoup(html, "lxml")
    missing: list[str] = []
    for marker in markers:
        try:
            found = soup.select(marker)
            if not found:
                missing.append(marker)
        except Exception:
            missing.append(marker)
    if len(missing) > len(markers) * 0.5:
        return True, missing
    return False, missing


def detect_listing_structure(html: str) -> tuple[bool, list[str]]:
    return detect_structure_changes(
        html,
        [
            "div.box-announce",
            "a.ads-text-link",
            'section[aria-labelledby^="direccion-empresa"]',
            'section[aria-labelledby^="telefonos-empresa"]',
        ],
    )


def detect_profile_structure(html: str) -> tuple[bool, list[str]]:
    return detect_structure_changes(
        html,
        [
            "h1#companyName",
            "[data-branch-idbranch]",
            "a.social-network-stats",
        ],
    )


def analyze_response(html: str, kind: str = "listing") -> AnomalyDetection:
    result = AnomalyDetection()

    captcha_found, captcha_type = detect_captcha(html)
    if captcha_found:
        result.captcha_detected = True
        result.captcha_type = captcha_type
        result.reason = f"captcha detected: {captcha_type}"
        return result

    if detect_empty_page(html):
        result.empty_page = True
        result.reason = "empty or error page"
        return result

    if kind == "listing":
        changed, missing = detect_listing_structure(html)
    elif kind == "profile":
        changed, missing = detect_profile_structure(html)
    else:
        changed, missing = False, []

    if changed:
        result.structure_changed = True
        result.missing_markers = missing
        result.reason = f"structure changed, missing: {', '.join(missing[:3])}"

    return result
