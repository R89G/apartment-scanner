from dataclasses import dataclass, field


@dataclass
class Listing:
    url: str
    source_site: str
    date_found: str                      # ISO date string YYYY-MM-DD
    neighborhood: str | None
    street: str | None
    floor: int | None
    rooms: float | None                  # can be 2.5, 3, etc.
    size_sqm: int | None
    price_nis: int | None
    property_status: str | None          # Hebrew condition string, e.g. "משופץ", "נדלן חדש"
    notes: list[str] = field(default_factory=list)
    is_old_north: bool | None = None
    city: str | None = None
    floors_in_building: int | None = None
    has_elevator: bool | None = None
    has_parking: bool | None = None
    date_published: str | None = None
