import logging
import os
import time

import gspread
from google.oauth2.service_account import Credentials

from models.listing import Listing

logger = logging.getLogger(__name__)

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

HEADERS = [
    "Date Found",
    "Source Site",
    "Neighborhood",
    "Street",
    "Floor",
    "Rooms",
    "Size (sqm)",
    "Price (NIS)",
    "Property Status",
    "Old North",
    "Floors in Building",
    "URL",
    "Notes",
    "Elevator",
    "Parking",
    "Date Published",
]


def _get_client(creds_path: str) -> gspread.Client:
    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    return gspread.authorize(creds)


def get_or_create_sheet(creds_path: str, sheet_name: str) -> gspread.Worksheet:
    client = _get_client(creds_path)
    try:
        spreadsheet = client.open(sheet_name)
        logger.info("Opened spreadsheet: %s", sheet_name)
    except gspread.SpreadsheetNotFound:
        raise RuntimeError(
            f"Google Sheet '{sheet_name}' was not found. "
            "Check that:\n"
            "  1. The sheet name in your .env (GOOGLE_SHEET_NAME) matches exactly.\n"
            "  2. The sheet is shared with the service account email in google_credentials.json."
        )
    return spreadsheet.sheet1


def ensure_header(ws: gspread.Worksheet) -> None:
    existing = ws.row_values(1)
    if existing == HEADERS:
        return
    ws.update("A1:P1", [HEADERS])
    ws.freeze(rows=1)
    header_format = {
        "textFormat": {"bold": True},
        "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.9},
    }
    ws.format("A1:P1", header_format)
    logger.info("Header row written and formatted")


def _listing_to_row(listing: Listing) -> list:
    elevator = (
        "Yes" if listing.has_elevator is True
        else "No" if listing.has_elevator is False
        else "Unknown"
    )
    parking = (
        "Yes" if listing.has_parking is True
        else "No" if listing.has_parking is False
        else "Unknown"
    )
    return [
        listing.date_found,
        listing.source_site,
        listing.neighborhood or "",
        listing.street or "",
        listing.floor if listing.floor is not None else "Unknown",
        listing.rooms if listing.rooms is not None else "",
        listing.size_sqm if listing.size_sqm is not None else "Unknown",
        listing.price_nis if listing.price_nis is not None else "Unknown",
        listing.property_status or "Unknown",
        "Yes" if listing.is_old_north else "No",
        listing.floors_in_building if listing.floors_in_building is not None else "Unknown",
        listing.url,
        ", ".join(listing.notes),
        elevator,
        parking,
        listing.date_published or "Unknown",
    ]


def append_listing(ws: gspread.Worksheet, listing: Listing) -> None:
    ws.append_row(_listing_to_row(listing), value_input_option="USER_ENTERED")
    logger.debug("Appended listing: %s", listing.url)


def _append_rows_with_retry(
    ws: gspread.Worksheet,
    rows: list,
    max_retries: int = 3,
    retry_wait: int = 5,
) -> None:
    for attempt in range(max_retries):
        try:
            ws.append_rows(rows, value_input_option="USER_ENTERED")
            return
        except gspread.exceptions.APIError as exc:
            if "429" in str(exc) and attempt < max_retries - 1:
                logger.warning(
                    "Sheets 429 rate limit hit — waiting %ds before retry (attempt %d/%d)",
                    retry_wait, attempt + 1, max_retries,
                )
                time.sleep(retry_wait)
            else:
                raise


def append_listings_batch(
    ws: gspread.Worksheet,
    listings: list[Listing],
    batch_size: int = 10,
    delay_seconds: float = 2.0,
) -> None:
    """Write listings in batches to stay within Sheets API rate limits (429)."""
    total = len(listings)
    for start in range(0, total, batch_size):
        batch = listings[start : start + batch_size]
        rows = [_listing_to_row(l) for l in batch]
        _append_rows_with_retry(ws, rows)
        end = min(start + batch_size, total)
        logger.debug("Wrote rows %d–%d of %d", start + 1, end, total)
        if end < total:
            time.sleep(delay_seconds)


def resize_columns(ws: gspread.Worksheet) -> None:
    try:
        spreadsheet = ws.spreadsheet
        sheet_id = ws.id
        requests = [
            {
                "autoResizeDimensions": {
                    "dimensions": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": 0,
                        "endIndex": 16,
                    }
                }
            }
        ]
        spreadsheet.batch_update({"requests": requests})
        logger.debug("Columns auto-resized")
    except Exception as exc:
        logger.warning("Could not auto-resize columns: %s", exc)


def get_sheet_url(ws: gspread.Worksheet) -> str:
    return f"https://docs.google.com/spreadsheets/d/{ws.spreadsheet.id}"
