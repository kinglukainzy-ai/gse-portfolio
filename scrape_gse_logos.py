#!/usr/bin/env python3
"""Scrape GSE company pages and download logos."""
import subprocess, re, io, os, time
from PIL import Image

logos_dir = "backend/static/logos"

def curl_get(url):
    r = subprocess.run(
        ["curl", "-s", "-L", "--connect-timeout", "10",
         "-A", "Mozilla/5.0 Chrome/125", "-H", "Accept: text/html,*/*", url],
        capture_output=True
    )
    return r.stdout.decode("utf-8", "ignore")

def curl_img(url, referer="https://gse.com.gh/"):
    r = subprocess.run(
        ["curl", "-s", "-L", "--connect-timeout", "10",
         "-A", "Mozilla/5.0 Chrome/125",
         "-H", f"Referer: {referer}", url],
        capture_output=True
    )
    return r.stdout

def save(sym, raw):
    if len(raw) < 600:
        raise ValueError(f"too small ({len(raw)}b)")
    im = Image.open(io.BytesIO(raw)).convert("RGBA")
    canvas = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    im.thumbnail((240, 240), Image.Resampling.LANCZOS)
    x = (256-im.width)//2
    y = (256-im.height)//2
    canvas.paste(im, (x, y), im)
    out = os.path.join(logos_dir, f"{sym}.png")
    canvas.save(out)
    return os.path.getsize(out)

# GSE profile page slugs for each symbol
gse_slugs = {
    "MTNGH": "mtn-ghana-limited",
    "TLW":   "tullow-oil-plc",
    "SIC":   "sic-insurance-company-limited",
    "ADB":   "agricultural-development-bank-limited",
    "EGL":   "enterprise-group-limited",
    "ZEN":   "zen-petroleum-limited",
    "ASG":   "asante-gold-corporation",
    "IIL":   "intravenous-infusions-limited",
    "TBL":   "trust-bank-the-gambia-limited",
    "MMH":   "mechanical-lloyd-company-limited",
    "MAC":   "mega-african-capital-limited",
    "SAMBA": "samba-foods-limited",
    "HORDS": "hords-limited",
    "CLYD":  "clydestone-ghana-limited",
    "ALLGH": "atlantic-lithium-limited",
}

SKIP_KEYWORDS = ["favicon", "FramePNG", "gse-logo", "white-gse", "Banner", "cropped"]

for sym, slug in gse_slugs.items():
    out = os.path.join(logos_dir, f"{sym}.png")
    if os.path.exists(out) and os.path.getsize(out) > 10000:
        print(f"[SKIP] {sym}: already good ({os.path.getsize(out)}b)")
        continue

    url = f"https://gse.com.gh/listing/{slug}/"
    html = curl_get(url)
    imgs = re.findall(
        r"(https?://(?:gse\.com\.gh|www\.gse\.com\.gh)/wp-content/uploads/[^\s\"']+\.(?:png|jpg|jpeg|webp))",
        html
    )
    imgs = [u for u in imgs if not any(k in u for k in SKIP_KEYWORDS)]

    print(f"{sym}: {len(imgs)} candidate images from {url}")
    downloaded = False
    for img_url in imgs[:5]:
        try:
            raw = curl_img(img_url)
            sz = save(sym, raw)
            print(f"  [OK] {sym}: {img_url[:60]} -> {sz}b")
            downloaded = True
            break
        except Exception as e:
            print(f"  [FAIL] {img_url[:60]}: {e}")
    if not downloaded:
        print(f"  [MISS] {sym}: no usable image found")
    time.sleep(0.5)
