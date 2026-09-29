/**
 * compact_dom.js — Hyper-optimized in-page perception engine for Swades CUA
 * 
 * Features:
 * 1. Fast DOM traversal using createTreeWalker.
 * 2. Recursive traversal into Open Shadow DOMs and same-origin IFrames.
 * 3. Exact bounding box [left, top, width, height], center coordinates [x, y], and visibility checks.
 * 4. Occlusion hit-testing via document.elementFromPoint.
 * 5. Semantic label/name extraction (aria-label, aria-labelledby, placeholder, title, alt, value, innerText).
 * 6. Ephemeral tagging with data-swades-id="<index>".
 * 7. Structured element output and ultra-compact DSL format.
 * 8. Visual debugging overlay with floating numerical badges (__swades_show_overlay / __swades_clear_overlay).
 * 9. Universal compatibility (ES module, CommonJS, CDP / in-browser evaluation).
 */

const OVERLAY_CONTAINER_ID = '__swades_overlay_container';

const AD_HOST_KEYWORDS = [
  'doubleclick.net', 'googlesyndication.com', 'safeframe', 'google.com/recaptcha',
  'challenges.cloudflare.com', 'adnxs.com', 'rubiconproject.com', 'criteo.com',
  'adagio.js', 'sync pixels', 'amazon-adsystem.com', 'taboola.com', 'outbrain.com',
  'partnerpixels', 'google-analytics.com', '4dex.io', 'quantserve.com', 'scorecardresearch.com',
  'adroll.com', 'use1-x.d.adroll.com', 'yieldmo.com', 'openx.net', 'pubmatic.com', '__adroll'
];

function isAdElement(node) {
  if (!node) return false;
  const id = (node.id || '').toLowerCase();
  const cls = (typeof node.className === 'string' ? node.className : '').toLowerCase();
  const src = (node.src || node.href || '').toLowerCase();
  return AD_HOST_KEYWORDS.some(ad => id.includes(ad) || cls.includes(ad) || src.includes(ad));
}

/**
 * Clean up existing overlays
 */
function clearOverlay(doc) {
  const targetDoc = doc || (typeof document !== 'undefined' ? document : null);
  if (!targetDoc) return;
  const existing = targetDoc.getElementById ? targetDoc.getElementById(OVERLAY_CONTAINER_ID) : null;
  if (existing && existing.remove) {
    existing.remove();
  }
}

/**
 * Render visual debugging overlay with floating numerical badges and subtle bounding boxes
 */
function showOverlay(elements, doc) {
  const targetDoc = doc || (typeof document !== 'undefined' ? document : null);
  if (!targetDoc) return;

  const targetBody = targetDoc.body || targetDoc.documentElement;
  if (!targetBody) return;

  clearOverlay(targetDoc);

  const container = targetDoc.createElement('div');
  container.id = OVERLAY_CONTAINER_ID;
  container.setAttribute('data-swades-overlay', 'true');
  container.style.cssText = [
    'position: absolute',
    'top: 0',
    'left: 0',
    'width: 100%',
    'height: 100%',
    'pointer-events: none',
    'z-index: 2147483647',
    'overflow: visible'
  ].join(';');

  const win = targetDoc.defaultView || (typeof window !== 'undefined' ? window : null);
  const scrollX = win ? (win.scrollX || win.pageXOffset || 0) : 0;
  const scrollY = win ? (win.scrollY || win.pageYOffset || 0) : 0;

  for (const elInfo of elements) {
    const [left, top, width, height] = elInfo.bbox;
    if (width <= 0 || height <= 0) continue;

    const box = targetDoc.createElement('div');
    box.setAttribute('data-swades-overlay', 'true');
    box.style.cssText = [
      'position: absolute',
      `left: ${left + scrollX}px`,
      `top: ${top + scrollY}px`,
      `width: ${width}px`,
      `height: ${height}px`,
      'border: 1.5px solid rgba(255, 68, 68, 0.85)',
      'background: rgba(255, 68, 68, 0.08)',
      'box-sizing: border-box',
      'border-radius: 3px',
      'pointer-events: none'
    ].join(';');

    const badge = targetDoc.createElement('span');
    badge.setAttribute('data-swades-overlay', 'true');
    badge.textContent = `@${elInfo.index}`;
    badge.style.cssText = [
      'position: absolute',
      'top: -9px',
      'left: -2px',
      'background: #ffe600',
      'color: #000000',
      'font-weight: 800',
      'font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
      'font-size: 10px',
      'line-height: 12px',
      'padding: 1px 3px',
      'border-radius: 2px',
      'border: 1px solid #111111',
      'box-shadow: 0 1px 3px rgba(0,0,0,0.5)',
      'pointer-events: none',
      'white-space: nowrap'
    ].join(';');

    box.appendChild(badge);
    container.appendChild(box);
  }

  targetBody.appendChild(container);
}

/**
 * Determine if element is interactive or semantically important
 */
function isInteractiveCandidate(el) {
  const tag = el.tagName ? el.tagName.toUpperCase() : '';

  // Non-visual / metadata tags
  if (['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'HEAD', 'META', 'TITLE', 'LINK', 'BR', 'WBR', 'SVG', 'PATH'].includes(tag)) {
    return false;
  }

  // Standard interactive form / link elements
  if (['A', 'BUTTON', 'INPUT', 'SELECT', 'TEXTAREA', 'DETAILS', 'SUMMARY', 'OPTION'].includes(tag)) {
    return true;
  }

  // ARIA interactive roles
  const role = (el.getAttribute ? (el.getAttribute('role') || '') : '').toLowerCase();
  const interactiveRoles = [
    'button', 'link', 'checkbox', 'radio', 'tab', 'switch',
    'combobox', 'menuitem', 'menuitemcheckbox', 'menuitemradio',
    'option', 'searchbox', 'slider', 'spinbutton', 'textbox',
    'treeitem', 'dialog', 'alertdialog'
  ];
  if (role && interactiveRoles.includes(role)) {
    return true;
  }

  // Event handlers & editable states
  if (
    (el.hasAttribute && el.hasAttribute('onclick')) ||
    (el.hasAttribute && el.hasAttribute('onmousedown')) ||
    (el.hasAttribute && el.hasAttribute('onmouseup')) ||
    (el.hasAttribute && el.hasAttribute('data-action')) ||
    (el.hasAttribute && el.hasAttribute('data-clickable')) ||
    (el.hasAttribute && el.hasAttribute('jsaction'))
  ) {
    return true;
  }

  const contentEditable = el.getAttribute ? el.getAttribute('contenteditable') : null;
  if (contentEditable === '' || contentEditable === 'true') {
    return true;
  }

  const tabIndex = el.getAttribute ? el.getAttribute('tabindex') : null;
  if (tabIndex !== null && tabIndex !== '-1' && !isNaN(parseInt(tabIndex, 10))) {
    return true;
  }

  // Pointer cursor check
  const win = el.ownerDocument?.defaultView || (typeof window !== 'undefined' ? window : null);
  if (win && typeof win.getComputedStyle === 'function') {
    try {
      const style = win.getComputedStyle(el);
      if (style && style.cursor === 'pointer') {
        return true;
      }
    } catch {
      // Ignore style computation errors
    }
  }

  return false;
}

/**
 * Check element visibility according to rules:
 * - display != 'none'
 * - visibility != 'hidden' and visibility != 'collapse'
 * - opacity > 0.05
 * - rect.width >= 4 && rect.height >= 4
 * - intersects viewport bounds
 */
function checkElementVisibility(el, rect, win) {
  if (rect.width < 4 || rect.height < 4) {
    return false;
  }

  const doc = el.ownerDocument || (win ? win.document : null);
  const viewWidth = win ? Math.max(win.innerWidth || 0, win.outerWidth || 0, doc && doc.documentElement ? (doc.documentElement.scrollWidth || 0) : 0, 1280) : 1920;
  const viewHeight = win ? Math.max(win.innerHeight || 0, win.outerHeight || 0, doc && doc.documentElement ? (doc.documentElement.scrollHeight || 0) : 0, 1080) : 1080;

  // Viewport intersection check
  if (
    rect.bottom <= 0 ||
    rect.right <= 0 ||
    rect.left >= viewWidth ||
    rect.top >= viewHeight
  ) {
    return false;
  }

  if (win && typeof win.getComputedStyle === 'function') {
    try {
      const style = win.getComputedStyle(el);
      if (style.display === 'none') return false;
      if (style.visibility === 'hidden' || style.visibility === 'collapse') return false;
      const opacity = parseFloat(style.opacity || '1');
      if (!isNaN(opacity) && opacity <= 0.05) return false;
    } catch {
      // If getComputedStyle fails, proceed with geometric check
    }
  }

  return true;
}

/**
 * Occlusion hit-testing via elementFromPoint
 */
function isElementOccluded(el, center, doc) {
  if (!doc || typeof doc.elementFromPoint !== 'function') {
    return false;
  }

  const [cx, cy] = center;
  const win = doc.defaultView || (typeof window !== 'undefined' ? window : null);
  const viewWidth = win ? (win.innerWidth || 1920) : 1920;
  const viewHeight = win ? (win.innerHeight || 1080) : 1080;

  if (cx < 0 || cy < 0 || cx >= viewWidth || cy >= viewHeight) {
    return false;
  }

  try {
    const hitEl = doc.elementFromPoint(cx, cy);
    if (!hitEl) return false;

    // Overlay ignore
    if (hitEl.id === OVERLAY_CONTAINER_ID || (hitEl.hasAttribute && hitEl.hasAttribute('data-swades-overlay'))) {
      return false;
    }

    if (hitEl === el || (el.contains && el.contains(hitEl)) || (hitEl.contains && hitEl.contains(el))) {
      return false;
    }

    // Secondary corner probe (top-left & bottom-right inner offsets)
    const rect = el.getBoundingClientRect();
    const probePoints = [
      [rect.left + Math.min(8, Math.max(2, rect.width / 4)), rect.top + Math.min(8, Math.max(2, rect.height / 4))],
      [rect.right - Math.min(8, Math.max(2, rect.width / 4)), rect.bottom - Math.min(8, Math.max(2, rect.height / 4))]
    ];

    for (const [px, py] of probePoints) {
      if (px >= 0 && py >= 0 && px < viewWidth && py < viewHeight) {
        const probeHit = doc.elementFromPoint(px, py);
        if (probeHit && (probeHit === el || (el.contains && el.contains(probeHit)) || (probeHit.contains && probeHit.contains(el)))) {
          return false;
        }
      }
    }

    return true; // Completely occluded by an unrelated element
  } catch {
    return false;
  }
}

/**
 * Extract semantic name/label from element
 */
function extractSemanticLabel(el, doc) {
  // 1. aria-label
  const ariaLabel = el.getAttribute ? el.getAttribute('aria-label') : null;
  if (ariaLabel && ariaLabel.trim()) {
    return ariaLabel.trim();
  }

  // 2. aria-labelledby
  const ariaLabelledBy = el.getAttribute ? el.getAttribute('aria-labelledby') : null;
  if (ariaLabelledBy && doc) {
    const ids = ariaLabelledBy.split(/\s+/).filter(Boolean);
    const labelTexts = [];
    for (const id of ids) {
      const refEl = doc.getElementById ? doc.getElementById(id) : null;
      if (refEl) {
        const text = (refEl.innerText || refEl.textContent || '').trim();
        if (text) labelTexts.push(text);
      }
    }
    if (labelTexts.length > 0) {
      return labelTexts.join(' ');
    }
  }

  // 3. Associated <label> tag
  if (el.id && doc) {
    try {
      const labelEl = doc.querySelector ? doc.querySelector(`label[for="${CSS.escape(el.id)}"]`) : null;
      if (labelEl) {
        const text = (labelEl.innerText || labelEl.textContent || '').trim();
        if (text) return text;
      }
    } catch {
      // Ignore selector syntax error
    }
  }

  const parentLabel = el.closest ? el.closest('label') : null;
  if (parentLabel) {
    const text = (parentLabel.innerText || parentLabel.textContent || '').trim();
    if (text) return text;
  }

  // 4. placeholder
  const placeholder = el.getAttribute ? el.getAttribute('placeholder') : null;
  if (placeholder && placeholder.trim()) {
    return placeholder.trim();
  }

  // 5. title
  const title = el.getAttribute ? el.getAttribute('title') : null;
  if (title && title.trim()) {
    return title.trim();
  }

  // 6. alt (images / inputs)
  const alt = el.getAttribute ? el.getAttribute('alt') : null;
  if (alt && alt.trim()) {
    return alt.trim();
  }

  // 7. value for input/buttons
  const tag = el.tagName ? el.tagName.toUpperCase() : '';
  if (tag === 'INPUT' || tag === 'BUTTON') {
    const type = (el.getAttribute ? (el.getAttribute('type') || '') : '').toLowerCase();
    if (['submit', 'button', 'reset'].includes(type) && el.value) {
      return String(el.value).trim();
    }
  }

  // 8. innerText / textContent
  const rawText = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
  if (rawText) {
    return rawText.length > 120 ? rawText.slice(0, 117) + '...' : rawText;
  }

  return '';
}

/**
 * Generate CSS selector for element
 */
function generateCssSelector(el) {
  const tag = (el.tagName || '').toLowerCase();
  if (el.id && /^[a-zA-Z][a-zA-Z0-9_-]*$/.test(el.id)) {
    return `${tag}#${el.id}`;
  }

  const name = el.getAttribute ? el.getAttribute('name') : null;
  if (name) {
    return `${tag}[name="${name.replace(/"/g, '\\"')}"]`;
  }

  const role = el.getAttribute ? el.getAttribute('role') : null;
  if (role) {
    return `${tag}[role="${role}"]`;
  }

  const type = el.getAttribute ? el.getAttribute('type') : null;
  if (type) {
    return `${tag}[type="${type}"]`;
  }

  if (el.classList && el.classList.length > 0) {
    const validClasses = Array.from(el.classList)
      .filter(c => /^[a-zA-Z][a-zA-Z0-9_-]*$/.test(c))
      .slice(0, 2);
    if (validClasses.length > 0) {
      return `${tag}.${validClasses.join('.')}`;
    }
  }

  return tag;
}

/**
 * Generate robust XPath for element
 */
function generateXPath(el) {
  if (el.id) {
    return `//${(el.tagName || '').toLowerCase()}[@id='${el.id}']`;
  }
  const name = el.getAttribute ? el.getAttribute('name') : null;
  if (name) {
    return `//${(el.tagName || '').toLowerCase()}[@name='${name}']`;
  }

  const paths = [];
  let current = el;
  while (current && current.nodeType === 1) {
    let index = 1;
    let sibling = current.previousElementSibling;
    while (sibling) {
      if (sibling.nodeType === 1 && sibling.tagName === current.tagName) {
        index++;
      }
      sibling = sibling.previousElementSibling;
    }
    const tagName = (current.tagName || '').toLowerCase();
    paths.unshift(`${tagName}[${index}]`);
    if (current.tagName.toUpperCase() === 'BODY' || current.tagName.toUpperCase() === 'HTML') {
      break;
    }
    current = current.parentElement;
  }
  return '/' + paths.join('/');
}

/**
 * Format tag/role shorthand for compact DSL
 */
function getDslTag(tagName, role, type) {
  const tag = (tagName || '').toLowerCase();
  if (tag === 'button' || role === 'button') return 'btn';
  if (tag === 'a' || role === 'link') return 'a';
  if (tag === 'select' || role === 'combobox') return 'select';
  if (tag === 'textarea') return 'textarea';
  if (tag === 'input') {
    if (type === 'checkbox' || role === 'checkbox') return 'checkbox';
    if (type === 'radio' || role === 'radio') return 'radio';
    if (type === 'submit') return 'btn';
    return 'input';
  }
  return role || tag;
}

/**
 * Extract attributes map
 */
function extractAttributes(el) {
  const attrs = {};
  const interesting = [
    'id', 'name', 'type', 'placeholder', 'value', 'href', 'title',
    'role', 'aria-label', 'disabled', 'readonly', 'checked', 'selected',
    'autocomplete', 'required'
  ];

  for (const attr of interesting) {
    if (el.hasAttribute && el.hasAttribute(attr)) {
      attrs[attr] = el.getAttribute(attr);
    }
  }

  if (el.value !== undefined && el.value !== '' && !attrs.value) {
    attrs.value = String(el.value);
  }

  if (el.checked !== undefined && el.hasAttribute && el.hasAttribute('type') && ['checkbox', 'radio'].includes(el.getAttribute('type'))) {
    attrs.checked = Boolean(el.checked);
  }

  return attrs;
}

/**
 * Format single element to ultra-compact DSL string
 */
function formatElementDsl(item) {
  const dslTag = getDslTag(item.tagName, item.role, item.attributes.type);
  let idPart = item.attributes.id ? `#${item.attributes.id}` : '';
  const [cx, cy] = item.center;
  const [bx, by, bw, bh] = item.bbox;

  const parts = [`[@${item.index}]`, `${dslTag}${idPart}`];

  if (item.text && dslTag !== 'input' && dslTag !== 'textarea') {
    parts.push(`'${item.text.replace(/'/g, "\\'")}'`);
  }

  parts.push(`[x:${cx}, y:${cy}, w:${bw}, h:${bh}]`);

  if (item.attributes.value && dslTag !== 'btn') {
    parts.push(`value="${item.attributes.value.replace(/"/g, '\\"')}"`);
  }
  if (item.attributes.placeholder) {
    parts.push(`placeholder="${item.attributes.placeholder.replace(/"/g, '\\"')}"`);
  }
  if (item.attributes.href) {
    parts.push(`href="${item.attributes.href}"`);
  }
  if (item.attributes.checked !== undefined) {
    parts.push(`checked=${item.attributes.checked}`);
  }
  if (item.attributes.disabled) {
    parts.push('disabled');
  }

  return parts.join(' ');
}

/**
 * Recursively collect candidates using TreeWalker across Document, Shadow Roots, and same-origin IFrames
 */
function collectDomCandidates(rootNode, frameOffset = { x: 0, y: 0 }, results = []) {
  if (!rootNode) return results;

  const doc = rootNode.ownerDocument || (rootNode.nodeType === 9 ? rootNode : (typeof document !== 'undefined' ? document : null));
  const win = doc ? (doc.defaultView || (typeof window !== 'undefined' ? window : null)) : null;

  const walkerRoot = rootNode.nodeType === 9 ? (rootNode.body || rootNode.documentElement || rootNode) : rootNode;

  // Use createTreeWalker for fast in-page DOM traversal
  let walker = null;
  try {
    const treeDoc = walkerRoot.ownerDocument || doc;
    if (treeDoc && typeof treeDoc.createTreeWalker === 'function') {
      walker = treeDoc.createTreeWalker(
        walkerRoot,
        typeof NodeFilter !== 'undefined' ? NodeFilter.SHOW_ELEMENT : 1,
        {
          acceptNode(node) {
            if (!node || node.nodeType !== 1) return 2; // FILTER_REJECT
            const tag = node.tagName ? node.tagName.toUpperCase() : '';
            if (['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'HEAD'].includes(tag)) {
              return 2; // FILTER_REJECT
            }
            if (node.id === OVERLAY_CONTAINER_ID || (node.hasAttribute && node.hasAttribute('data-swades-overlay'))) {
              return 2; // FILTER_REJECT
            }
            if (isAdElement(node)) {
              return 2; // FILTER_REJECT
            }
            return 1; // FILTER_ACCEPT
          }
        },
        false
      );
    }
  } catch {
    walker = null;
  }

  const nodes = [];
  if (walker) {
    // If the root node itself is an element (e.g. shadowRoot host or body if walker starts after root)
    if (walkerRoot !== doc && walkerRoot.nodeType === 1) {
      nodes.push(walkerRoot);
    }
    let curr = walker.nextNode();
    while (curr) {
      nodes.push(curr);
      curr = walker.nextNode();
    }
  } else if (walkerRoot.querySelectorAll) {
    if (walkerRoot.nodeType === 1) nodes.push(walkerRoot);
    nodes.push(...walkerRoot.querySelectorAll('*'));
  }

  for (const node of nodes) {
    if (!node || node.nodeType !== 1) continue;

    if (isAdElement(node)) continue;

    // 1. Traverse Open Shadow DOM if present
    if (node.shadowRoot) {
      collectDomCandidates(node.shadowRoot, frameOffset, results);
    }

    // 2. Traverse Same-Origin IFrame if present
    const tag = node.tagName ? node.tagName.toUpperCase() : '';
    if (tag === 'IFRAME' || tag === 'FRAME') {
      try {
        if (!isAdElement(node)) {
          const iframeDoc = node.contentDocument || (node.contentWindow ? node.contentWindow.document : null);
          if (iframeDoc) {
            const iframeRect = node.getBoundingClientRect();
            const nextOffset = {
              x: frameOffset.x + iframeRect.left,
              y: frameOffset.y + iframeRect.top
            };
            collectDomCandidates(iframeDoc, nextOffset, results);
          }
        }
      } catch {
        // Cross-origin iframe security error — skip gracefully
      }
    }

    // 3. Check candidate interactivity & semantics
    if (isInteractiveCandidate(node)) {
      try {
        const rawRect = node.getBoundingClientRect();
        const rect = {
          left: rawRect.left + frameOffset.x,
          top: rawRect.top + frameOffset.y,
          width: rawRect.width,
          height: rawRect.height,
          right: rawRect.left + frameOffset.x + rawRect.width,
          bottom: rawRect.top + frameOffset.y + rawRect.height
        };

        if (checkElementVisibility(node, rect, win)) {
          const cx = Math.round(rect.left + rect.width / 2);
          const cy = Math.round(rect.top + rect.height / 2);
          const center = [cx, cy];

          results.push({
            node,
            doc,
            rect,
            center,
            bbox: [Math.round(rect.left), Math.round(rect.top), Math.round(rect.width), Math.round(rect.height)]
          });
        }
      } catch {
        // Ignore bounding box calculation failures
      }
    }
  }

  return results;
}

/**
 * Main perception function
 * @param {Object} [options]
 * @param {Document} [options.document] - Document to inspect (defaults to global document)
 * @param {boolean} [options.showOverlay=false] - Whether to render visual debugging overlay
 * @param {boolean} [options.clearOverlay=false] - Whether to clear visual debugging overlay
 * @param {boolean} [options.filterOccluded=true] - Filter out occluded background elements
 * @returns {{ elements: Array<Object>, dsl: string }}
 */
function getCompactDom(options = {}) {
  const targetDoc = options.document || (typeof document !== 'undefined' ? document : null);
  if (!targetDoc) {
    return { elements: [], dsl: '' };
  }

  if (options.clearOverlay) {
    clearOverlay(targetDoc);
  }

  // Clear previous data-swades-id attributes
  try {
    const prevTagged = targetDoc.querySelectorAll ? targetDoc.querySelectorAll('[data-swades-id]') : [];
    if (prevTagged && prevTagged.forEach) {
      prevTagged.forEach(el => el.removeAttribute('data-swades-id'));
    }
  } catch {
    // Ignore cleanup query errors
  }

  const rawCandidates = collectDomCandidates(targetDoc, { x: 0, y: 0 }, []);
  const filterOccluded = options.filterOccluded !== false;

  const elements = [];
  const dslLines = [];
  let index = 0;

  for (const item of rawCandidates) {
    const { node, doc, center, bbox } = item;

    // Occlusion hit-testing
    if (filterOccluded && isElementOccluded(node, center, doc)) {
      continue;
    }

    // Ephemeral tagging
    try {
      node.setAttribute('data-swades-id', String(index));
    } catch {
      // Ignore attribute set error on read-only/detached nodes
    }

    const tagName = (node.tagName || '').toLowerCase();
    const role = node.getAttribute ? (node.getAttribute('role') || '') : '';
    const text = extractSemanticLabel(node, doc);
    const attributes = extractAttributes(node);
    const selector = generateCssSelector(node);
    const xpath = generateXPath(node);

    const elementRecord = {
      index,
      tagName,
      role,
      text,
      center,
      bbox,
      selector,
      xpath,
      attributes
    };

    elements.push(elementRecord);
    dslLines.push(formatElementDsl(elementRecord));
    index++;
  }

  const dsl = dslLines.join('\n');

  if (options.showOverlay) {
    showOverlay(elements, targetDoc);
  }

  return { elements, dsl };
}

// Attach to window for browser / CDP evaluation
if (typeof window !== 'undefined') {
  window.__swades_get_compact_dom = (opts) => getCompactDom(opts);
  window.__swades_show_overlay = (elems, doc) => showOverlay(elems, doc);
  window.__swades_clear_overlay = (doc) => clearOverlay(doc);
  window.getCompactDom = getCompactDom;
  window.showOverlay = showOverlay;
  window.clearOverlay = clearOverlay;
}

export { getCompactDom, showOverlay, clearOverlay };





