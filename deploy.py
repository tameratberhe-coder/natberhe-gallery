#!/usr/bin/env python3
"""
Bulletproof Shopify deploy script for natberhegallery.com
Auto-detects ALL local image references and converts them to Shopify asset_url tags.
Never misses a file.
"""
import re, requests, sys

import os
SHOP = os.environ.get("SHOPIFY_SHOP", "fbea3c-0e.myshopify.com")
TOKEN = os.environ["SHOPIFY_TOKEN"]  # Set via environment variable
THEMES = [182801662252, 182801858860]  # v11 backup, v12 live
HEADERS = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}

with open('index.html', 'r') as f:
    html = f.read()

# Auto-detect ALL local image references (not CDN URLs, not already Liquid tags)
local_refs = set()
for attr in ['src', 'href', 'content']:
    for match in re.finditer(rf'{attr}="([^"]*?\.(?:jpg|jpeg|png|gif|svg|webp|ico))"', html):
        val = match.group(1)
        if not val.startswith('http') and '{{' not in val and '/' not in val:
            local_refs.add(val)

print(f"Converting {len(local_refs)} local image references:")
for ref in sorted(local_refs):
    print(f"  {ref}")

shopify_html = html
for img in local_refs:
    for attr in ['src', 'href', 'content']:
        shopify_html = shopify_html.replace(f'{attr}="{img}"', f"{attr}=\"{{{{ '{img}' | asset_url }}}}\"")
        shopify_html = shopify_html.replace(f"{attr}='{img}'", f"{attr}=\"{{{{ '{img}' | asset_url }}}}\"")

# Verify none remain
remaining = []
for attr in ['src', 'href', 'content']:
    for match in re.finditer(rf'{attr}="([^"]*?\.(?:jpg|jpeg|png|gif|svg|webp|ico))"', shopify_html):
        val = match.group(1)
        if not val.startswith('http') and '{{' not in val:
            remaining.append(val)

if remaining:
    print(f"\nERROR: {len(remaining)} local refs still unconverted: {remaining}")
    sys.exit(1)

print(f"\nAll converted. Deploying to {len(THEMES)} themes...")
for tid in THEMES:
    url = f"https://{SHOP}/admin/api/2024-01/themes/{tid}/assets.json"
    r = requests.put(url, headers=HEADERS, json={"asset": {"key": "templates/index.liquid", "value": shopify_html}})
    status = "OK" if r.status_code == 200 else f"FAIL ({r.status_code})"
    print(f"  Theme {tid}: {status}")

print("Done!")
