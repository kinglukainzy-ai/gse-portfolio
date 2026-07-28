#!/usr/bin/env python3
"""
Download company logos using curl (better browser impersonation than urllib).
Processes PIL image resize after successful download.
"""
import subprocess, io, os, sys
from PIL import Image

logos_dir = "backend/static/logos"

CURL_HEADERS = [
    "-H", "User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "-H", "Referer: https://en.wikipedia.org/",
    "-H", "Accept: image/webp,image/apng,image/*,*/*;q=0.8",
    "-H", "Accept-Language: en-US,en;q=0.9",
    "-L", "--connect-timeout", "15", "--max-time", "20",
]


def curl_download(url: str) -> bytes:
    result = subprocess.run(
        ["curl", "-s", *CURL_HEADERS, url],
        capture_output=True
    )
    return result.stdout


def save_logo(sym: str, raw: bytes, min_size: int = 800) -> int:
    if len(raw) < min_size:
        raise ValueError(f"downloaded data too small ({len(raw)} bytes)")
    try:
        im = Image.open(io.BytesIO(raw)).convert("RGBA")
    except Exception as e:
        raise ValueError(f"not a valid image: {e}")
    canvas = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    im.thumbnail((240, 240), Image.Resampling.LANCZOS)
    x = (256 - im.width) // 2
    y = (256 - im.height) // 2
    canvas.paste(im, (x, y), im)
    out = os.path.join(logos_dir, f"{sym}.png")
    canvas.save(out, "PNG")
    return os.path.getsize(out)


# All known-working direct URLs for remaining companies
# Priority: official website > Wikipedia commons
LOGO_URLS = {
    # ---- Real Wikipedia/Wikimedia URLs confirmed via page scrape ----
    "GCB":   "https://upload.wikimedia.org/wikipedia/commons/3/3d/GCBBANK.jpg",
    "GOIL":  "https://upload.wikimedia.org/wikipedia/commons/7/7a/Goil.jpg",
    "CAL":   "https://upload.wikimedia.org/wikipedia/commons/3/34/Logo_png-01.png",
    "ALLGH": "https://upload.wikimedia.org/wikipedia/commons/thumb/3/3f/Atlantic_Lithium_Limited_logo.png/320px-Atlantic_Lithium_Limited_logo.png",
    "ADB":   "https://upload.wikimedia.org/wikipedia/commons/thumb/4/49/ADB_Ghana_logo.svg/320px-ADB_Ghana_logo.svg.png",
    "EGL":   "https://upload.wikimedia.org/wikipedia/commons/thumb/5/51/Enterprise_Group_Limited_logo.png/320px-Enterprise_Group_Limited_logo.png",
    "CLYD":  "https://upload.wikimedia.org/wikipedia/en/1/1c/Clydestone_Ghana_Ltd_logo.jpg",
    "TBL":   "https://upload.wikimedia.org/wikipedia/commons/thumb/9/93/Trust_Bank_The_Gambia_logo.png/320px-Trust_Bank_The_Gambia_logo.png",
    "IIL":   "https://upload.wikimedia.org/wikipedia/en/7/7d/Intravenous_Infusions_Limited.jpg",
    "HORDS": "https://upload.wikimedia.org/wikipedia/en/0/0b/Hords_Ghana.jpg",
    "ZEN":   "https://upload.wikimedia.org/wikipedia/en/5/5e/Zen_Petroleum_Ghana.jpg",
    "ASG":   "https://upload.wikimedia.org/wikipedia/commons/thumb/4/4f/Asante_Gold_Corp_logo.png/320px-Asante_Gold_Corp_logo.png",
    "SIC":   "https://upload.wikimedia.org/wikipedia/en/f/f5/SIC_Insurance_Company_Limited_logo.jpg",
    "MMH":   "https://upload.wikimedia.org/wikipedia/en/2/20/Mechanical_Lloyd_Ghana.jpg",
    "MAC":   "https://upload.wikimedia.org/wikipedia/en/5/57/Mega_African_Capital.jpg",
    "SAMBA": "https://upload.wikimedia.org/wikipedia/en/3/3c/Samba_Foods_Ghana.jpg",
    # ---- MTN: their official press kit / media page ----
    "MTNGH": "https://www.mtn.com.gh/wp-content/uploads/2023/05/MTN-logo.png",
    # ---- Tullow: official site ----
    "TLW":   "https://www.tullowoil.com/media/logo-colour.png",
}

# Supplemental fallback URLs if primary fails
FALLBACK_URLS = {
    "GCB":   "https://www.gcb.com.gh/wp-content/uploads/2023/GCB-Logo.png",
    "MTNGH": "https://logo.brandfetch.io/mtn.com/w/512/h/512/logo",
    "TLW":   "https://upload.wikimedia.org/wikipedia/en/thumb/b/bc/Tullow_Oil.svg/200px-Tullow_Oil.svg.png",
}


def try_download(sym: str) -> bool:
    out = os.path.join(logos_dir, f"{sym}.png")
    if os.path.exists(out) and os.path.getsize(out) > 10000:
        print(f"[SKIP] {sym}: already has good logo ({os.path.getsize(out)}b)")
        return True

    urls_to_try = []
    if sym in LOGO_URLS:
        urls_to_try.append(LOGO_URLS[sym])
    if sym in FALLBACK_URLS:
        urls_to_try.append(FALLBACK_URLS[sym])

    for url in urls_to_try:
        try:
            raw = curl_download(url)
            size = save_logo(sym, raw)
            print(f"[OK] {sym}: {url[:60]}... -> {size} bytes")
            return True
        except ValueError as e:
            print(f"[FAIL] {sym}: {url[:60]}... -> {e}")

    print(f"[MISS] {sym}: all URLs failed")
    return False


if __name__ == "__main__":
    targets = sys.argv[1:] or list(LOGO_URLS.keys())
    for sym in targets:
        try_download(sym)
