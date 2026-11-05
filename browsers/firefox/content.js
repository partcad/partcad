/*
 * PartCAD, 2026
 *
 * Licensed under Apache License, Version 2.0.
 *
 * The page half of the PartCAD login extension. It is loaded into every
 * top-level page and does nothing there unless the background says a login is
 * in progress and names this page's origin. Then it shows the banner and the
 * guide, reads the storage keys and DOM values the background asks it for,
 * and passes on what the user types into the banner. It is never told a
 * captured value back -- only which ones have been captured.
 *
 * On `pc login`'s own start page it does one thing instead: hands the spec on
 * that page to the background.
 *
 * Everything it shows lives in closed shadow roots, so that the page's styles
 * cannot reach in and its scripts cannot read what is typed into the banner.
 *
 * Byte-identical in `browsers/chromium` and `browsers/firefox`.
 */
(function () {
  "use strict";

  if (globalThis.__partcadLoginContent || window.top !== window) {
    return;
  }
  globalThis.__partcadLoginContent = true;

  const api = globalThis.browser || globalThis.chrome;
  const L = globalThis.PartcadLogin;

  const POLL_MS = 1000;
  const TICK_MS = 400;
  const ASK_DEBOUNCE_MS = 250;

  // Said instead of the guide on a page a site has put a bot check in front of.
  // Said, and nothing more: PartCAD captures credentials and does not work
  // around a site's checks, so the extension never clicks, scripts or reads
  // the widget, and treats its cookies like any other.
  const CHALLENGE_TEXT = "Confirm you are human on this page \u2014 the login continues once the site lets you in.";
  // The scripts of the check itself. Not ".../scripts/jsd/": that is
  // Cloudflare's "JavaScript detections", which it adds to the ordinary pages
  // of a site it protects, and which would otherwise hide the guide on all of
  // them.
  const CHALLENGE_SCRIPT = /\/cdn-cgi\/challenge-platform\/(?!scripts\/jsd\/)/;

  function send(message) {
    try {
      return Promise.resolve(api.runtime.sendMessage(message)).catch(() => null);
    } catch (error) {
      // The extension was reloaded or removed under this page.
      return Promise.resolve(null);
    }
  }

  function sleep(milliseconds) {
    return new Promise((resolve) => setTimeout(resolve, milliseconds));
  }

  function element(tag, className, parent) {
    const node = document.createElement(tag);
    if (className) {
      node.className = className;
    }
    if (parent) {
      parent.appendChild(node);
    }
    return node;
  }

  // Styles for a shadow root. A constructed sheet first, because a page's
  // Content-Security-Policy can forbid inline <style> and does not govern the
  // CSS object model; a <style> element where constructing one is refused.
  function style(root, css) {
    try {
      const sheet = new CSSStyleSheet();
      sheet.replaceSync(css);
      root.adoptedStyleSheets = [sheet];
      if (root.adoptedStyleSheets.length === 1) {
        return;
      }
    } catch (error) {
      // Fall through to the element.
    }
    element("style", null, root).textContent = css;
  }

  // A shadow host the page's own CSS cannot move or hide: these properties are
  // set inline and !important, which no stylesheet of the page outranks.
  function host(tag, css) {
    const node = document.createElement(tag);
    node.style.cssText = "all: initial !important; display: block !important; " + css;
    return { node: node, root: node.attachShadow({ mode: "closed" }) };
  }

  // --- The start page ---------------------------------------------------------

  // What the start page shows of the extension, for the person looking at it
  // and for the page itself: `data-partcad-login` on <html> says whether the
  // extension took the login ("accepted") or not ("refused").
  function note(state, text) {
    document.documentElement.setAttribute("data-partcad-login", state);
    let box = document.getElementById("partcad-login-extension");
    if (!box) {
      box = document.createElement("p");
      box.id = "partcad-login-extension";
      box.setAttribute("role", "status");
      (document.body || document.documentElement).prepend(box);
    }
    box.setAttribute("data-state", state);
    box.textContent = text;
  }

  async function startPage() {
    const holder = document.getElementById("partcad-login-spec");
    if (!holder) {
      return;
    }
    let spec;
    try {
      spec = JSON.parse(holder.textContent);
    } catch (error) {
      note("refused", "The PartCAD extension could not read the login request on this page: " + error.message);
      return;
    }
    let answer = null;
    // The background may still be starting with the browser.
    for (let attempt = 0; attempt < 40 && !answer; attempt += 1) {
      answer = await send({ type: "start", spec: spec });
      if (!answer) {
        await sleep(250);
      }
    }
    if (!answer) {
      note("refused", "The PartCAD extension is installed but did not answer.");
    } else if (answer.ok) {
      note("accepted", "The PartCAD extension is opening " + answer.title + "\u2026");
    } else {
      note("refused", answer.error);
    }
  }

  if (L.startNonce(location.href)) {
    startPage();
    return;
  }

  // --- Every other page -------------------------------------------------------

  const BANNER_CSS = `
    .bar {
      box-sizing: border-box;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px 16px;
      width: 100%;
      padding: 10px 16px;
      background: #1d2026;
      color: #f4f4f5;
      border-top: 3px solid #f2b705;
      box-shadow: 0 -2px 14px rgba(0, 0, 0, 0.35);
      font: 14px/1.4 system-ui, -apple-system, "Segoe UI", Roboto, Ubuntu, sans-serif;
      text-align: left;
    }
    :host([data-edge="top"]) .bar {
      border-top: 0;
      border-bottom: 3px solid #f2b705;
      box-shadow: 0 2px 14px rgba(0, 0, 0, 0.35);
    }
    .main { flex: 1 1 320px; min-width: 0; }
    .title { margin: 0; font-weight: 600; }
    .title .brand { color: #f2b705; }
    .guide { margin: 2px 0 0; color: #ffe08a; }
    .guide:empty { display: none; }
    .status { margin: 2px 0 0; color: #c9ccd1; }
    .status[data-kind="error"] { color: #ff9b8f; }
    .captures { display: flex; flex-wrap: wrap; gap: 4px 6px; margin: 6px 0 0; padding: 0; list-style: none; }
    .capture {
      padding: 1px 8px;
      border: 1px solid #4a4f59;
      border-radius: 10px;
      color: #c9ccd1;
      font-size: 12px;
    }
    .capture[data-captured="true"] { border-color: #2f9e5b; color: #8ee0ad; }
    .capture[data-captured="true"]::before { content: "\\2713  "; }
    .asks { display: flex; flex-wrap: wrap; gap: 8px 12px; }
    .asks:empty { display: none; }
    .ask { display: flex; align-items: center; gap: 6px; }
    .ask input {
      box-sizing: border-box;
      width: 16em;
      padding: 5px 8px;
      border: 1px solid #6b717c;
      border-radius: 4px;
      background: #ffffff;
      color: #1d2026;
      font: inherit;
    }
    .ask[data-captured="true"] input { border-color: #2f9e5b; }
    .ask input[aria-invalid="true"] { border-color: #ff9b8f; box-shadow: 0 0 0 1px #ff9b8f; }
    .ask .tick { color: #8ee0ad; visibility: hidden; }
    .ask[data-captured="true"] .tick { visibility: visible; }
    .actions { display: flex; gap: 8px; }
    button {
      padding: 6px 14px;
      border-radius: 4px;
      font: inherit;
      font-weight: 600;
      cursor: pointer;
    }
    button.done { border: 1px solid #f2b705; background: #f2b705; color: #1d2026; }
    button.done:disabled { border-color: #4a4f59; background: #3a3e46; color: #8b9099; cursor: default; }
    button.cancel { border: 1px solid #6b717c; background: transparent; color: #f4f4f5; }
    button:focus-visible, input:focus-visible { outline: 2px solid #ffe08a; outline-offset: 2px; }
  `;

  const GUIDE_CSS = `
    .spot {
      position: fixed;
      box-sizing: border-box;
      border-radius: 6px;
      box-shadow: 0 0 0 3px #f2b705, 0 0 0 200vmax rgba(10, 12, 16, 0.55);
      pointer-events: none;
    }
    .pointer {
      position: fixed;
      width: 48px;
      height: 48px;
      pointer-events: none;
      transform-origin: 50% 50%;
      transform: rotate(var(--angle, 0deg));
      animation: partcad-nudge 1.1s ease-in-out infinite;
      filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.6));
    }
    .label {
      position: fixed;
      box-sizing: border-box;
      max-width: 320px;
      padding: 8px 12px;
      border-radius: 6px;
      background: #f2b705;
      color: #1d2026;
      font: 600 14px/1.35 system-ui, -apple-system, "Segoe UI", Roboto, Ubuntu, sans-serif;
      box-shadow: 0 2px 10px rgba(0, 0, 0, 0.45);
      pointer-events: none;
    }
    @keyframes partcad-nudge {
      0%, 100% { transform: rotate(var(--angle, 0deg)) translateX(0); }
      50% { transform: rotate(var(--angle, 0deg)) translateX(-12px); }
    }
    @media (prefers-reduced-motion: reduce) {
      .pointer { animation: none; }
    }
  `;

  let answer = null;
  let pollTimer = null;
  let polling = false;
  let pollAgain = false;
  let ticker = null;
  let observer = null;
  let layoutQueued = false;
  let lastHref = location.href;
  let banner = null;
  let overlay = null;
  let scrolledTo = null;
  let challenged = false;
  // What each script element was found to be, so that a page's large inline
  // scripts are read once rather than on every tick.
  const scripts = new WeakMap();

  function collect() {
    if (!answer) {
      return null;
    }
    const report = { storage: {}, dom: {}, doneSelector: false };
    for (const task of answer.storage) {
      try {
        const value = window[task.area].getItem(task.key);
        if (typeof value === "string") {
          report.storage[task.name] = value;
        }
      } catch (error) {
        // Storage this page may not open (a sandboxed document, a policy).
      }
    }
    for (const task of answer.dom) {
      const node = query(task.selector);
      if (!node) {
        continue;
      }
      const value = task.attribute ? node.getAttribute(task.attribute) : node[task.property];
      if (value !== null && value !== undefined) {
        report.dom[task.name] = String(value).trim();
      }
    }
    if (answer.doneSelector) {
      const wanted = answer.doneSelector;
      report.doneSelector = queryAll(wanted.selector).some((node) => L.textMatches(wanted.contains, node));
    }
    return report;
  }

  function query(selector) {
    try {
      return document.querySelector(selector);
    } catch (error) {
      return null;
    }
  }

  function queryAll(selector) {
    try {
      return Array.from(document.querySelectorAll(selector));
    } catch (error) {
      return [];
    }
  }

  async function poll() {
    if (polling) {
      pollAgain = true;
      return;
    }
    polling = true;
    clearTimeout(pollTimer);
    const first = answer === null;
    const next = await send({ type: "poll", url: location.href, report: collect() });
    polling = false;
    if (!apply(next)) {
      if (pollAgain) {
        pollAgain = false;
        poll();
      }
      return;
    }
    // Straight away after the first answer: it said what to read here, and
    // the second poll is the one that reads it.
    const delay = pollAgain || first ? 30 : POLL_MS;
    pollAgain = false;
    pollTimer = setTimeout(poll, delay);
  }

  function apply(next) {
    if (!next || !next.active) {
      deactivate();
      return false;
    }
    answer = next;
    renderBanner();
    if (!ticker) {
      challenged = challenge();
      ticker = setInterval(tick, TICK_MS);
      addEventListener("scroll", queueLayout, true);
      addEventListener("resize", queueLayout);
      observer = new MutationObserver(queueLayout);
      observer.observe(document.documentElement, {
        childList: true,
        subtree: true,
        attributes: true,
        characterData: true,
      });
    }
    queueLayout();
    return true;
  }

  function deactivate() {
    answer = null;
    clearTimeout(pollTimer);
    pollTimer = null;
    if (ticker) {
      clearInterval(ticker);
      ticker = null;
      removeEventListener("scroll", queueLayout, true);
      removeEventListener("resize", queueLayout);
      observer.disconnect();
      observer = null;
    }
    if (banner) {
      banner.host.remove();
      banner = null;
    }
    if (overlay) {
      overlay.host.remove();
      overlay = null;
    }
    scrolledTo = null;
  }

  // Whether this page is Cloudflare's interactive check ("Just a moment...",
  // "Verify you are human"). Its widget is in a closed shadow root with random
  // class names, so no guide step could point at it; what can be recognised
  // is the page around it.
  function challenge() {
    if (/^just a moment(\.\.\.|\u2026)?$/i.test(document.title.trim())) {
      return true;
    }
    if (query("input[id^='cf-chl-widget']")) {
      return true;
    }
    for (const node of queryAll("script, iframe")) {
      let verdict = node.localName === "script" ? scripts.get(node) : undefined;
      if (verdict === undefined) {
        const source = node.getAttribute("src");
        verdict = CHALLENGE_SCRIPT.test(source !== null ? source : node.localName === "script" ? node.textContent : "");
        if (node.localName === "script") {
          scripts.set(node, verdict);
        }
      }
      if (verdict) {
        return true;
      }
    }
    return false;
  }

  function tick() {
    challenged = challenge();
    if (location.href !== lastHref) {
      // A single-page application moved on: what to read and what to guide to
      // depend on the URL.
      lastHref = location.href;
      poll();
    }
    queueLayout();
  }

  function queueLayout() {
    if (!layoutQueued && answer) {
      layoutQueued = true;
      requestAnimationFrame(layout);
    }
  }

  // --- The banner -------------------------------------------------------------

  function buildBanner() {
    const shadow = host(
      "partcad-login-banner",
      "position: fixed !important; left: 0 !important; right: 0 !important; bottom: 0 !important; " +
        "top: auto !important; z-index: 2147483647 !important; margin: 0 !important;",
    );
    style(shadow.root, BANNER_CSS);
    const bar = element("div", "bar", shadow.root);
    bar.setAttribute("role", "region");
    bar.setAttribute("aria-label", "PartCAD login");
    // Typing into the banner is not typing into the page: keep the keys away
    // from the page's own shortcuts.
    for (const type of ["keydown", "keyup", "keypress"]) {
      bar.addEventListener(type, (event) => event.stopPropagation());
    }
    const main = element("div", "main", bar);
    const title = element("p", "title", main);
    element("span", "brand", title).textContent = "PartCAD login: ";
    const name = element("span", "name", title);
    const guide = element("p", "guide", main);
    guide.setAttribute("aria-live", "polite");
    const status = element("p", "status", main);
    status.setAttribute("role", "status");
    const captures = element("ul", "captures", main);
    const asks = element("div", "asks", bar);
    const actions = element("div", "actions", bar);
    const done = element("button", "done", actions);
    done.type = "button";
    done.textContent = "Done";
    done.addEventListener("click", () => act({ type: "done", url: location.href }));
    const cancel = element("button", "cancel", actions);
    cancel.type = "button";
    cancel.textContent = "Cancel";
    cancel.addEventListener("click", () => act({ type: "cancel", url: location.href }));
    return {
      host: shadow.node,
      root: shadow.root,
      bar: bar,
      name: name,
      guide: guide,
      status: status,
      captures: captures,
      asks: asks,
      done: done,
      inputs: new Map(),
      chips: new Map(),
      edge: "bottom",
    };
  }

  async function act(message) {
    if (message.type === "done" && banner) {
      banner.done.disabled = true;
    }
    apply(await send(message));
  }

  function askInput(capture) {
    const label = element("label", "ask", banner.asks);
    label.setAttribute("data-name", capture.name);
    element("span", "label", label).textContent = capture.ask.label;
    const input = element("input", null, label);
    input.type = capture.ask.secret ? "password" : "text";
    input.autocomplete = "off";
    input.spellcheck = false;
    input.setAttribute("data-name", capture.name);
    const mark = element("span", "tick", label);
    mark.textContent = "\u2713";
    mark.setAttribute("aria-label", "captured");
    let timer = null;
    const flush = () => {
      clearTimeout(timer);
      timer = null;
      act({ type: "ask", name: capture.name, value: input.value, url: location.href });
    };
    input.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(flush, ASK_DEBOUNCE_MS);
    });
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        flush();
      }
    });
    return { label: label, input: input };
  }

  function renderBanner() {
    if (!banner) {
      banner = buildBanner();
    }
    if (!banner.host.isConnected) {
      document.documentElement.appendChild(banner.host);
    }
    banner.name.textContent = answer.title;
    banner.status.textContent = answer.error || answer.status;
    banner.status.setAttribute("data-kind", answer.error ? "error" : "info");
    for (const capture of answer.captures) {
      let chip = banner.chips.get(capture.name);
      if (!chip) {
        chip = element("li", "capture", banner.captures);
        chip.setAttribute("data-name", capture.name);
        chip.textContent = capture.name;
        banner.chips.set(capture.name, chip);
      }
      chip.setAttribute("data-captured", String(capture.captured));
      if (capture.ask) {
        let ask = banner.inputs.get(capture.name);
        if (!ask) {
          ask = askInput(capture);
          banner.inputs.set(capture.name, ask);
        }
        ask.label.setAttribute("data-captured", String(capture.captured));
        // Something typed that is not of the shape the spec asks for.
        const invalid = !capture.captured && ask.input.value.trim() !== "";
        ask.input.setAttribute("aria-invalid", String(invalid));
        ask.input.title = invalid ? "This does not look like what PartCAD asked for." : "";
        // What was typed on an earlier page is not sent back; say it is there.
        ask.input.placeholder = capture.captured && !ask.input.value ? "captured \u2014 type to replace" : "";
      }
    }
    banner.done.disabled = !answer.complete || answer.sending;
    banner.done.title = answer.complete ? "" : answer.status;
  }

  function placeBanner(spot) {
    // At the bottom of the window, out of the way of the sign-in links most
    // sites put at the top -- unless what the guide points at is under it.
    let edge = "bottom";
    if (spot) {
      const height = banner.bar.getBoundingClientRect().height;
      if (spot.bottom > window.innerHeight - height) {
        edge = "top";
      }
    }
    if (edge !== banner.edge) {
      banner.edge = edge;
      banner.host.setAttribute("data-edge", edge);
      banner.host.style.setProperty("top", edge === "top" ? "0" : "auto", "important");
      banner.host.style.setProperty("bottom", edge === "top" ? "auto" : "0", "important");
    }
  }

  // --- The guide --------------------------------------------------------------

  function visible(node) {
    if (!node || !node.isConnected) {
      return false;
    }
    if (typeof node.checkVisibility === "function" && !node.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) {
      return false;
    }
    const rect = node.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  // The first step, in the spec's order, with a visible element to point at --
  // one its selector matches and, when the step says `contains`, whose text does.
  function currentStep() {
    for (const step of answer.guide) {
      for (const node of queryAll(step.selector)) {
        if (visible(node) && L.textMatches(step.contains, node)) {
          return { node: node, text: step.text };
        }
      }
    }
    return null;
  }

  function buildOverlay() {
    const shadow = host(
      "partcad-login-guide",
      "position: fixed !important; left: 0 !important; top: 0 !important; width: 0 !important; " +
        "height: 0 !important; overflow: visible !important; z-index: 2147483646 !important; " +
        "pointer-events: none !important; margin: 0 !important;",
    );
    style(shadow.root, GUIDE_CSS);
    const spot = element("div", "spot", shadow.root);
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 48 48");
    svg.setAttribute("width", "48");
    svg.setAttribute("height", "48");
    svg.setAttribute("class", "pointer");
    svg.setAttribute("aria-hidden", "true");
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    // An arrow pointing right; it is turned to face the element.
    path.setAttribute("d", "M3 19 H27 V8 L46 24 L27 40 V29 H3 Z");
    path.setAttribute("fill", "#f2b705");
    path.setAttribute("stroke", "#1d2026");
    path.setAttribute("stroke-width", "2");
    path.setAttribute("stroke-linejoin", "round");
    svg.appendChild(path);
    shadow.root.appendChild(svg);
    const label = element("div", "label", shadow.root);
    label.setAttribute("role", "note");
    return { host: shadow.node, root: shadow.root, spot: spot, pointer: svg, label: label, text: null };
  }

  function place(node, left, top) {
    node.style.left = Math.round(left) + "px";
    node.style.top = Math.round(top) + "px";
  }

  function clamp(value, low, high) {
    return Math.max(low, Math.min(value, high));
  }

  function layout() {
    layoutQueued = false;
    if (!answer || !banner) {
      return;
    }
    if (!banner.host.isConnected) {
      document.documentElement.appendChild(banner.host);
    }
    // On a bot check the user's next step is the check, whatever the guide
    // would point at: no spotlight, and the banner says what to do.
    const step = challenged ? null : currentStep();
    banner.guide.textContent = challenged ? CHALLENGE_TEXT : step ? step.text : "";
    if (banner.host.getAttribute("data-challenge") !== String(challenged)) {
      // Only on a change: the page's MutationObserver above sees the host, and
      // an attribute set to the value it has is still a mutation.
      banner.host.setAttribute("data-challenge", String(challenged));
    }
    if (!step) {
      if (overlay) {
        overlay.host.remove();
        overlay = null;
      }
      placeBanner(null);
      return;
    }
    if (!overlay) {
      overlay = buildOverlay();
    }
    if (!overlay.host.isConnected) {
      document.documentElement.appendChild(overlay.host);
    }
    let rect = step.node.getBoundingClientRect();
    const width = window.innerWidth;
    const height = window.innerHeight;
    if ((rect.bottom < 0 || rect.top > height || rect.right < 0 || rect.left > width) && scrolledTo !== step.node) {
      // Once per element: bring it into view, and then leave the scrolling to
      // the user.
      scrolledTo = step.node;
      step.node.scrollIntoView({ block: "center", inline: "nearest" });
      rect = step.node.getBoundingClientRect();
    }
    const pad = 6;
    place(overlay.spot, rect.left - pad, rect.top - pad);
    overlay.spot.style.width = Math.round(rect.width + 2 * pad) + "px";
    overlay.spot.style.height = Math.round(rect.height + 2 * pad) + "px";
    if (overlay.text !== step.text) {
      overlay.text = step.text;
      overlay.label.textContent = step.text;
      overlay.label.style.display = step.text ? "block" : "none";
    }
    const labelWidth = overlay.label.offsetWidth;
    const labelHeight = overlay.label.offsetHeight;
    const size = 48;
    const gap = 6;
    const sideways = size + gap + labelWidth + 2 * gap;
    const middleY = rect.top + rect.height / 2;
    const middleX = rect.left + rect.width / 2;
    let direction;
    let pointerX;
    let pointerY;
    let labelX;
    let labelY;
    if (rect.left - pad >= sideways) {
      direction = "left";
      pointerX = rect.left - pad - gap - size;
      pointerY = middleY - size / 2;
      labelX = pointerX - gap - labelWidth;
      labelY = middleY - labelHeight / 2;
    } else if (width - rect.right - pad >= sideways) {
      direction = "right";
      pointerX = rect.right + pad + gap;
      pointerY = middleY - size / 2;
      labelX = pointerX + size + gap;
      labelY = middleY - labelHeight / 2;
    } else if (height - rect.bottom - pad >= size + labelHeight + 3 * gap) {
      direction = "below";
      pointerX = middleX - size / 2;
      pointerY = rect.bottom + pad + gap;
      labelX = middleX - labelWidth / 2;
      labelY = pointerY + size + gap;
    } else {
      direction = "above";
      pointerX = middleX - size / 2;
      pointerY = rect.top - pad - gap - size;
      labelX = middleX - labelWidth / 2;
      labelY = pointerY - gap - labelHeight;
    }
    const angle = { left: "0deg", right: "180deg", below: "-90deg", above: "90deg" }[direction];
    overlay.pointer.style.setProperty("--angle", angle);
    overlay.pointer.setAttribute("data-direction", direction);
    place(overlay.pointer, pointerX, pointerY);
    place(
      overlay.label,
      clamp(labelX, gap, Math.max(gap, width - labelWidth - gap)),
      clamp(labelY, gap, Math.max(gap, height - labelHeight - gap)),
    );
    placeBanner(rect);
  }

  api.runtime.onMessage.addListener((message) => {
    if (!message || typeof message.type !== "string") {
      return;
    }
    if (message.type === "wake") {
      poll();
    } else if (message.type === "end") {
      deactivate();
    }
  });

  poll();
})();
