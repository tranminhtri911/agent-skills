/*
 * e2e-evidence highlight (E2E-004): red frames drawn into the page just before a step screenshot, so whoever
 * opens the image sees at once which area, which title and which value the step checks.
 *
 * Load, draw, capture, clear (Playwright; any browser tool that evaluates JavaScript works the same way):
 *   await page.addScriptTag({ path: '<skill dir>/assets/highlight.js' });
 *   const found = await page.evaluate((targets) => window.e2eHighlight(targets), [
 *     { kind: 'area',  selector: '#calendar-memo-section' },
 *     { kind: 'title', text: 'カレンダーメモ' },
 *     { kind: 'value', selector: 'textarea[name=memo]', line: '(1,100円)×1', label: '備品 = (1,100円)×1' },
 *   ]);
 *   // every entry of `found` must have found: true, otherwise fix the target and draw again
 *   await page.screenshot({ path: '<case dir>/step02_memo-equipment-lines.png' });
 *   await page.evaluate(() => window.e2eClearHighlight());
 *
 * A target names one thing on the screen:
 *   selector: 'css'          the first visible element matching the selector (`nth` picks another match)
 *   text: 'visible text'     the innermost visible element whose text, or field value, contains the text
 *   within: 'css'            limits a text search to that container
 *   line: 'text'             with a textarea/input: only the line of its value containing the text
 *   rect: [x, y, w, h]       page coordinates, for framing a spot in an image shown in a blank page
 * and how to draw it:
 *   kind: 'area'  dashed frame around the section the step is about
 *         'title' frame around the label or heading of the value
 *         'value' (default) thick frame with a light fill around the value being checked
 *   label: 'caption'         numbered tag next to the frame: the title and the expected value, e.g. '合計 = 3,300円'
 *
 * The frames sit outside the element and leave the text readable; nothing in the page is changed except an
 * overlay layer (and the scroll position of a field whose line is out of view). Returns one entry per
 * target: { index, found, reason }.
 */
(function installHighlight(global) {
  'use strict';

  const LAYER_ID = 'e2e-highlight-layer';
  const FRAME_GAP_PX = 4;
  const LINE_FRAME_GAP_PX = 2;
  const TAG_GAP_PX = 6;
  const RED = '#e11d48';
  const FIELD_STYLE_PROPERTIES = [
    'boxSizing', 'width', 'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft',
    'borderTopWidth', 'borderRightWidth', 'borderBottomWidth', 'borderLeftWidth',
    'fontFamily', 'fontSize', 'fontWeight', 'fontStyle', 'letterSpacing', 'lineHeight',
    'textTransform', 'wordSpacing', 'textIndent', 'tabSize',
  ];

  function isVisible(element) {
    const rect = element.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) {
      return false;
    }
    const style = getComputedStyle(element);
    return style.visibility !== 'hidden' && style.display !== 'none' && Number(style.opacity) !== 0;
  }

  function isField(element) {
    return element.tagName === 'TEXTAREA' || element.tagName === 'INPUT' || element.tagName === 'SELECT';
  }

  function textOf(element) {
    if (element.tagName === 'SELECT') {
      return Array.from(element.selectedOptions).map((option) => option.textContent).join(' ');
    }
    if (isField(element)) {
      return element.value || '';
    }
    return element.innerText || '';
  }

  function normalize(text) {
    return String(text).replace(/\s+/g, ' ').trim();
  }

  /* Innermost visible elements containing the text, in document order. */
  function findByText(text, withinSelector) {
    const container = withinSelector ? document.querySelector(withinSelector) : document.body;
    if (!container) {
      return [];
    }
    const wanted = normalize(text);
    const candidates = Array.from(container.querySelectorAll('*')).filter((element) => {
      if (element.closest('#' + LAYER_ID) || !isVisible(element)) {
        return false;
      }
      return normalize(textOf(element)).includes(wanted);
    });
    return candidates.filter((element) => {
      const hasMatchingChild = candidates.some((other) => other !== element && element.contains(other));
      return !hasMatchingChild;
    });
  }

  function findElement(target) {
    const index = target.nth || 0;
    if (target.selector) {
      const matches = Array.from(document.querySelectorAll(target.selector)).filter(isVisible);
      return matches[index] || null;
    }
    if (target.text) {
      return findByText(target.text, target.within)[index] || null;
    }
    return null;
  }

  /* A copy of the field's text box laid out the same way, used to measure where one line of its value is. */
  function buildFieldMirror(field, textBefore, lineText) {
    const style = getComputedStyle(field);
    const mirror = document.createElement('div');
    for (const property of FIELD_STYLE_PROPERTIES) {
      mirror.style[property] = style[property];
    }
    // The text wraps at the field's inner width, without its scrollbar.
    const paddingWidth = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
    mirror.style.boxSizing = 'content-box';
    mirror.style.width = (field.clientWidth - paddingWidth) + 'px';
    mirror.style.borderStyle = 'solid';
    mirror.style.borderColor = 'transparent';
    mirror.style.position = 'absolute';
    mirror.style.visibility = 'hidden';
    mirror.style.top = '0';
    mirror.style.left = '-99999px';
    mirror.style.whiteSpace = field.tagName === 'INPUT' ? 'pre' : 'pre-wrap';
    mirror.style.overflowWrap = 'break-word';
    mirror.textContent = textBefore;
    const lineSpan = document.createElement('span');
    lineSpan.textContent = lineText || ' ';
    mirror.appendChild(lineSpan);
    document.body.appendChild(mirror);
    return { mirror, lineSpan };
  }

  /* Where the line of a field's value containing `needle` sits inside the field's content, or null. */
  function measureFieldLine(field, needle) {
    const value = field.value || '';
    const start = value.indexOf(needle);
    if (start < 0) {
      return null;
    }
    const lineStart = value.lastIndexOf('\n', start) + 1;
    const lineEndIndex = value.indexOf('\n', start);
    const lineEnd = lineEndIndex < 0 ? value.length : lineEndIndex;
    const { mirror, lineSpan } = buildFieldMirror(field, value.slice(0, lineStart), value.slice(lineStart, lineEnd));
    const mirrorRect = mirror.getBoundingClientRect();
    const pieces = Array.from(lineSpan.getClientRects());
    mirror.remove();
    if (pieces.length === 0) {
      return null;
    }
    return {
      top: Math.min(...pieces.map((piece) => piece.top)) - mirrorRect.top,
      bottom: Math.max(...pieces.map((piece) => piece.bottom)) - mirrorRect.top,
      left: Math.min(...pieces.map((piece) => piece.left)) - mirrorRect.left,
      right: Math.max(...pieces.map((piece) => piece.right)) - mirrorRect.left,
    };
  }

  /*
   * Scroll each field once so that all of its lines named by the targets are in view (the first one wins when
   * they do not fit together). Done before any frame is measured: scrolling later would move frames drawn earlier.
   */
  function scrollFieldsToShowLines(targets) {
    const linesByField = new Map();
    for (const target of targets) {
      const field = target.line ? findElement(target) : null;
      const line = field && isField(field) ? measureFieldLine(field, target.line) : null;
      if (line) {
        const lines = linesByField.get(field) || [];
        lines.push(line);
        linesByField.set(field, lines);
      }
    }
    linesByField.forEach((lines, field) => {
      const firstTop = Math.min(...lines.map((line) => line.top));
      const lastBottom = Math.max(...lines.map((line) => line.bottom));
      const allInView = firstTop >= field.scrollTop && lastBottom <= field.scrollTop + field.clientHeight;
      if (!allInView) {
        const spanHeight = lastBottom - firstTop;
        const margin = Math.max(0, (field.clientHeight - spanHeight) / 3);
        field.scrollTop = Math.max(0, firstTop - margin);
      }
    });
  }

  /* Viewport rectangle of a measured line, clipped to the field; null when the line is scrolled out of view. */
  function fieldLineRect(field, line) {
    const fieldRect = field.getBoundingClientRect();
    const top = Math.max(fieldRect.top, fieldRect.top + line.top - field.scrollTop);
    const bottom = Math.min(fieldRect.bottom, fieldRect.top + line.bottom - field.scrollTop);
    const left = Math.max(fieldRect.left, fieldRect.left + line.left - field.scrollLeft);
    const right = Math.min(fieldRect.right, fieldRect.left + line.right - field.scrollLeft);
    if (bottom - top < 4 || right <= left) {
      return null;
    }
    return { left, top, width: right - left, height: bottom - top };
  }

  /* Page-coordinate rectangle of a target, or a reason why there is none. */
  function locate(target) {
    if (Array.isArray(target.rect)) {
      const [left, top, width, height] = target.rect;
      return { box: { left, top, width, height } };
    }
    const element = findElement(target);
    if (!element) {
      return { reason: 'no visible element for ' + JSON.stringify(target.selector || target.text) };
    }
    let viewportRect = element.getBoundingClientRect();
    if (target.line) {
      if (!isField(element)) {
        return { reason: '`line` needs a textarea or input, got <' + element.tagName.toLowerCase() + '>' };
      }
      const line = measureFieldLine(element, target.line);
      if (!line) {
        return { reason: 'the field value has no line containing ' + JSON.stringify(target.line) };
      }
      viewportRect = fieldLineRect(element, line);
      if (!viewportRect) {
        return { reason: 'the line ' + JSON.stringify(target.line) + ' is out of the field\'s view: capture it in another screenshot' };
      }
    }
    return {
      box: {
        left: viewportRect.left + global.scrollX,
        top: viewportRect.top + global.scrollY,
        width: viewportRect.width,
        height: viewportRect.height,
      },
    };
  }

  function ensureLayer() {
    let layer = document.getElementById(LAYER_ID);
    if (!layer) {
      layer = document.createElement('div');
      layer.id = LAYER_ID;
      layer.setAttribute('aria-hidden', 'true');
      layer.style.cssText = 'position:absolute;left:0;top:0;width:0;height:0;z-index:2147483647;pointer-events:none';
      document.documentElement.appendChild(layer);
    }
    return layer;
  }

  function frameStyle(kind) {
    if (kind === 'area') {
      return 'border:2px dashed ' + RED + ';border-radius:8px';
    }
    if (kind === 'title') {
      return 'border:2px solid ' + RED + ';border-radius:6px';
    }
    return 'border:3px solid ' + RED + ';border-radius:6px;background:rgba(250,204,21,.22);'
      + 'box-shadow:0 0 0 2px rgba(255,255,255,.85)';
  }

  function expand(box, gap) {
    return { left: box.left - gap, top: box.top - gap, width: box.width + gap * 2, height: box.height + gap * 2 };
  }

  function overlaps(first, second) {
    const separateHorizontally = first.left + first.width <= second.left || second.left + second.width <= first.left;
    const separateVertically = first.top + first.height <= second.top || second.top + second.height <= first.top;
    return !separateHorizontally && !separateVertically;
  }

  function drawFrame(layer, frameBox, kind) {
    const frame = document.createElement('div');
    frame.style.cssText = 'position:absolute;box-sizing:border-box;' + frameStyle(kind)
      + ';left:' + frameBox.left + 'px;top:' + frameBox.top + 'px'
      + ';width:' + frameBox.width + 'px;height:' + frameBox.height + 'px';
    layer.appendChild(frame);
  }

  /* Where a tag may go, in order of preference: right of the frame, left of it, above, below. */
  function tagPositions(frameBox, tagWidth, tagHeight) {
    const middleTop = frameBox.top + (frameBox.height - tagHeight) / 2;
    return [
      { left: frameBox.left + frameBox.width + TAG_GAP_PX, top: middleTop },
      { left: frameBox.left - TAG_GAP_PX - tagWidth, top: middleTop },
      { left: frameBox.left, top: frameBox.top - TAG_GAP_PX - tagHeight },
      { left: frameBox.left, top: frameBox.top + frameBox.height + TAG_GAP_PX },
    ];
  }

  /* Page rectangles of the visible text on screen, so tags can avoid covering other values. */
  function visibleTextBoxes() {
    const boxes = [];
    const viewportHeight = document.documentElement.clientHeight;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const range = document.createRange();
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const parent = node.parentElement;
      if (!node.textContent.trim() || !parent || parent.closest('#' + LAYER_ID) || isField(parent)) {
        continue;
      }
      range.selectNodeContents(node);
      for (const rect of range.getClientRects()) {
        if (rect.width > 0 && rect.bottom > 0 && rect.top < viewportHeight) {
          boxes.push({ left: rect.left + global.scrollX, top: rect.top + global.scrollY, width: rect.width, height: rect.height });
        }
      }
    }
    return boxes;
  }

  /*
   * Numbered tag next to its frame. Preference: on screen, covering no frame, no other tag and no page text;
   * then the same allowing a shift along the screen edge; then allowing text to be covered.
   */
  function drawTag(layer, frameBox, text, obstacles, textBoxes) {
    const tag = document.createElement('div');
    tag.textContent = text;
    tag.style.cssText = 'position:absolute;left:0;top:0;background:' + RED + ';color:#fff;'
      + 'font:700 12px/18px system-ui,sans-serif;padding:0 7px;border-radius:4px;white-space:nowrap;max-width:460px;'
      + 'overflow:hidden;text-overflow:ellipsis;box-shadow:0 1px 3px rgba(0,0,0,.35)';
    layer.appendChild(tag);
    const tagWidth = tag.offsetWidth;
    const tagHeight = tag.offsetHeight;
    const screenLeft = global.scrollX;
    const screenRight = global.scrollX + document.documentElement.clientWidth;
    const onScreen = tagPositions(frameBox, tagWidth, tagHeight).map((position) => ({
      left: Math.min(Math.max(position.left, screenLeft), screenRight - tagWidth),
      top: Math.max(position.top, 0),
      width: tagWidth,
      height: tagHeight,
      shifted: position.left < screenLeft || position.left + tagWidth > screenRight,
    }));
    const coversFrame = (position) => obstacles.some((obstacle) => overlaps(position, obstacle));
    const coversText = (position) => textBoxes.some((textBox) => overlaps(position, textBox));
    const preferences = [
      (position) => !position.shifted && !coversFrame(position) && !coversText(position),
      (position) => !coversFrame(position) && !coversText(position),
      (position) => !position.shifted && !coversFrame(position),
      (position) => !coversFrame(position),
    ];
    let chosen = onScreen[2];
    for (const isAcceptable of preferences) {
      const match = onScreen.find(isAcceptable);
      if (match) {
        chosen = match;
        break;
      }
    }
    tag.style.left = chosen.left + 'px';
    tag.style.top = chosen.top + 'px';
    obstacles.push(chosen);
  }

  function scrollFirstTargetIntoView(targets) {
    const first = targets.find((target) => !Array.isArray(target.rect));
    const element = first ? findElement(first) : null;
    if (element) {
      element.scrollIntoView({ block: 'center', inline: 'nearest' });
    }
  }

  /**
   * Draw the frames of one step. Clears earlier frames first.
   * @param {Array<object>} targets  see the header comment
   * @param {{scroll?: boolean}} options  scroll (default true) centres the first target before drawing
   * @returns {Array<{index:number, found:boolean, reason?:string}>}
   */
  function e2eHighlight(targets, options) {
    const settings = Object.assign({ scroll: true }, options || {});
    e2eClearHighlight();
    if (settings.scroll) {
      scrollFirstTargetIntoView(targets);
    }
    scrollFieldsToShowLines(targets);
    const layer = ensureLayer();
    const results = [];
    const drawn = [];
    targets.forEach((target, index) => {
      const kind = target.kind || 'value';
      const located = locate(target);
      if (!located.box) {
        results.push({ index, found: false, reason: located.reason });
        return;
      }
      const frameBox = expand(located.box, target.line ? LINE_FRAME_GAP_PX : FRAME_GAP_PX);
      drawFrame(layer, frameBox, kind);
      drawn.push({ target, kind, frameBox });
      results.push({ index, found: true });
    });
    // Tags go on after every frame is drawn so that none of them covers a frame drawn later.
    const obstacles = drawn.filter((item) => item.kind !== 'area').map((item) => item.frameBox);
    const textBoxes = visibleTextBoxes();
    let tagNumber = 0;
    for (const item of drawn) {
      if (item.kind === 'area' && !item.target.label) {
        continue;
      }
      tagNumber += 1;
      const text = item.target.label ? tagNumber + '  ' + item.target.label : String(tagNumber);
      drawTag(layer, item.frameBox, text, obstacles, textBoxes);
    }
    return results;
  }

  function e2eClearHighlight() {
    const layer = document.getElementById(LAYER_ID);
    if (layer) {
      layer.remove();
    }
  }

  global.e2eHighlight = e2eHighlight;
  global.e2eClearHighlight = e2eClearHighlight;
})(window);
