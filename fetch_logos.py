#!/usr/bin/env python3
"""Download real company logos for GSE equities."""
import urllib.request
import json
import re
import io
import os
import time
from PIL import Image

logos_dir = "backend/static/logos"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def download_image(url, output_path, headers=None):
    """Download an image, resize to 128x128, save as PNG."""
    h = headers or HEADERS
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=12) as resp:
        raw = resp.read()
    if len(raw) < 300:
        raise ValueError(f"Image too small: {len(raw)} bytes")
    im = Image.open(io.BytesIO(raw))
    im = im.convert("RGBA")
    canvas = Image.new("RGBA", (128, 128), (255, 255, 255, 0))
    im.thumbnail((120, 120), Image.Resampling.LANCZOS)
    x = (128 - im.width) // 2
    y = (128 - im.height) // 2
    canvas.paste(im, (x, y), im)
    canvas.save(output_path, "PNG")
    return os.path.getsize(output_path)


def wikipedia_api_urls(titles):
    """Fetch direct image URLs from Wikipedia API."""
    joined = urllib.parse.quote("|".join(titles), safe="|:")
    url = f"https://en.wikipedia.org/w/api.php?action=query&titles={joined}&prop=imageinfo&iiprop=url,thumburl&iiurlwidth=300&format=json"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    result = {}
    for p in data.get("query", {}).get("pages", {}).values():
        t = p["title"]
        info = p.get("imageinfo", [{}])[0]
        u = info.get("thumburl") or info.get("url")
        if u:
            result[t] = u
    return result


def wikimedia_api_urls(titles):
    """Fetch from Wikimedia Commons API."""
    joined = urllib.parse.quote("|".join(titles), safe="|:")
    url = f"https://commons.wikimedia.org/w/api.php?action=query&titles={joined}&prop=imageinfo&iiprop=url,thumburl&iiurlwidth=300&format=json"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    result = {}
    for p in data.get("query", {}).get("pages", {}).values():
        t = p["title"]
        info = p.get("imageinfo", [{}])[0]
        u = info.get("thumburl") or info.get("url")
        if u:
            result[t] = u
    return result


def scrape_page_logo(page_url):
    """Scrape og:image or logo src from a page."""
    req = urllib.request.Request(page_url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=12) as resp:
        html = resp.read().decode("utf-8", errors="ignore")
    og = re.search(r'<meta[^>]+property=.og:image.[^>]+content="([^"]+)"', html, re.IGNORECASE)
    if og:
        return og.group(1)
    logo = re.search(r'src="([^"]*logo[^"]*\.(?:png|jpg|jpeg|webp))"', html, re.IGNORECASE)
    if logo:
        return urllib.parse.urljoin(page_url, logo.group(1))
    return None


import urllib.parse


# Mapping: symbol -> list of (source_type, identifier)
# source_type: "wiki_en", "wiki_commons", "direct_url", "scrape"
LOGO_SOURCES = {
    # Still has generated 1507-byte logo - Wikimedia has real one
    "ACCESS": [
        ("wiki_en", "File:Access Bank Logo.png"),
    ],
    # Identical generic GSE placeholder (9390 bytes) - need real logos
    "BOPP": [
        ("wiki_en", "File:Benso Oil Palm Plantation logo.jpg"),
    ],
    "SIC": [
        ("direct_url", "https://www.sic-gh.com/wp-content/uploads/2020/06/sic_logo.png"),
        ("scrape", "https://www.sic-gh.com/"),
    ],
    "MAC": [
        ("scrape", "https://megaafricancapital.com/"),
        ("direct_url", "https://megaafricancapital.com/assets/images/logo.png"),
    ],
    "MMH": [
        ("wiki_en", "File:Mechanical Lloyd Company logo.png"),
        ("direct_url", "https://www.mechanicallloyd.com/wp-content/themes/mech/images/logo.png"),
    ],
    "SAMBA": [
        ("scrape", "https://sambafoodsghana.com/"),
        ("direct_url", "https://sambafoodsghana.com/wp-content/uploads/logo.png"),
    ],
    # Other small/low-quality logos to upgrade
    "MTNGH": [
        ("wiki_commons", "File:MTN Group Logo.svg"),
    ],
    "TLW": [
        ("wiki_en", "File:Tullow Oil.svg"),
    ],
    "TOTAL": [
        ("wiki_en", "File:TotalEnergies logo.svg"),
    ],
    "SCBPREF": [
        ("wiki_en", "File:Standard Chartered Logo (2021, Logo only).svg"),
    ],
    "GOIL": [
        ("scrape", "https://www.goil.com.gh/"),
    ],
    "RBGH": [
        ("scrape", "https://www.republicghana.com/"),
    ],
    "GCB": [
        ("direct_url", "https://www.gcb.com.gh/images/gcb_logo.png"),
        ("scrape", "https://www.gcb.com.gh/"),
    ],
    "KASA": [
        ("direct_url", "https://www.kasapreko.com/wp-content/uploads/2021/01/logo.png"),
        ("scrape", "https://www.kasapreko.com/"),
    ],
    "HORDS": [
        ("scrape", "https://hords.com.gh/"),
    ],
    "ZEN": [
        ("direct_url", "https://zenpetroleum.com/wp-content/uploads/logo.png"),
        ("scrape", "https://zenpetroleum.com/"),
    ],
    "ASG": [
        ("wiki_commons", "File:Asante Gold logo.png"),
        ("scrape", "https://www.asantegold.com/"),
    ],
}


def try_download_logo(sym, sources):
    out_path = os.path.join(logos_dir, f"{sym}.png")
    for source_type, identifier in sources:
        try:
            if source_type == "direct_url":
                size = download_image(identifier, out_path)
                print(f"[OK] {sym}: direct URL -> {size} bytes")
                return True

            elif source_type == "wiki_en":
                urls = wikipedia_api_urls([identifier])
                url = urls.get(identifier)
                if url:
                    size = download_image(url, out_path)
                    print(f"[OK] {sym}: Wikipedia '{identifier}' -> {size} bytes")
                    return True
                else:
                    print(f"[MISS] {sym}: Wikipedia '{identifier}' - no URL")

            elif source_type == "wiki_commons":
                urls = wikimedia_api_urls([identifier])
                url = urls.get(identifier)
                if url:
                    size = download_image(url, out_path)
                    print(f"[OK] {sym}: Wikimedia Commons '{identifier}' -> {size} bytes")
                    return True
                else:
                    print(f"[MISS] {sym}: Wikimedia Commons '{identifier}' - no URL")

            elif source_type == "scrape":
                url = scrape_page_logo(identifier)
                if url:
                    size = download_image(url, out_path)
                    print(f"[OK] {sym}: scraped {identifier} -> {url} -> {size} bytes")
                    return True
                else:
                    print(f"[MISS] {sym}: scrape {identifier} - no logo found")

        except Exception as e:
            print(f"[FAIL] {sym}: {source_type} {identifier} -> {e}")
        time.sleep(0.5)

    print(f"[SKIP] {sym}: all sources exhausted")
    return False


for sym, sources in LOGO_SOURCES.items():
    try_download_logo(sym, sources)
    time.sleep(0.3)

print("\nDone. Final logo sizes:")
for path in sorted(os.listdir(logos_dir)):
    if path.endswith(".csv"):
        continue
    size = os.path.getsize(os.path.join(logos_dir, path))
    print(f"  {path:15s} {size:7d} bytes")
