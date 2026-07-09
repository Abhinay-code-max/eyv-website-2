"""
Installs ignav_service.py, updates .env with the API key,
and patches server.py to use Ignav instead of Sky Scrapper.
"""
import shutil
from pathlib import Path

BASE    = Path(r"C:\Users\Abhinay Kandrika\OneDrive\Desktop\eyv-website-main\backend")
SERVER  = BASE / "server.py"
ENV     = BASE / ".env"
SVC_DIR = BASE / "services"
SRC     = Path(__file__).parent / "ignav_service.py"

# ── 1. Copy service file ─────────────────────────────────────────────────────
shutil.copy(SRC, SVC_DIR / "ignav_service.py")
print("✓ ignav_service.py installed to services/")

# ── 2. Add IGNAV_API_KEY to .env ─────────────────────────────────────────────
env_text = ENV.read_text(encoding="utf-8")
if "IGNAV_API_KEY" not in env_text:
    env_text += "\nIGNAV_API_KEY=ignav_2sBZOraBXCFeYP2K-oCOAwaiiVwxr-Oe\n"
    ENV.write_text(env_text, encoding="utf-8")
    print("✓ IGNAV_API_KEY added to .env")
else:
    print("✓ IGNAV_API_KEY already in .env")

# ── 3. Patch server.py ───────────────────────────────────────────────────────
shutil.copy(SERVER, SERVER.with_suffix(".py.backup_ignav"))
server = SERVER.read_text(encoding="utf-8")

# Replace sky_scrapper import with ignav
server = server.replace(
    "from services import sky_scrapper_service as duffel_service  # Sky Scrapper replaces Duffel",
    "from services import ignav_service as duffel_service  # Ignav replaces Sky Scrapper"
)

# Also handle if it still points to original duffel
server = server.replace(
    "from services import duffel_service",
    "from services import ignav_service as duffel_service  # Ignav flight service"
)

SERVER.write_text(server, encoding="utf-8")
print("✓ server.py patched — duffel_service now points to Ignav")
print("\n✅ Done! Restart the backend server.")
