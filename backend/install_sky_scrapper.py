"""
Installs sky_scrapper_service.py and wires it into server.py
replacing duffel_service with Sky Scrapper (Skyscanner via RapidAPI).
"""
import shutil
from pathlib import Path

BASE    = Path(r"C:\Users\Abhinay Kandrika\OneDrive\Desktop\eyv-website-main\backend")
SERVER  = BASE / "server.py"
SVC_DIR = BASE / "services"
SKY_SRC = Path(__file__).parent / "sky_scrapper_service.py"

# ── Copy the new service file ────────────────────────────────────────────────
shutil.copy(SKY_SRC, SVC_DIR / "sky_scrapper_service.py")
print("✓ sky_scrapper_service.py installed")

# ── Patch server.py ──────────────────────────────────────────────────────────
shutil.copy(SERVER, SERVER.with_suffix(".py.backup_sky"))
server = SERVER.read_text(encoding="utf-8")

# 1. Replace duffel import with sky_scrapper
server = server.replace(
    "from services import duffel_service",
    "from services import sky_scrapper_service as duffel_service  # Sky Scrapper replaces Duffel"
)

# 2. Replace serpapi import if not already there (idempotent)
if "from services import serpapi_hotels_service" not in server:
    server = server.replace(
        "from services import sky_scrapper_service as duffel_service",
        "from services import sky_scrapper_service as duffel_service\nfrom services import serpapi_hotels_service"
    )

SERVER.write_text(server, encoding="utf-8")
print("✓ server.py patched — duffel_service now points to Sky Scrapper")
print("\n✅ Done! Restart the backend server.")
