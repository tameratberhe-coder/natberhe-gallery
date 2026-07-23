#!/usr/bin/env python3
"""
Shopify-to-Prodigi auto-router for natberhegallery.com

Polls Shopify for paid, unfulfilled orders containing print line items,
submits them to Prodigi with ImageWrap (no white border) on canvas,
and tracks routed orders for idempotency.

Outputs JSON to stdout:
  {"orders_checked": N, "newly_routed": N, "failures": N,
   "new_orders": [...], "failure_details": [...]}

State: /home/user/workspace/cron_tracking/auto_router/routed_orders.json
"""
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

SHOP = "fbea3c-0e.myshopify.com"
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_ADMIN_TOKEN", "")
PRODIGI_KEY = os.environ.get("PRODIGI_API_KEY", "")
PRODIGI_BASE = "https://api.prodigi.com/v4.0"

STATE_DIR = "/home/user/workspace/cron_tracking/auto_router"
STATE_FILE = os.path.join(STATE_DIR, "routed_orders.json")
SKU_MAP_FILE = "/home/user/workspace/prodigi_sku_map.json"


def http_request(method, url, headers=None, body=None, timeout=30):
    """Lightweight HTTP request returning (status, body_text)."""
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def load_state():
    os.makedirs(STATE_DIR, exist_ok=True)
    if not os.path.exists(STATE_FILE):
        return {"routed": {}, "last_run": None}
    with open(STATE_FILE) as f:
        return json.load(f)


def save_state(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    state["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def load_sku_map():
    with open(SKU_MAP_FILE) as f:
        return json.load(f)


def normalize_size(raw):
    """Convert 'XX" x YY"' (with straight or smart quotes) to 'XXxYY'."""
    if not raw:
        return None
    # Strip all kinds of quotes and whitespace
    cleaned = raw.replace("″", "").replace('"', "").replace("'", "")
    cleaned = re.sub(r"\([^)]*\)", "", cleaned).strip()
    # Find first two numbers
    nums = re.findall(r"\d+", cleaned)
    if len(nums) >= 2:
        return f"{nums[0]}x{nums[1]}"
    return None


def shopify_get_unfulfilled_orders():
    """Fetch paid, unfulfilled orders from last 30 days."""
    url = (
        f"https://{SHOP}/admin/api/2024-01/orders.json"
        f"?status=open&fulfillment_status=unfulfilled&financial_status=paid&limit=50"
    )
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN}
    code, body = http_request("GET", url, headers=headers)
    if code != 200:
        raise RuntimeError(f"Shopify GET orders failed: {code} {body[:200]}")
    return json.loads(body).get("orders", [])


def product_is_print(product_id, line_item):
    """Heuristic: print if variant size matches a Prodigi-compatible size."""
    variant_title = line_item.get("variant_title") or ""
    if not variant_title or variant_title == "Default Title":
        return False
    size = normalize_size(variant_title)
    return size is not None


def get_product_image_url(product_id):
    """Pull the current featured image URL for a Shopify product."""
    url = f"https://{SHOP}/admin/api/2024-01/products/{product_id}.json?fields=image,images"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN}
    code, body = http_request("GET", url, headers=headers)
    if code != 200:
        return None
    data = json.loads(body).get("product", {})
    img = data.get("image") or {}
    if img.get("src"):
        return img["src"]
    images = data.get("images") or []
    return images[0].get("src") if images else None


def build_prodigi_payload(order, sku_map):
    """Build a Prodigi order payload from a Shopify order."""
    addr = order.get("shipping_address") or order.get("billing_address") or {}
    recipient = {
        "name": addr.get("name") or order.get("customer", {}).get("first_name", "") + " " + order.get("customer", {}).get("last_name", ""),
        "email": order.get("email") or order.get("contact_email"),
        "address": {
            "line1": addr.get("address1") or "",
            "line2": addr.get("address2") or None,
            "townOrCity": addr.get("city") or "",
            "stateOrCounty": addr.get("province_code") or addr.get("province") or "",
            "postalOrZipCode": addr.get("zip") or "",
            "countryCode": addr.get("country_code") or "US",
        },
    }

    items = []
    skipped = []
    for li in order.get("line_items", []):
        if not product_is_print(li.get("product_id"), li):
            skipped.append(
                f"line {li.get('id')} '{li.get('title')}' (variant: {li.get('variant_title')!r}) not a recognized print"
            )
            continue
        size = normalize_size(li.get("variant_title") or "")
        if size not in sku_map:
            skipped.append(f"line {li.get('id')} size {size} not in SKU map")
            continue
        prodigi_sku = sku_map[size]["sku"]
        image_url = get_product_image_url(li.get("product_id"))
        if not image_url:
            skipped.append(f"line {li.get('id')} no image URL")
            continue
        items.append({
            "sku": prodigi_sku,
            "copies": int(li.get("quantity", 1)),
            "sizing": "fillPrintArea",
            "attributes": {"wrap": "ImageWrap"},  # NO WHITE BORDER
            "assets": [{"printArea": "default", "url": image_url}],
        })

    return {
        "shippingMethod": "Budget",
        "merchantReference": f"shopify-{order.get('name')}-auto",
        "recipient": recipient,
        "items": items,
    }, skipped


def submit_to_prodigi(payload):
    code, body = http_request(
        "POST",
        f"{PRODIGI_BASE}/orders",
        headers={"X-API-Key": PRODIGI_KEY, "Content-Type": "application/json"},
        body=payload,
    )
    try:
        return code, json.loads(body)
    except json.JSONDecodeError:
        return code, {"raw": body}


def main():
    sku_map = load_sku_map()
    state = load_state()
    routed = state["routed"]

    result = {
        "orders_checked": 0,
        "newly_routed": 0,
        "failures": 0,
        "new_orders": [],
        "failure_details": [],
    }

    try:
        orders = shopify_get_unfulfilled_orders()
    except Exception as e:
        result["failures"] = 1
        result["failure_details"].append({"error": f"shopify_fetch: {e}"})
        save_state(state)
        print(json.dumps(result))
        return

    result["orders_checked"] = len(orders)

    for order in orders:
        order_id = str(order.get("id"))
        order_name = order.get("name") or f"id-{order_id}"

        if order_id in routed:
            continue  # idempotent skip

        payload, skipped = build_prodigi_payload(order, sku_map)

        if not payload["items"]:
            # Order has no routable items; mark as skipped (not failed) so we don't retry
            routed[order_id] = {
                "name": order_name,
                "status": "skipped_no_print_items",
                "reasons": skipped,
                "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            }
            continue

        code, response = submit_to_prodigi(payload)
        outcome = response.get("outcome") if isinstance(response, dict) else None

        if code in (200, 201) and outcome in ("Created", "CreatedWithIssues"):
            prodigi_order = response.get("order", {})
            prodigi_id = prodigi_order.get("id")
            charges = prodigi_order.get("charges", [])
            total = None
            if charges:
                tc = charges[0].get("totalCost", {})
                total = f"{tc.get('amount')} {tc.get('currency')}"
            routed[order_id] = {
                "name": order_name,
                "status": "routed",
                "prodigi_id": prodigi_id,
                "total": total,
                "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            }
            result["newly_routed"] += 1
            result["new_orders"].append({
                "shopify_name": order_name,
                "prodigi_id": prodigi_id,
                "total": total,
            })
        else:
            result["failures"] += 1
            result["failure_details"].append({
                "shopify_name": order_name,
                "shopify_id": order_id,
                "http_code": code,
                "outcome": outcome,
                "response": response if len(json.dumps(response)) < 800 else "(truncated)",
            })


    # Check Prodigi for newly-shipped orders (tracking writeback notification)
    newly_shipped = []
    for sid, info in routed.items():
        if info.get('status') != 'routed':
            continue
        pid = info.get('prodigi_id')
        if not pid or info.get('notified_shipped'):
            continue
        try:
            code_p, body_p = http_request(
                "GET",
                f"{PRODIGI_BASE}/orders/{pid}",
                headers={"X-API-Key": PRODIGI_KEY},
            )
            if code_p == 200:
                pdata = json.loads(body_p).get('order', {})
                shipments = pdata.get('shipments', [])
                for s in shipments:
                    if s.get('status') == 'Shipped':
                        tracking = (s.get('tracking') or {}).get('number')
                        url = (s.get('tracking') or {}).get('url')
                        carrier = (s.get('carrier') or {}).get('name', 'UPS')
                        if tracking:
                            # Auto-push fulfillment to Shopify with tracking number.
                            # This marks the order fulfilled and triggers Shopify's standard
                            # customer shipping email with the carrier tracking link.
                            fulfilled_in_shopify = False
                            shopify_error = None
                            try:
                                code_fo, body_fo = http_request(
                                    "GET",
                                    f"https://{SHOP}/admin/api/2024-01/orders/{sid}/fulfillment_orders.json",
                                    headers={"X-Shopify-Access-Token": SHOPIFY_TOKEN},
                                )
                                if code_fo == 200:
                                    fos = json.loads(body_fo).get('fulfillment_orders', [])
                                    open_fos = [fo for fo in fos if fo.get('status') in ('open', 'in_progress')]
                                    if open_fos:
                                        fulfillment_body = {
                                            "fulfillment": {
                                                "message": f"Shipped from Prodigi production. Tracking: {tracking}",
                                                "notify_customer": True,
                                                "tracking_info": {
                                                    "number": tracking,
                                                    "url": url or f"https://www.ups.com/track?loc=en_US&tracknum={tracking}",
                                                    "company": carrier or "UPS",
                                                },
                                                "line_items_by_fulfillment_order": [
                                                    {"fulfillment_order_id": fo['id']} for fo in open_fos
                                                ],
                                            }
                                        }
                                        code_f, body_f = http_request(
                                            "POST",
                                            f"https://{SHOP}/admin/api/2024-01/fulfillments.json",
                                            headers={
                                                "X-Shopify-Access-Token": SHOPIFY_TOKEN,
                                                "Content-Type": "application/json",
                                            },
                                            body=json.dumps(fulfillment_body).encode(),
                                        )
                                        if code_f in (200, 201):
                                            fulfilled_in_shopify = True
                                            f_data = json.loads(body_f)
                                            info['shopify_fulfillment_id'] = f_data.get('fulfillment', {}).get('id')
                                        else:
                                            shopify_error = f"HTTP {code_f}: {body_f[:200]}"
                                    else:
                                        shopify_error = "no open fulfillment_orders (already fulfilled?)"
                                else:
                                    shopify_error = f"GET fulfillment_orders HTTP {code_fo}"
                            except Exception as e:
                                shopify_error = f"exception: {e}"

                            newly_shipped.append({
                                'shopify_name': info.get('name'),
                                'shopify_id': sid,
                                'prodigi_id': pid,
                                'tracking': tracking,
                                'tracking_url': url,
                                'carrier': carrier,
                                'fulfilled_in_shopify': fulfilled_in_shopify,
                                'shopify_error': shopify_error,
                            })
                            info['notified_shipped'] = True
                            info['tracking'] = tracking
                            info['tracking_url'] = url
                            info['carrier'] = carrier
                            info['shipped_at'] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                            info['fulfilled_in_shopify'] = fulfilled_in_shopify
                            if shopify_error:
                                info['shopify_fulfillment_error'] = shopify_error
                            break
        except Exception as e:
            pass  # Don't fail the whole run on a single order lookup

    result['newly_shipped'] = newly_shipped

    save_state(state)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
