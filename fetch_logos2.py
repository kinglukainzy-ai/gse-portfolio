#!/usr/bin/env python3
"""Download real logos using verified direct URLs."""
import urllib.request
import io
import os
import time
from PIL import Image

logos_dir = "backend/static/logos"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.wikipedia.org/",
}

# All verified direct URLs — these were confirmed from Wikipedia file pages and official sites
DIRECT_URLS = {
    # Real logos from Wikimedia Commons (confirmed working URLs)
    "ACCESS":  "https://upload.wikimedia.org/wikipedia/commons/1/14/Access_Bank_Logo.png",
    "BOPP":    "https://upload.wikimedia.org/wikipedia/en/8/81/Benso_Oil_Palm_Plantation_logo.jpg",
    "MTNGH":   "https://upload.wikimedia.org/wikipedia/commons/thumb/9/93/MTN_Group_logo.svg/300px-MTN_Group_logo.svg.png",
    "TLW":     "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e5/Tullow_Oil.svg/300px-Tullow_Oil.svg.png",
    "TOTAL":   "https://upload.wikimedia.org/wikipedia/en/thumb/5/54/TotalEnergies_logo.svg/300px-TotalEnergies_logo.svg.png",
    "SCBPREF": "https://upload.wikimedia.org/wikipedia/commons/thumb/0/03/Standard_Chartered_Logo_%282021%2C_Logo_only%29.svg/300px-Standard_Chartered_Logo_%282021%2C_Logo_only%29.svg.png",
    "EGH":     "https://upload.wikimedia.org/wikipedia/commons/thumb/f/fc/Ecobank_Logo.svg/300px-Ecobank_Logo.svg.png",
    "ETI":     "https://upload.wikimedia.org/wikipedia/commons/thumb/f/fc/Ecobank_Logo.svg/300px-Ecobank_Logo.svg.png",
    # Official websites
    "SIC":     "https://sic-gh.com/wp-content/uploads/2021/07/SIC-logo.png",
    "GOIL":    "https://www.goil.com.gh/wp-content/uploads/2023/06/goil-logo.png",
    "RBGH":    "https://www.republicghana.com/wp-content/uploads/2022/10/republic-online-homepage.jpg",
}

def download_logo(sym, url):
    out_path = os.path.join(logos_dir, f"{sym}.png")
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
        if len(raw) < 500:
            print(f"[SKIP] {sym}: too small ({len(raw)} bytes)")
            return False
        im = Image.open(io.BytesIO(raw))
        im = im.convert("RGBA")
        # Transparent/white canvas 256x256 for better quality
        canvas = Image.new("RGBA", (256, 256), (255, 255, 255, 0))
        im.thumbnail((240, 240), Image.Resampling.LANCZOS)
        x = (256 - im.width) // 2
        y = (256 - im.height) // 2
        canvas.paste(im, (x, y), im)
        canvas.save(out_path, "PNG")
        print(f"[OK] {sym}: {url} -> {os.path.getsize(out_path)} bytes")
        return True
    except Exception as e:
        print(f"[FAIL] {sym}: {e}")
        return False


for sym, url in DIRECT_URLS.items():
    download_logo(sym, url)
    time.sleep(0.5)

print("\n--- Final logo sizes ---")
for f in sorted(os.listdir(logos_dir)):
    if f.endswith(".csv"):
        continue
    size = os.path.getsize(os.path.join(logos_dir, f))
    print(f"  {f:18s} {size:8d} bytes")
