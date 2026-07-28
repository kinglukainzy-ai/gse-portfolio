#!/usr/bin/env python3
"""Download real company logos using DuckDuckGo image search to replace generic placeholders."""
import subprocess, json, re, io, os, urllib.parse, time
from PIL import Image

logos_dir = "backend/static/logos"

CURL_ARGS = [
    "curl", "-s", "-L", "--connect-timeout", "10",
    "-A", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/125.0.0.0",
]

def curl_get(url, extra_headers=None):
    args = CURL_ARGS[:]
    if extra_headers:
        for k, v in extra_headers.items():
            args += ["-H", f"{k}: {v}"]
    args.append(url)
    r = subprocess.run(args, capture_output=True)
    return r.stdout

def save(sym, raw):
    if len(raw) < 600:
        raise ValueError(f"too small {len(raw)}b")
    im = Image.open(io.BytesIO(raw)).convert("RGBA")
    canvas = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    im.thumbnail((240, 240), Image.Resampling.LANCZOS)
    x = (256-im.width)//2
    y = (256-im.height)//2
    canvas.paste(im, (x, y), im)
    out = os.path.join(logos_dir, f"{sym}.png")
    canvas.save(out)
    return os.path.getsize(out)

# Specific targets that still have generic or small logos
searches = {
    "GCB":   "GCB Bank Ghana logo PNG",
    "GOIL":  "GOIL Ghana logo PNG",
    "SIC":   "SIC Insurance Company Ghana logo PNG",
    "MAC":   "Mega African Capital logo PNG",
    "MMH":   "Mechanical Lloyd Ghana logo",
    "SAMBA": "Samba Foods Ghana logo",
}

for sym, query in searches.items():
    out = os.path.join(logos_dir, f"{sym}.png")
    # Do not skip these targets as we explicitly want to overwrite the generics (which are 9390 bytes or smaller)
    
    enc = urllib.parse.quote(query)
    # Step 1: get VQD token
    html = curl_get(
        f"https://duckduckgo.com/?q={enc}&ia=images",
        {"Accept": "text/html,*/*"}
    ).decode("utf-8", "ignore")

    vqd_match = re.search(r'vqd=(["\'])([^"\']+)\1', html)
    if not vqd_match:
        vqd_match = re.search(r'"vqd":"([^"]+)"', html)
        vqd = vqd_match.group(1) if vqd_match else None
    else:
        vqd = vqd_match.group(2)

    if not vqd:
        print(f"[MISS] {sym}: no vqd token found")
        time.sleep(1)
        continue

    # Step 2: get image results
    api_url = f"https://duckduckgo.com/i.js?l=us-en&o=json&q={enc}&vqd={urllib.parse.quote(vqd)}&f=,,,,,&p=1"
    resp = curl_get(api_url, {"Referer": "https://duckduckgo.com/"}).decode("utf-8", "ignore")
    try:
        data = json.loads(resp)
        results = data.get("results", [])
    except Exception:
        print(f"[FAIL] {sym}: JSON parse error")
        time.sleep(1)
        continue

    downloaded = False
    for r in results[:8]:
        img_url = r.get("image") or r.get("thumbnail")
        if not img_url:
            continue
        try:
            raw = curl_get(img_url, {"Referer": "https://duckduckgo.com/"})
            sz = save(sym, raw)
            print(f"[OK] {sym}: {img_url[:70]} -> {sz}b")
            downloaded = True
            break
        except Exception as e:
            pass

    if not downloaded:
        print(f"[MISS] {sym}: {len(results)} results, none worked")
    time.sleep(1.5)
