import re, requests, os
with open('/home/user/workspace/natberhe-gallery/index.html', 'r') as f:
    html = f.read()
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
SHOP = "fbea3c-0e.myshopify.com"
TOKEN = os.environ.get("SHOPIFY_TOKEN", "")
HEADERS = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}
for tid in [182801662252, 182801858860]:
    url = f"https://{SHOP}/admin/api/2024-01/themes/{tid}/assets.json"
    r = requests.put(url, headers=HEADERS, json={"asset": {"key": "templates/index.liquid", "value": shopify_html}})
    print(f"Theme {tid}: {'OK' if r.status_code == 200 else f'FAIL'}")
