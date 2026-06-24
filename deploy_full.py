#!/usr/bin/env python3
"""
Full deploy: pushes index.html as templates/index.liquid AND catalog.js as assets/catalog.js
to live theme 183912333612 and all backup themes.
"""
import re, requests, os, sys

SHOP = os.environ.get("SHOPIFY_SHOP", "fbea3c-0e.myshopify.com")
TOKEN = os.environ.get("SHOPIFY_TOKEN", "")
if not TOKEN:
    print("ERROR: SHOPIFY_TOKEN env var required")
    sys.exit(1)
THEMES = [
    183912333612,  # LIVE
    183911973164,  # backup
    182801858860,  # legacy backup
    182801662252,  # legacy backup
]
HEADERS = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}

with open('/home/user/workspace/natberhe-gallery/index.html', 'r') as f:
    html = f.read()

# Auto-detect local image refs and convert to asset_url
local_refs = set()
for attr in ['src', 'href', 'content']:
    for match in re.finditer(rf'{attr}="([^"]*?\.(?:jpg|jpeg|png|gif|svg|webp|ico))"', html):
        val = match.group(1)
        if not val.startswith('http') and '{{' not in val and '/' not in val:
            local_refs.add(val)

shopify_html = html
for img in local_refs:
    for attr in ['src', 'href', 'content']:
        shopify_html = shopify_html.replace(f'{attr}="{img}"', f"{attr}=\"{{{{ '{img}' | asset_url }}}}\"")
        shopify_html = shopify_html.replace(f"{attr}='{img}'", f"{attr}=\"{{{{ '{img}' | asset_url }}}}\"")

# Read catalog.js
with open('/home/user/workspace/natberhe-gallery/catalog.js', 'r') as f:
    catalog_js = f.read()

print(f"index.html: {len(shopify_html)} bytes ({len(local_refs)} img refs converted)")
print(f"catalog.js: {len(catalog_js)} bytes")
print()

results = {}
for tid in THEMES:
    base = f"https://{SHOP}/admin/api/2024-01/themes/{tid}/assets.json"

    # Push index.liquid
    r1 = requests.put(base, headers=HEADERS, json={"asset": {"key": "templates/index.liquid", "value": shopify_html}})
    s1 = "OK" if r1.status_code == 200 else f"FAIL ({r1.status_code})"

    # Push catalog.js to all known asset names. Live theme currently loads catalog-v6.js.
    # We mirror to v4/v5/v6 + plain catalog.js so any rollback still works.
    js_results = []
    for key in ["assets/catalog.js", "assets/catalog-v4.js", "assets/catalog-v5.js", "assets/catalog-v6.js", "assets/catalog-v7.js", "assets/catalog-v8.js", "assets/catalog-v9.js", "assets/catalog-v10.js", "assets/catalog-v11.js"]:
        r2 = requests.put(base, headers=HEADERS, json={"asset": {"key": key, "value": catalog_js}})
        js_results.append(f"{key}={'OK' if r2.status_code == 200 else f'FAIL({r2.status_code})'}")

    results[tid] = (s1, js_results)
    print(f"Theme {tid}: index={s1}, {', '.join(js_results)}")

# Exit non-zero if live theme failed
if "OK" not in results[183912333612][0]:
    sys.exit(1)
print("\nLive theme deploy: SUCCESS")
