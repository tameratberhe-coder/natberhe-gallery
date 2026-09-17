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
        json.dump(state, f, indent=2, default=str)


def shopify_get_order_status(order_id):
    """Light re-check of an order's current cancellation/refund state before acting on it."""
    url = f"https://{SHOP}/admin/api/2024-01/orders/{order_id}.json?fields=id,cancelled_at,financial_status,fulfillment_status"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN}
    code, body = http_request("GET", url, headers=headers)
    if code != 200:
        return None
    try:
        return json.loads(body).get("order", {})
    except json.JSONDecodeError:
        return None


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


# Hard price ceiling for anything this router is allowed to treat as a print.
# Real print prices top out around $255-$400 across the whole catalog; every
# genuine one-of-one original starts at $15,000. A same-shaped variant title
# (e.g. an original painting's own '36" x 36"' dimension label) must never be
# mistaken for a print's size variant just because both parse as "WxH" — that
# would route a real original to Prodigi for canvas printing and ship a cheap
# reproduction to the customer instead of the actual painting. This ceiling is
# the primary guard against that failure mode, independent of any variant
# title heuristic.
PRINT_PRICE_CEILING = 1000.0


def product_is_print(product_id, line_item):
    """Heuristic: print if variant size matches a Prodigi-compatible size AND
    the price is consistent with an actual print (never an original painting)."""
    variant_title = line_item.get("variant_title") or ""
    if not variant_title or variant_title == "Default Title":
        return False
    size = normalize_size(variant_title)
    if size is None:
        return False
    try:
        price = float(line_item.get("price") or 0)
    except (TypeError, ValueError):
        price = 0.0
    if price > PRINT_PRICE_CEILING:
        return False
    return True


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
    routed_line_item_ids = []
    non_print_line_item_ids = []
    for li in order.get("line_items", []):
        if not product_is_print(li.get("product_id"), li):
            skipped.append(
                f"line {li.get('id')} '{li.get('title')}' (variant: {li.get('variant_title')!r}) not a recognized print"
            )
            non_print_line_item_ids.append(li.get("id"))
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
        routed_line_item_ids.append(li.get("id"))

    return {
        "shippingMethod": "Budget",
        "merchantReference": f"shopify-{order.get('name')}-auto",
        "recipient": recipient,
        "items": items,
    }, skipped, routed_line_item_ids, non_print_line_item_ids


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


def attempt_shopify_fulfillment(sid, tracking, url, carrier, line_item_ids):
    """Fulfill only the specific routed line items (not the whole order), so a print
    shipping never falsely marks an accompanying original painting as shipped.
    Returns (fulfilled_ok, fulfillment_id, error_message)."""
    code_fo, body_fo = http_request(
        "GET",
        f"https://{SHOP}/admin/api/2024-01/orders/{sid}/fulfillment_orders.json",
        headers={"X-Shopify-Access-Token": SHOPIFY_TOKEN},
    )
    if code_fo != 200:
        return False, None, f"GET fulfillment_orders HTTP {code_fo}"

    fos = json.loads(body_fo).get("fulfillment_orders", [])
    line_item_ids = set(line_item_ids or [])
    fo_line_items_by_fo = {}
    for fo in fos:
        if fo.get("status") not in ("open", "in_progress"):
            continue
        matches = [
            {"id": foli["id"], "quantity": foli.get("quantity", 1)}
            for foli in fo.get("line_items", [])
            if (not line_item_ids) or (foli.get("line_item_id") in line_item_ids)
        ]
        if matches:
            fo_line_items_by_fo[fo["id"]] = matches

    if not fo_line_items_by_fo:
        return False, None, "no open fulfillment_orders matched the routed line items (already fulfilled or cancelled?)"

    all_fo_line_items = [item for items in fo_line_items_by_fo.values() for item in items]
    fulfillment_body = {
        "fulfillment": {
            "message": f"Shipped from Prodigi production. Tracking: {tracking}",
            "notify_customer": True,
            "tracking_info": {
                "number": tracking,
                "url": url or f"https://www.ups.com/track?loc=en_US&tracknum={tracking}",
                "company": carrier or "UPS",
            },
            "fulfillment_order_line_items": all_fo_line_items,
        }
    }
    code_f, body_f = http_request(
        "POST",
        f"https://{SHOP}/admin/api/2024-01/fulfillments.json",
        headers={"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"},
        body=fulfillment_body,
    )
    if code_f in (200, 201):
        f_data = json.loads(body_f)
        return True, f_data.get("fulfillment", {}).get("id"), None
    return False, None, f"HTTP {code_f}: {body_f[:200]}"


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
        "skipped_needs_review": [],
        "cancelled_needs_review": [],
        "recovered_fulfillments": [],
    }

    try:
        orders = shopify_get_unfulfilled_orders()
    except Exception as e:
        result["failures"] = 1
        result["failure_details"].append({"error": f"shopify_fetch: {e}"})
        save_state(state)
        print(json.dumps(result, default=str))
        return

    result["orders_checked"] = len(orders)

    for order in orders:
        order_id = str(order.get("id"))
        order_name = order.get("name") or f"id-{order_id}"

        if order_id in routed:
            continue  # idempotent skip

        payload, skipped, routed_line_item_ids, non_print_line_item_ids = build_prodigi_payload(order, sku_map)

        if not payload["items"]:
            # Order has no routable items. Most of the time this is a normal original-painting
            # order (correctly out of scope for this router). Flag it for a human to glance at
            # once, rather than silently disappearing forever, in case it's actually a print
            # product this heuristic doesn't recognize (e.g. a single fixed-size listing with
            # no size variant).
            routed[order_id] = {
                "name": order_name,
                "status": "skipped_no_print_items",
                "reasons": skipped,
                "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "flagged": True,
            }
            result["skipped_needs_review"].append({
                "shopify_name": order_name,
                "shopify_id": order_id,
                "reasons": skipped,
            })
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
                "line_item_ids": routed_line_item_ids,
            }
            result["newly_routed"] += 1
            result["new_orders"].append({
                "shopify_name": order_name,
                "prodigi_id": prodigi_id,
                "total": total,
            })
            if outcome == "CreatedWithIssues":
                result["new_orders"][-1]["warning"] = "Prodigi accepted this order WITH ISSUES (e.g. low image resolution). Worth a manual look before it ships."
        else:
            result["failures"] += 1
            result["failure_details"].append({
                "shopify_name": order_name,
                "shopify_id": order_id,
                "http_code": code,
                "outcome": outcome,
                "response": response if len(json.dumps(response, default=str)) < 800 else "(truncated)",
            })

    # Re-surface any older skipped orders that were never explicitly reviewed yet
    # (covers orders skipped by earlier versions of this script, before this flag existed).
    for sid, info in routed.items():
        if info.get("status") == "skipped_no_print_items" and not info.get("flagged"):
            info["flagged"] = True
            result["skipped_needs_review"].append({
                "shopify_name": info.get("name"),
                "shopify_id": sid,
                "reasons": info.get("reasons", []),
                "note": "previously skipped before review-alerting existed",
            })

    # Check Prodigi for newly-shipped orders (tracking writeback notification)
    newly_shipped = []
    for sid, info in routed.items():
        if info.get('status') != 'routed':
            continue
        pid = info.get('prodigi_id')
        if not pid or info.get('notified_shipped'):
            continue

        # Refund/cancellation guard: don't auto-fulfill (and don't let the customer
        # think it shipped) if the Shopify order was cancelled or refunded after routing.
        order_status = shopify_get_order_status(sid)
        if order_status and (order_status.get("cancelled_at") or order_status.get("financial_status") in ("refunded", "partially_refunded", "voided")):
            result["cancelled_needs_review"].append({
                "shopify_name": info.get("name"),
                "shopify_id": sid,
                "prodigi_id": pid,
                "financial_status": order_status.get("financial_status"),
                "cancelled_at": order_status.get("cancelled_at"),
                "note": "Order was cancelled/refunded after being routed to Prodigi. Check whether the Prodigi order needs manual cancellation.",
            })
            info["notified_shipped"] = True  # stop re-checking; a human is now looking at it
            info["cancelled_after_routing"] = True
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
                            try:
                                fulfilled_in_shopify, fulfillment_id, shopify_error = attempt_shopify_fulfillment(
                                    sid, tracking, url, carrier, info.get('line_item_ids')
                                )
                                if fulfillment_id:
                                    info['shopify_fulfillment_id'] = fulfillment_id
                            except Exception as e:
                                fulfilled_in_shopify = False
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

    # Retry pass: orders where we already know they shipped (notified_shipped=True) but the
    # Shopify fulfillment call itself failed last time (fulfilled_in_shopify=False). Previously
    # this state was permanent and silent; now we retry every run until it succeeds or the
    # order is flagged cancelled above.
    for sid, info in routed.items():
        if info.get('status') != 'routed':
            continue
        if not info.get('notified_shipped') or info.get('fulfilled_in_shopify') or info.get('cancelled_after_routing'):
            continue
        tracking = info.get('tracking')
        if not tracking:
            continue
        try:
            fulfilled_ok, fulfillment_id, shopify_error = attempt_shopify_fulfillment(
                sid, tracking, info.get('tracking_url'), info.get('carrier'), info.get('line_item_ids')
            )
        except Exception as e:
            fulfilled_ok, fulfillment_id, shopify_error = False, None, f"exception: {e}"
        info['fulfilled_in_shopify'] = fulfilled_ok
        if fulfillment_id:
            info['shopify_fulfillment_id'] = fulfillment_id
        if fulfilled_ok:
            info.pop('shopify_fulfillment_error', None)
            result['recovered_fulfillments'].append({
                'shopify_name': info.get('name'),
                'shopify_id': sid,
                'tracking': tracking,
                'note': 'Shopify fulfillment had previously failed and just succeeded on retry. Customer is being notified now.',
            })
        else:
            info['shopify_fulfillment_error'] = shopify_error

    result['newly_shipped'] = newly_shipped

    save_state(state)
    print(json.dumps(result, default=str))


if __name__ == "__main__":
    main()
