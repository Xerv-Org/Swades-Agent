import test from 'node:test';
import assert from 'node:assert/strict';
import { getCompactDom, showOverlay, clearOverlay } from '../src/compact_dom.js';

// Minimal DOM mock environment for testing in Node
function createMockElement(tag, attrs = {}, styles = {}, rect = { left: 0, top: 0, width: 100, height: 40 }) {
  const children = [];
  const attributes = { ...attrs };
  let shadowRoot = null;
  let contentDoc = null;

  const el = {
    nodeType: 1,
    tagName: tag.toUpperCase(),
    attributes,
    style: { ...styles },
    children,
    parentElement: null,
    previousElementSibling: null,
    ownerDocument: null,
    value: attrs.value !== undefined ? attrs.value : '',
    checked: attrs.checked !== undefined ? attrs.checked : false,
    innerText: attrs.innerText || '',
    textContent: attrs.textContent || attrs.innerText || '',
    classList: {
      length: 0,
      [Symbol.iterator]: function* () {}
    },
    getAttribute(name) {
      return attributes[name] !== undefined ? String(attributes[name]) : null;
    },
    setAttribute(name, val) {
      attributes[name] = String(val);
      if (name === 'id' && el.ownerDocument) {
        el.ownerDocument.elementsById[String(val)] = el;
      }
    },
    removeAttribute(name) {
      if (name === 'id' && el.ownerDocument && attributes.id) {
        delete el.ownerDocument.elementsById[attributes.id];
      }
      delete attributes[name];
    },
    hasAttribute(name) {
      return attributes[name] !== undefined;
    },
    getBoundingClientRect() {
      return {
        left: rect.left,
        top: rect.top,
        width: rect.width,
        height: rect.height,
        right: rect.left + rect.width,
        bottom: rect.top + rect.height,
        x: rect.left,
        y: rect.top
      };
    },
    appendChild(child) {
      child.parentElement = el;
      child.ownerDocument = el.ownerDocument;
      if (child.id && el.ownerDocument) {
        el.ownerDocument.elementsById[child.id] = child;
      }
      if (children.length > 0) {
        child.previousElementSibling = children[children.length - 1];
      }
      children.push(child);
      return child;
    },
    remove() {
      if (el.parentElement) {
        const idx = el.parentElement.children.indexOf(el);
        if (idx !== -1) el.parentElement.children.splice(idx, 1);
      }
      if (el.id && el.ownerDocument) {
        delete el.ownerDocument.elementsById[el.id];
      }
    },
    contains(target) {
      if (target === el) return true;
      let curr = target;
      while (curr) {
        if (curr === el) return true;
        curr = curr.parentElement;
      }
      return false;
    },
    closest(selector) {
      if (selector === 'label' && el.parentElement && el.parentElement.tagName === 'LABEL') {
        return el.parentElement;
      }
      return null;
    },
    get shadowRoot() {
      return shadowRoot;
    },
    set shadowRoot(sr) {
      shadowRoot = sr;
    },
    get contentDocument() {
      return contentDoc;
    },
    set contentDocument(cd) {
      contentDoc = cd;
    }
  };

  Object.defineProperty(el, 'id', {
    get: () => attributes.id || '',
    set: (v) => {
      attributes.id = v;
      if (el.ownerDocument) {
        el.ownerDocument.elementsById[v] = el;
      }
    }
  });

  return el;
}

function createMockDocument() {
  const doc = {
    nodeType: 9,
    body: null,
    documentElement: null,
    elementsById: {},
    defaultView: {
      innerWidth: 1920,
      innerHeight: 1080,
      scrollX: 0,
      scrollY: 0,
      getComputedStyle(el) {
        return {
          display: el.style.display || 'block',
          visibility: el.style.visibility || 'visible',
          opacity: el.style.opacity || '1',
          cursor: el.style.cursor || 'default'
        };
      }
    },
    createElement(tag) {
      const el = createMockElement(tag);
      el.ownerDocument = doc;
      return el;
    },
    getElementById(id) {
      if (doc.elementsById[id]) return doc.elementsById[id];
      function findId(node) {
        if (!node) return null;
        if (node.id === id) return node;
        if (node.children) {
          for (const c of node.children) {
            const found = findId(c);
            if (found) return found;
          }
        }
        return null;
      }
      return findId(doc.documentElement);
    },
    querySelector(sel) {
      if (sel.startsWith('label[for="')) {
        const id = sel.match(/label\[for="([^"]+)"\]/)?.[1];
        if (id) {
          const matchId = `label_for_${id}`;
          return doc.getElementById(matchId);
        }
      }
      return null;
    },
    querySelectorAll(sel) {
      const results = [];
      function walk(node) {
        if (!node) return;
        if (sel === '[data-swades-id]' && node.hasAttribute && node.hasAttribute('data-swades-id')) {
          results.push(node);
        }
        if (node.children) {
          for (const c of node.children) walk(c);
        }
      }
      walk(doc.documentElement);
      return results;
    },
    createTreeWalker(root, whatToShow, filter) {
      const nodes = [];
      function collect(node) {
        if (!node) return;
        if (node !== root && node.nodeType === 1) {
          let accept = 1;
          if (filter && typeof filter.acceptNode === 'function') {
            accept = filter.acceptNode(node);
          }
          if (accept === 1) {
            nodes.push(node);
          }
        }
        if (node.children) {
          for (const c of node.children) collect(c);
        }
      }
      collect(root);
      let idx = 0;
      return {
        nextNode() {
          if (idx < nodes.length) {
            return nodes[idx++];
          }
          return null;
        }
      };
    },
    elementFromPoint(x, y) {
      return null;
    }
  };

  const html = doc.createElement('html');
  const body = doc.createElement('body');
  html.appendChild(body);
  doc.documentElement = html;
  doc.body = body;

  return doc;
}

test('Compact DOM Perception Tests', async (t) => {
  await t.test('1. Basic interactive elements perception and DSL format', () => {
    const doc = createMockDocument();

    const input = createMockElement('input', { id: 'nickname', value: 'SwadesBot', placeholder: 'Nickname' }, {}, { left: 222, top: 222, width: 180, height: 36 });
    const btn = createMockElement('button', { innerText: 'Play' }, {}, { left: 456, top: 222, width: 96, height: 36 });
    const link = createMockElement('a', { href: '/settings', innerText: 'Settings' }, {}, { left: 610, top: 225, width: 80, height: 30 });

    doc.body.appendChild(input);
    doc.body.appendChild(btn);
    doc.body.appendChild(link);

    const result = getCompactDom({ document: doc });

    assert.equal(result.elements.length, 3);
    assert.equal(input.getAttribute('data-swades-id'), '0');
    assert.equal(btn.getAttribute('data-swades-id'), '1');
    assert.equal(link.getAttribute('data-swades-id'), '2');

    // Check first element properties
    const el0 = result.elements[0];
    assert.equal(el0.index, 0);
    assert.equal(el0.tagName, 'input');
    assert.equal(el0.selector, 'input#nickname');
    assert.deepEqual(el0.center, [312, 240]);
    assert.deepEqual(el0.bbox, [222, 222, 180, 36]);
    assert.equal(el0.attributes.value, 'SwadesBot');
    assert.equal(el0.attributes.placeholder, 'Nickname');

    // Check second element properties
    const el1 = result.elements[1];
    assert.equal(el1.index, 1);
    assert.equal(el1.tagName, 'button');
    assert.equal(el1.text, 'Play');
    assert.deepEqual(el1.center, [504, 240]);
    assert.deepEqual(el1.bbox, [456, 222, 96, 36]);

    // Check DSL output lines
    const dslLines = result.dsl.split('\n');
    assert.ok(dslLines[0].includes('[@0] input#nickname [x:312, y:240, w:180, h:36] value="SwadesBot" placeholder="Nickname"'));
    assert.ok(dslLines[1].includes("[@1] btn 'Play' [x:504, y:240, w:96, h:36]"));
    assert.ok(dslLines[2].includes("[@2] a 'Settings' [x:650, y:240, w:80, h:30] href=\"/settings\""));
  });

  await t.test('2. Open Shadow DOM recursive traversal', () => {
    const doc = createMockDocument();
    const host = createMockElement('custom-card', {}, {}, { left: 50, top: 50, width: 300, height: 200 });

    const shadowRoot = createMockElement('shadow-root');
    shadowRoot.ownerDocument = doc;
    const shadowBtn = createMockElement('button', { innerText: 'Submit in Shadow' }, {}, { left: 80, top: 100, width: 120, height: 40 });
    shadowRoot.appendChild(shadowBtn);
    host.shadowRoot = shadowRoot;

    doc.body.appendChild(host);

    const result = getCompactDom({ document: doc });
    assert.equal(result.elements.length, 1);
    assert.equal(result.elements[0].text, 'Submit in Shadow');
  });

  await t.test('3. Same-origin IFrame traversal with offset translation', () => {
    const doc = createMockDocument();
    const iframe = createMockElement('iframe', {}, {}, { left: 100, top: 200, width: 500, height: 400 });

    const iframeDoc = createMockDocument();
    const iframeInput = createMockElement('input', { id: 'search-box', placeholder: 'Search...' }, {}, { left: 50, top: 60, width: 200, height: 40 });
    iframeDoc.body.appendChild(iframeInput);
    iframe.contentDocument = iframeDoc;

    doc.body.appendChild(iframe);

    const result = getCompactDom({ document: doc });
    assert.equal(result.elements.length, 1);
    const item = result.elements[0];
    // Offset translated: left = 100 + 50 = 150, top = 200 + 60 = 260
    assert.deepEqual(item.bbox, [150, 260, 200, 40]);
    assert.deepEqual(item.center, [250, 280]);
  });

  await t.test('4. Visibility filters (hidden, opacity, zero rect, out-of-viewport)', () => {
    const doc = createMockDocument();

    const hidden1 = createMockElement('button', { innerText: 'DispNone' }, { display: 'none' }, { left: 10, top: 10, width: 50, height: 30 });
    const hidden2 = createMockElement('button', { innerText: 'VisHidden' }, { visibility: 'hidden' }, { left: 10, top: 10, width: 50, height: 30 });
    const hidden3 = createMockElement('button', { innerText: 'LowOpacity' }, { opacity: '0.02' }, { left: 10, top: 10, width: 50, height: 30 });
    const tiny = createMockElement('button', { innerText: 'TooTiny' }, {}, { left: 10, top: 10, width: 2, height: 2 });
    const offscreen = createMockElement('button', { innerText: 'Offscreen' }, {}, { left: 2500, top: 3000, width: 100, height: 40 });
    const visible = createMockElement('button', { innerText: 'Visible' }, {}, { left: 10, top: 10, width: 100, height: 40 });

    doc.body.appendChild(hidden1);
    doc.body.appendChild(hidden2);
    doc.body.appendChild(hidden3);
    doc.body.appendChild(tiny);
    doc.body.appendChild(offscreen);
    doc.body.appendChild(visible);

    const result = getCompactDom({ document: doc });
    assert.equal(result.elements.length, 1);
    assert.equal(result.elements[0].text, 'Visible');
  });

  await t.test('5. Semantic label extraction priorities (aria-label, aria-labelledby, label[for], title, alt)', () => {
    const doc = createMockDocument();

    const ariaEl = createMockElement('button', { 'aria-label': 'Close Dialog', title: 'Ignore Title' }, {}, { left: 10, top: 10, width: 30, height: 30 });
    const altEl = createMockElement('input', { type: 'image', alt: 'Submit Icon' }, {}, { left: 50, top: 10, width: 30, height: 30 });

    doc.body.appendChild(ariaEl);
    doc.body.appendChild(altEl);

    const result = getCompactDom({ document: doc });
    assert.equal(result.elements.length, 2);
    assert.equal(result.elements[0].text, 'Close Dialog');
    assert.equal(result.elements[1].text, 'Submit Icon');
  });

  await t.test('6. Overlay show and clear functionality', () => {
    const doc = createMockDocument();
    const btn = createMockElement('button', { innerText: 'Click Me' }, {}, { left: 50, top: 50, width: 100, height: 40 });
    doc.body.appendChild(btn);

    const result = getCompactDom({ document: doc, showOverlay: true });
    assert.equal(result.elements.length, 1);

    const overlay = doc.body.children.find(c => c.id === '__swades_overlay_container');
    assert.ok(overlay, 'Overlay container should be injected');
    assert.equal(overlay.children.length, 1);

    clearOverlay(doc);
    const overlayAfter = doc.body.children.find(c => c.id === '__swades_overlay_container');
    assert.equal(overlayAfter, undefined, 'Overlay should be removed');
  });

  await t.test('7. Occlusion filtering via elementFromPoint', () => {
    const doc = createMockDocument();
    const occludedBtn = createMockElement('button', { innerText: 'Covered' }, {}, { left: 100, top: 100, width: 100, height: 40 });
    const modalBackdrop = createMockElement('div', { id: 'modal-backdrop' }, {}, { left: 0, top: 0, width: 1920, height: 1080 });
    const modalBtn = createMockElement('button', { innerText: 'Confirm' }, {}, { left: 200, top: 200, width: 100, height: 40 });

    doc.body.appendChild(occludedBtn);
    doc.body.appendChild(modalBackdrop);
    modalBackdrop.appendChild(modalBtn);

    // Mock elementFromPoint: over occludedBtn (x=150, y=120) returns modalBackdrop, over modalBtn (x=250, y=220) returns modalBtn
    doc.elementFromPoint = (x, y) => {
      if (x >= 200 && x <= 300 && y >= 200 && y <= 240) {
        return modalBtn;
      }
      return modalBackdrop;
    };

    const result = getCompactDom({ document: doc, filterOccluded: true });
    assert.equal(result.elements.length, 1);
    assert.equal(result.elements[0].text, 'Confirm');
  });
});
