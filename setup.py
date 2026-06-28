"""
One-time setup script. Run this before the first automated scan.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent


def step(n: int, msg: str) -> None:
    print(f"\n[Step {n}] {msg}")


def ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def print_google_cloud_instructions() -> None:
    print("""
╔══════════════════════════════════════════════════════════════════╗
║        Google Cloud Setup — One-Time Manual Steps               ║
╚══════════════════════════════════════════════════════════════════╝

1. Go to: https://console.cloud.google.com/
   Create a new project (e.g. "ApartmentScanner").

2. Enable APIs — in your project, go to:
   APIs & Services → Library
   Search for and enable:
     • Google Sheets API
     • Google Drive API

3. Create a Service Account:
   APIs & Services → Credentials → Create Credentials → Service Account
   Give it any name (e.g. "apartment-scanner-bot").
   Role: Editor (or Sheets + Drive permissions).

4. Download JSON key:
   Click the service account → Keys tab → Add Key → JSON
   Save the downloaded file as  google_credentials.json
   in the apartment-scanner/ folder.

5. Share the Google Sheet with the service account email:
   (The service account email looks like: name@project.iam.gserviceaccount.com)
   The setup script will create the sheet automatically — you'll need to
   share it with the service account email so it has write access.
   Alternatively, the service account can create sheets in Drive directly.

6. Gmail App Password (for email notifications):
   Go to: https://myaccount.google.com/apppasswords
   Generate an app password for "Mail" on your device.
   Use this password (NOT your Gmail password) in the .env file.
""")


def install_dependencies() -> bool:
    step(1, "Installing Python dependencies from requirements.txt…")
    req_file = BASE_DIR / "requirements.txt"
    if not req_file.exists():
        fail("requirements.txt not found")
        return False
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(req_file)],
        cwd=BASE_DIR,
    )
    if result.returncode == 0:
        ok("Dependencies installed")
        return True
    fail("pip install failed — check output above")
    return False


def install_playwright() -> bool:
    step(2, "Installing Playwright Chromium browser…")
    result = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        cwd=BASE_DIR,
    )
    if result.returncode == 0:
        ok("Playwright Chromium installed")
        return True
    fail("playwright install failed — check output above")
    return False


def prompt_google_credentials() -> str | None:
    step(3, "Google credentials setup")
    creds_default = BASE_DIR / "google_credentials.json"
    if creds_default.exists():
        ok(f"Found google_credentials.json at {creds_default}")
        return str(creds_default)

    print("  Please provide the path to your Google service account JSON credentials file.")
    print("  (See Google Cloud setup instructions above)")
    path = input("  Path to JSON file: ").strip().strip('"')
    if not path:
        fail("No path provided — Google Sheets integration will not work")
        return None
    src = Path(path)
    if not src.exists():
        fail(f"File not found: {src}")
        return None
    dest = BASE_DIR / "google_credentials.json"
    if src != dest:
        shutil.copy2(src, dest)
        ok(f"Copied credentials to {dest}")
    return str(dest)


def create_directories() -> None:
    step(4, "Creating data/ and logs/ directories…")
    (BASE_DIR / "data").mkdir(exist_ok=True)
    (BASE_DIR / "logs").mkdir(exist_ok=True)
    ok("Directories ready")


def init_database() -> None:
    step(5, "Initialising SQLite deduplication database…")
    try:
        sys.path.insert(0, str(BASE_DIR))
        from services.dedup import init_db
        init_db(str(BASE_DIR / "data" / "seen_listings.db"))
        ok("SQLite DB created at data/seen_listings.db")
    except Exception as exc:
        fail(f"SQLite init failed: {exc}")


def create_google_sheet(creds_path: str | None) -> tuple[str | None, str | None]:
    step(6, "Creating Google Sheet…")
    if not creds_path:
        fail("Skipped — no credentials provided")
        return None, None
    try:
        sys.path.insert(0, str(BASE_DIR))
        from dotenv import load_dotenv
        load_dotenv(BASE_DIR / ".env")
        sheet_name = os.environ.get("GOOGLE_SHEET_NAME", "Apartment Listings")
        from services.sheets import ensure_header, get_or_create_sheet, get_sheet_url
        ws = get_or_create_sheet(creds_path, sheet_name)
        ensure_header(ws)
        url = get_sheet_url(ws)
        ok(f"Sheet ready: {url}")
        return url, ws.spreadsheet.id
    except Exception as exc:
        fail(f"Google Sheets setup failed: {exc}")
        return None, None


def register_scheduler() -> None:
    step(7, "Registering Windows Task Scheduler job…")
    try:
        sys.path.insert(0, str(BASE_DIR))
        from scheduler_setup import register_task
        register_task(str(BASE_DIR))
    except Exception as exc:
        fail(f"Scheduler registration failed: {exc}")


def write_last_run_json() -> None:
    step(8, "Writing initial last_run.json…")
    (BASE_DIR / "last_run.json").write_text(
        json.dumps({"last_run": None}), encoding="utf-8"
    )
    ok("last_run.json written")


def create_env_if_missing() -> None:
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        return
    example = BASE_DIR / ".env.example"
    if example.exists():
        shutil.copy2(example, env_file)
        print("\n  [NOTE] Created .env from .env.example — please edit it with your real credentials.")


def main() -> None:
    print("=" * 68)
    print("  Apartment Scanner — One-Time Setup")
    print("=" * 68)

    print_google_cloud_instructions()

    input("  Press ENTER when you are ready to continue with automated setup…")

    create_env_if_missing()

    ok_deps = install_dependencies()
    ok_pw = install_playwright()
    creds_path = prompt_google_credentials()
    create_directories()
    init_database()
    sheet_url, sheet_id = create_google_sheet(creds_path)
    register_scheduler()
    write_last_run_json()

    print("\n" + "=" * 68)
    print("  Setup Complete")
    print("=" * 68)

    if sheet_url:
        print(f"\n  Your Google Sheet: {sheet_url}")
        print("  Bookmark this URL!")

    print("\n  Next steps:")
    print("  1. Edit .env with your Gmail App Password and Google credentials path")
    print("  2. Run: python main.py --debug")
    print("     to do a test scan and verify everything works")
    print("  3. The scanner will run automatically every Sunday at 08:00")
    print("     (catches up if the PC was off at that time)")

    if not ok_deps or not ok_pw:
        print("\n  [WARNING] Some setup steps failed — review output above")


if __name__ == "__main__":
    main()
