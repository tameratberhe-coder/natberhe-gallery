
// ============ SIGNED BY THE ARTIST PANEL (product pages, originals only) ============
function renderSignaturePanel() {
  try {
    var path = window.location.pathname || '';
    if (!/^\/products\//.test(path)) return;

    var price = null;
    var productType = '';
    try {
      if (window.ShopifyAnalytics && window.ShopifyAnalytics.meta && window.ShopifyAnalytics.meta.product) {
        var prod = window.ShopifyAnalytics.meta.product;
        productType = prod.type || '';
        if (prod.variants && prod.variants.length > 0 && prod.variants[0].price != null) {
          price = parseFloat(prod.variants[0].price);
          // Shopify's injected price is usually in cents
          if (price > 100000) price = price / 100;
        }
      }
    } catch (e) {}

    var isOriginalType = /oil painting/i.test(productType);
    var isHighValue = (price !== null && price > 500);
    if (!isOriginalType && !isHighValue) return;

    if (document.querySelector('.signature-panel')) return; // avoid double-inject

    var panelHTML =
      '<div class="signature-panel">' +
        '<div class="signature-panel-inner">' +
          '<svg class="signature-mark" viewBox="0 0 400 120" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-label="Nat Berhe signature">' +
            '<path d="M 15 90 C 15 90, 22 40, 25 35 C 27 32, 30 48, 35 60 C 45 82, 55 55, 58 40 C 60 32, 62 45, 65 60 C 68 72, 72 82, 75 88"/>' +
            '<path d="M 88 70 C 82 65, 78 72, 80 82 C 82 90, 92 90, 96 82 C 98 76, 98 70, 96 65 M 96 65 L 98 90"/>' +
            '<path d="M 108 50 L 108 88 C 108 92, 112 92, 116 88 M 102 68 L 116 66"/>' +
            '<path d="M 140 30 L 140 92 M 140 30 C 155 30, 168 34, 168 46 C 168 55, 158 60, 148 60 C 160 60, 175 66, 175 78 C 175 90, 158 92, 140 92"/>' +
            '<path d="M 188 78 C 200 78, 205 72, 202 66 C 199 62, 190 62, 188 70 C 186 78, 192 90, 205 87"/>' +
            '<path d="M 215 65 L 215 90 M 215 72 C 219 65, 226 63, 232 68"/>' +
            '<path d="M 245 30 L 245 92 M 245 68 C 250 62, 262 62, 265 70 L 265 92"/>' +
            '<path d="M 278 78 C 290 78, 295 72, 292 66 C 289 62, 280 62, 278 70 C 276 78, 282 90, 295 87"/>' +
            '<path d="M 305 90 C 320 92, 340 88, 358 85 C 365 84, 370 82, 370 78" stroke-width="1.5"/>' +
          '</svg>' +
          '<div class="signature-panel-label">SIGNED BY THE ARTIST</div>' +
          '<p class="signature-panel-text">Each original artwork is signed by Nat Berhe on the back of the canvas, with the year completed. Every piece ships with a certificate of authenticity.</p>' +
        '</div>' +
      '</div>';

    var anchor = document.querySelector('form[action*="/cart/add"]') ||
                 document.querySelector('.product-form') ||
                 document.querySelector('.product__description') ||
                 document.querySelector('[data-product-description]') ||
                 document.querySelector('main');
    if (anchor && anchor.insertAdjacentHTML) {
      anchor.insertAdjacentHTML('afterend', panelHTML);
    } else if (document.body) {
      document.body.insertAdjacentHTML('beforeend', panelHTML);
    }
  } catch (err) {
    console.warn('renderSignaturePanel failed', err);
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', renderSignaturePanel);
} else {
  renderSignaturePanel();
}
