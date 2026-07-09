import shutil, re
from pathlib import Path

file = Path(r"C:\Users\Abhinay Kandrika\OneDrive\Desktop\eyv-website-main\frontend\src\pages\DashboardPage.jsx")
backup = file.with_suffix(".backup8.jsx")

# Backup
shutil.copy(file, backup)
print(f"Backed up to {backup.name}")

content = file.read_text(encoding="utf-8")

# Fix 1: variant name visible -> show
content = content.replace(
    "visible: { transition: { staggerChildren: 0.08, delayChildren: 0.15 } }",
    "show: { transition: { staggerChildren: 0.08, delayChildren: 0.15 } }"
)

# Fix 2: animate="visible" -> animate="show"
content = content.replace('animate="visible"', 'animate="show"')

file.write_text(content, encoding="utf-8")
print("Done! Quick action cards should now appear.")
