"""Shared extraction helpers used across multiple scrapers."""

import re


_STATUS_KEYWORDS = [
    "נדלן חדש",
    "חדש מקבלן",
    "דירה חדשה",
    "משופצת לגמרי",   # feminine
    "משופצת חלקית",   # feminine
    "משופצת",         # feminine (ץ vs צת differ in Hebrew — must list separately)
    "משופץ לגמרי",
    "משופץ חלקית",
    "משופץ",
    "שיפוץ",
    "חדש",
]

_ELEVATOR_KEYWORDS = ["מעלית"]
_PARKING_KEYWORDS = ["חניה", "חנייה", "חנייון"]


def extract_property_status(text: str) -> str | None:
    """Return the first matching condition keyword found in text, or None."""
    if not text:
        return None
    for kw in _STATUS_KEYWORDS:
        if kw in text:
            return kw
    return None


def extract_elevator(text: str) -> bool | None:
    """Return True if elevator keyword found, None otherwise."""
    if not text:
        return None
    return True if any(kw in text for kw in _ELEVATOR_KEYWORDS) else None


def extract_parking(text: str) -> bool | None:
    """Return True if parking keyword found, None otherwise."""
    if not text:
        return None
    return True if any(kw in text for kw in _PARKING_KEYWORDS) else None


def extract_floors_in_building(text: str) -> int | None:
    """Parse total building floors from patterns like 'מתוך 5' or 'בן 6 קומות'."""
    if not text:
        return None
    m = re.search(r"מתוך\s+(\d+)", text)
    if m:
        return int(m.group(1))
    m = re.search(r"בן\s+(\d+)\s+קומות", text)
    if m:
        return int(m.group(1))
    return None


# ── Detail-page extraction ─────────────────────────────────────────────────────

def parse_detail_text(raw: str) -> dict:
    """
    Extract structured fields from the full plain-text of a listing detail page.

    Handles both label-first ("קומה 3") and value-first ("3\\nקומה") layouts,
    which differ across sites due to RTL CSS rendering artefacts in inner_text().

    Returns a dict with zero or more of:
        floor, floors_in_building, property_status,
        has_elevator, has_parking, date_published
    """
    # Truncate at "similar listings" section so neighbour data doesn't bleed in.
    # Require the colon to avoid cutting on sites that use "מודעות דומות" as a nav tab label.
    text = re.split(r"מודעות דומות\s*:", raw)[0]

    out: dict = {}

    # ── Floor + total floors ──────────────────────────────────────────────────
    # Priority 1: "קומה X מתוך Y"
    m = re.search(r"קומה\s+(\d+)\s+מתוך\s+(\d+)", text)
    if m:
        out["floor"] = int(m.group(1))
        out["floors_in_building"] = int(m.group(2))
    else:
        # Priority 2: "קומה X/Y"
        m = re.search(r"קומה\s*:?\s*(\d+)\s*/\s*(\d+)", text)
        if m:
            out["floor"] = int(m.group(1))
            out["floors_in_building"] = int(m.group(2))
        else:
            # Priority 3: value-before-label RTL layout  "X\nקומה"
            m = re.search(r"\b(\d+)\s*\n\s*קומה\b", text)
            if m:
                out["floor"] = int(m.group(1))
            else:
                # Priority 4: inline "קומה X" without total
                m = re.search(r"קומה\s*:?\s*(\d+)", text)
                if m:
                    out["floor"] = int(m.group(1))

    # Total floors if not already found
    if "floors_in_building" not in out:
        # "קומות בבניין\n8 קומות"  or  "בניינים בני 8 קומות"
        m = re.search(r"קומות\s+בבניין\s*\n*(\d+)", text)
        if m:
            out["floors_in_building"] = int(m.group(1))
        else:
            m = re.search(r"בני\s+(\d+)\s+קומות", text)
            if m:
                out["floors_in_building"] = int(m.group(1))

    # ── Floor fallback: "בקומה ה-29" description-embedded pattern (Homeland) ──
    if "floor" not in out:
        m = re.search(r"בקומה\s+ה-?(\d+)", text)
        if m:
            out["floor"] = int(m.group(1))

    # ── Property status ───────────────────────────────────────────────────────
    # "מצב הנכס\nבמצב שמור"  or  "מצב הנכס: ..."
    m = re.search(r"מצב\s+הנכס\s*:?\s*\n*([^\n\r]{2,40})", text)
    if m:
        out["property_status"] = m.group(1).strip()

    # ── Date published ────────────────────────────────────────────────────────
    # "פורסם ב\nDD.MM.YYYY"  or  "פורסם ב: DD/MM/YY"
    m = re.search(r"פורסם\s+ב\s*:?\s*\n*([\d]{1,2}[./\-][\d]{1,2}[./\-][\d]{2,4})", text)
    if m:
        out["date_published"] = m.group(1).strip()

    # ── Elevator (negation-aware) ─────────────────────────────────────────────
    no_elev = bool(re.search(r"(?:אין|ללא|לא)\s+מעלית", text))
    if "מעלית" in text and not no_elev:
        out["has_elevator"] = True
    elif no_elev:
        out["has_elevator"] = False

    # ── Parking (negation-aware) ──────────────────────────────────────────────
    no_park = bool(re.search(r"(?:אין|ללא|לא)\s+חני[יה]", text))
    has_park_kw = bool(re.search(r"חני(?:ה|יה|ות|ון)", text))
    if has_park_kw and not no_park:
        out["has_parking"] = True
    elif no_park:
        out["has_parking"] = False

    return out


def apply_detail_fields(listing, detail: dict) -> None:
    """Overlay extracted detail-page fields onto a Listing; never clears an existing value."""
    mapping = {
        "floor": "floor",
        "floors_in_building": "floors_in_building",
        "property_status": "property_status",
        "has_elevator": "has_elevator",
        "has_parking": "has_parking",
        "date_published": "date_published",
    }
    for src, dst in mapping.items():
        val = detail.get(src)
        if val is not None:
            setattr(listing, dst, val)


def detail_page_blocked(text: str) -> bool:
    """Return True if the page is a bot-challenge / captcha page."""
    lc = text.lower()
    return any(kw in lc for kw in (
        "captcha", "are you for real", "cloudflare", "ray id",
        "ביצוע אימות אבטחה", "אנו מניחים שגולשים",
        "just a moment", "enable javascript", "checking your browser",
        "please enable cookies", "ddos protection", "security check",
        "verifying you are human", "please wait",
    ))


def quick_passes(listing) -> bool:
    """Lightweight pre-filter: skip obvious rejects before visiting detail pages."""
    if listing.price_nis is not None and listing.price_nis > 8000:
        return False
    if listing.rooms is not None and listing.rooms < 2:
        return False
    if listing.floor is not None and listing.floor < 2:
        return False
    return True
