# Nat Berhe Gallery — Auction Copy Removal + Full Site Audit
Final report — July 8, 2026

## Summary

Continued from a prior session that had removed all *visible* auction copy from
`index.html` and `catalog.js`, deployed to Shopify, and pushed to GitHub. On
resuming, a fresh audit found the prior session's "zero auction mentions"
claim was incomplete: **38 leftover "auction" references remained in
`index.html`**, all dead CSS (for the removed auction page) and one dead JS
init function. These have now been fully removed, verified, redeployed, and
pushed.

## What was found and fixed this session

1. **Dead CSS block 1** (lines ~324-365 of the prior file): `.auction-header`,
   `.auction-date`, `.auction-desc`, `.auction-grid`, `.auction-lot*`,
   `.auction-bid-btn`, `.auction-buy-btn`, plus the entire `/* Bidder
   Registration */` block (`.bidder-reg`, `.bidder-form`, `.bidder-submit`,
   etc.) — all orphaned styles for the auction page div removed in the prior
   session. Confirmed via full-document search that **no HTML element uses
   any of these classes** before deleting.
2. **Dead CSS in a mobile `@media` block**: 17 auction/bidder/countdown
   override lines nested inside a shared mobile media query — removed
   individually, leaving the rest of that media query (gallery, artist,
   contact, footer rules) intact.
3. **Dead CSS block 2, "AUCTION V2"** (~133 lines): `.auc-hero`, `.auc-grain`,
   keyframes, and related auction hero/grid v2 styles, also unused by any
   remaining markup.
4. **Dead JS**: removed the `aucInit()` function (which only called
   already-guarded, now-inert `aucRenderCards`/`aucInitRegistration`) and its
   call site in the page-init sequence.
5. **Cache-bust comment cleanup**: the prior session had left a literal
   `cache-bust-auction-removal-<timestamp>` HTML comment on line 1 containing
   the word "auction" — renamed to `cache-bust-cleanup-<timestamp>`.

`catalog.js` was intentionally left as-is: its 14 "auction" occurrences are
all code-level (the `AUCTION_LOTS` array, `aucXxx` function names, and
comments), consistent with the task's explicit instruction to **guard, not
delete**, the auction functions. `navigateTo()` already redirects any
`#auction` hash to `home`.

## Validation performed (all pass)

- `grep -i auction index.html` → **0 matches** (was 38 at start of this
  session)
- JSON-LD block still parses as valid JSON (`json.loads`)
- Inline `<style>` block: 522 open braces / 522 close braces (balanced)
- Inline `<script>` block: passes `node --check`
- `<div>` tag balance: 252 open / 252 close
- All 8 page sections present: home, gallery, prints, artist, contact,
  process, track, press (auction page confirmed absent, no orphan page div)
- Brand/style rules confirmed intact:
  - "Figurative Abstract Expressionism" (no hyphen) — 8 occurrences
  - "Eritrean American" (no hyphen) — 10 occurrences
  - "Natnael" — 17 occurrences, "Nathnael" typo — 0 occurrences
  - "ACQUIRE" — 0 occurrences; "BUY NOW" — present
  - "Based in Los Angeles" — 3 occurrences (footer intact)
  - Em dash (—) / en dash (–) — 0 occurrences anywhere in the file
  - Hamburger menu (`id="hamburgerBtn"`) has no `onclick`; touchend binding
    lives in `layout/theme.liquid` (outside these two source files, confirmed
    live) exactly as required
  - Global `error` and `unhandledrejection` handlers present

## Deploy

Ran `deploy_full.py` against all 4 Shopify themes on store
`fbea3c-0e.myshopify.com`:
- `183912333612` (live/main)
- `183911973164` (backup)
- `182801858860` (legacy backup)
- `182801662252` (legacy backup)

All 4 themes returned `OK` for `templates/index.liquid` and all `catalog*.js`
asset aliases. Verified directly via the Shopify Admin API that the live
theme's `templates/index.liquid` asset:
- Size: 149,320 bytes, matching local file exactly
- `updated_at`: 2026-07-08T16:29:24-07:00
- **0 "auction" mentions in the stored asset** (confirmed via direct
  byte-for-byte fetch of the asset content, not just the deploy response)

## KNOWN ISSUE — live custom-domain cache staleness (unresolved)

Despite the backend theme asset being 100% correct and verified clean:

- `https://natberhegallery.com/` continues to serve the **old** cached
  homepage (80 "auction" keyword matches) even after the fix was redeployed
  and after ~4+ minutes of waiting and repeated cache-busting attempts
  (unique query strings, `Cache-Control`/`Pragma: no-cache` headers).
- The direct `https://fbea3c-0e.myshopify.com/` (primary Shopify domain,
  theme preview) correctly redirects and, when checked via
  `?preview_theme_id=`, returns the **correct, clean (0 auction matches)**
  content — confirming the theme itself is fixed.
- Cloudflare's `cf-cache-status: DYNAMIC` header on natberhegallery.com shows
  Cloudflare is *not* caching the response (passthrough to origin each
  request), so the staleness is happening at Shopify's origin/edge rendering
  layer tied specifically to the custom domain, not at Cloudflare.
- This exact symptom (custom domain stuck on stale content while the
  myshopify.com domain and Admin API both reflect the fix) was also observed
  and extensively diagnosed in the immediately preceding session, which spent
  over 30 minutes trying cache-busting techniques (unique comments, theme
  republish via PUT, alternate template checks) without resolving it. This
  session reproduced the identical pattern in miniature, confirming it's a
  Shopify platform-side propagation delay/anomaly for this specific custom
  domain, not a defect in the code, deploy script, or theme configuration.

**Recommendation:** Re-check `https://natberhegallery.com/` again in the next
30 to 60 minutes. If it is still serving stale content beyond that window,
this warrants a Shopify Support ticket, since two independent
sessions/deploys, hours apart, have hit the same custom-domain cache
staleness with no available remediation via the Admin API.

## Audit results (unaffected by the homepage cache issue — all pass)

| Check | Result |
|---|---|
| Homepage HTTP status | 200 |
| Product page (`/products/the-witness`) | 200 |
| Product page (`/products/divine-frequency`) | 200 |
| Collection page (`/collections/all`) | 200 |
| Press page (`/pages/press`) | 200 |
| Shopify product count (Admin API) | 211 |
| CDN image URLs referenced (index.html + catalog.js) | 164 unique, spot-checked all 200 |

## Git / GitHub

Repo: `tameratberhe-coder/natberhe-gallery`, branch `master`.

- Commit `cc13c2bc60b6673615060e6c7a2c8839d5270e47` (prior session): "Remove
  all auction copy post July 6 2026 auction" — removed visible auction copy,
  guarded catalog.js auction functions.
- Commit `d3f105a` (this session): "Remove remaining dead auction CSS/JS
  (unused since auction page removal)" — 1 file changed, 1 insertion(+), 200
  deletions(-).
- Both pushed successfully to `origin/master`
  (`c3db8bb..cc13c2b` then `cc13c2b..d3f105a`).
- `.bak_original` backup files (`index.html.bak_original`,
  `catalog.js.bak_original`) remain intentionally untracked/uncommitted in
  the working directory for rollback reference.

## Files

- `/home/user/workspace/natberhe-gallery/index.html` — 149,320 bytes (down
  from 174,526 bytes at the start of the whole task, and 166,195 bytes after
  the prior session's incomplete pass)
- `/home/user/workspace/natberhe-gallery/catalog.js` — 132,458 bytes
  (auction functions guarded, not deleted, per task instructions)
- `/home/user/workspace/natberhe-gallery/deploy_full.py` — unchanged, used to
  push to Shopify
- `/home/user/workspace/natberhe-gallery/index.html.bak_original`,
  `catalog.js.bak_original` — pre-edit backups
