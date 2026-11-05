/*
 * PartCAD, 2026
 *
 * Licensed under Apache License, Version 2.0.
 *
 * What both halves of the PartCAD login extension need to agree on: what a
 * login request ("the spec" `pc login` puts on its start page) may say, and
 * which URLs and origins it names. The background decides with these, and the
 * content script asks the same questions of the page it is in, so a rule kept
 * twice would be a rule the two halves could come to disagree about.
 *
 * Byte-identical in `browsers/chromium` and `browsers/firefox`;
 * `tests/browsers/test_extensions.py` fails when the copies differ. Whatever
 * one browser needs differently belongs in its `manifest.json`.
 */
(function (root) {
  "use strict";

  if (root.PartcadLogin) {
    // Loaded twice into one context: the content script is also injected by
    // the background into a start page that was open before the extension
    // was (see `inject` in background.js).
    return;
  }

  // Where a captured value can come from, in the order the contract lists them.
  const SOURCES = ["cookie", "localStorage", "sessionStorage", "dom", "redirect", "ask"];

  // `pc login` serves its start page on the loopback interface and nowhere
  // else; anything claiming to be a start page on another host is not one.
  const START_HOSTS = ["127.0.0.1", "localhost", "[::1]"];
  const START_PATH = /^\/partcad\/login\/([^/]+)\/start$/;

  const DEFAULT_TIMEOUT = 600;
  const MAX_TIMEOUT = 24 * 3600;

  // A credential is a few kilobytes at most. Anything larger is not one, and it
  // has to fit into the query string of the callback besides.
  const MAX_VALUE_LENGTH = 16384;

  const globs = new Map();

  // URL patterns are globs over the whole URL, and `*` is the only wildcard:
  // `?` is far more often a literal in a URL than a wish to match one character.
  function globRegExp(glob) {
    let compiled = globs.get(glob);
    if (!compiled) {
      const body = glob
        .split("*")
        .map((part) => part.replace(/[\\^$.+?()[\]{}|/]/g, "\\$&"))
        .join(".*");
      compiled = new RegExp("^" + body + "$", "s");
      globs.set(glob, compiled);
    }
    return compiled;
  }

  function globMatch(glob, url) {
    return typeof glob === "string" && typeof url === "string" && globRegExp(glob).test(url);
  }

  function httpUrl(value) {
    if (typeof value !== "string") {
      return null;
    }
    try {
      const url = new URL(value);
      return url.protocol === "http:" || url.protocol === "https:" ? url : null;
    } catch (error) {
      return null;
    }
  }

  function originOf(value) {
    const url = httpUrl(value);
    return url ? url.origin : null;
  }

  // The nonce of a `pc login` start page, or null when `href` is not one.
  function startNonce(href) {
    let url;
    try {
      url = new URL(href);
    } catch (error) {
      return null;
    }
    if (url.protocol !== "http:" || !START_HOSTS.includes(url.hostname)) {
      return null;
    }
    const match = START_PATH.exec(url.pathname);
    return match ? match[1] : null;
  }

  // The part of a URL glob up to the path: the origin it can match, itself a
  // glob. A glob with no "://" in it names no origin of its own.
  function originGlobOf(glob) {
    const scheme = glob.indexOf("://");
    if (scheme < 0) {
      return null;
    }
    const path = glob.indexOf("/", scheme + 3);
    return path < 0 ? glob : glob.slice(0, path);
  }

  function isText(value) {
    return typeof value === "string" && value.length > 0;
  }

  function has(object, key) {
    return Object.prototype.hasOwnProperty.call(object, key);
  }

  function given(object, key) {
    return has(object, key) && object[key] !== undefined && object[key] !== null;
  }

  function fail(error) {
    return { error: error };
  }

  function validateSource(kind, source, name) {
    const where = "capture '" + name + "': ";
    if (!source || typeof source !== "object" || Array.isArray(source)) {
      return fail(where + "'" + kind + "' must be an object");
    }
    switch (kind) {
      case "cookie": {
        const url = httpUrl(source.url);
        if (!url || !isText(source.name)) {
          return fail(where + "a cookie needs 'url' (http or https) and 'name'");
        }
        return { source: { url: url.href, name: source.name } };
      }
      case "localStorage":
      case "sessionStorage": {
        const origin = originOf(source.origin);
        if (!origin || !isText(source.key)) {
          return fail(where + "storage needs 'origin' (http or https) and 'key'");
        }
        return { source: { origin: origin, key: source.key } };
      }
      case "dom": {
        if (!isText(source.url) || !isText(source.selector)) {
          return fail(where + "a DOM value needs 'url' and 'selector'");
        }
        if (given(source, "property") && !isText(source.property)) {
          return fail(where + "'property' must be a name");
        }
        if (given(source, "attribute") && !isText(source.attribute)) {
          return fail(where + "'attribute' must be a name");
        }
        return {
          source: {
            url: source.url,
            selector: source.selector,
            property: given(source, "property") ? source.property : "textContent",
            attribute: given(source, "attribute") ? source.attribute : null,
          },
        };
      }
      case "redirect": {
        if (!isText(source.url) || !isText(source.param)) {
          return fail(where + "a redirect needs 'url' and 'param'");
        }
        return { source: { url: source.url, param: source.param } };
      }
      case "ask": {
        if (given(source, "label") && typeof source.label !== "string") {
          return fail(where + "'label' must be text");
        }
        return { source: { label: isText(source.label) ? source.label : name, secret: source.secret === true } };
      }
      default:
        return fail(where + "unknown source '" + kind + "'");
    }
  }

  // `contains` on a guide step or on `done_when.selector`: a regular
  // expression, case-insensitive, that the element's visible text has to match
  // -- for the button nothing in CSS can pick out but its words.
  function validateContains(holder, where) {
    if (!given(holder, "contains")) {
      return { contains: null };
    }
    if (typeof holder.contains !== "string") {
      return fail(where + ": 'contains' must be a regular expression");
    }
    try {
      new RegExp(holder.contains, "i");
    } catch (error) {
      return fail(where + ": 'contains' is not a valid regular expression: " + error.message);
    }
    return { contains: holder.contains };
  }

  function validateCapture(item) {
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      return fail("every 'capture' entry must be an object");
    }
    if (!isText(item.name)) {
      return fail("every 'capture' entry needs a 'name'");
    }
    const kinds = SOURCES.filter((kind) => given(item, kind));
    if (kinds.length !== 1) {
      return fail("capture '" + item.name + "' must have exactly one of " + SOURCES.join(", "));
    }
    const kind = kinds[0];
    const checked = validateSource(kind, item[kind], item.name);
    if (checked.error) {
      return checked;
    }
    // `match` belongs beside the source; inside it is taken as well, which is
    // how an earlier draft of the contract could be read.
    let match = null;
    const pattern = given(item, "match") ? item.match : given(item[kind], "match") ? item[kind].match : null;
    if (pattern !== null) {
      if (typeof pattern !== "string") {
        return fail("capture '" + item.name + "': 'match' must be a regular expression");
      }
      try {
        new RegExp(pattern);
      } catch (error) {
        return fail("capture '" + item.name + "': 'match' is not a valid regular expression: " + error.message);
      }
      match = pattern;
    }
    const capture = { name: item.name, kind: kind, match: match };
    capture[kind] = checked.source;
    return { capture: capture };
  }

  function validateDoneWhen(raw) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
      return fail("'done_when' must be an object");
    }
    const kinds = ["url", "selector", "fetch"].filter((kind) => given(raw, kind));
    if (kinds.length !== 1) {
      return fail("'done_when' must have exactly one of url, selector, fetch");
    }
    if (kinds[0] === "url") {
      return isText(raw.url) ? { doneWhen: { url: raw.url } } : fail("'done_when.url' must be a URL pattern");
    }
    if (kinds[0] === "selector") {
      if (!isText(raw.selector)) {
        return fail("'done_when.selector' must be a CSS selector");
      }
      const checked = validateContains(raw, "'done_when'");
      return checked.error ? checked : { doneWhen: { selector: raw.selector, contains: checked.contains } };
    }
    const fetch = raw.fetch;
    const url = fetch && typeof fetch === "object" ? httpUrl(fetch.url) : null;
    if (!url) {
      return fail("'done_when.fetch' needs an http or https 'url'");
    }
    let status = 200;
    if (given(fetch, "status")) {
      if (!Number.isInteger(fetch.status) || fetch.status < 100 || fetch.status > 599) {
        return fail("'done_when.fetch.status' must be an HTTP status");
      }
      status = fetch.status;
    }
    return { doneWhen: { fetch: { url: url.href, status: status } } };
  }

  // Checks a spec as `pc login` wrote it and returns {spec} in the shape the
  // rest of the extension relies on, or {error} saying what is wrong with it.
  // Unknown keys are ignored, so that a newer `pc login` can add one.
  function validateSpec(raw, startHref) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
      return fail("the login request is not an object");
    }
    const start = new URL(startHref);
    const url = httpUrl(raw.url);
    if (!url) {
      return fail("'url' must be an http or https URL");
    }
    // The one place a captured value is sent. Pinned to the page that handed
    // the spec over, so that a spec cannot send what it captured anywhere else.
    const callback = httpUrl(raw.callback);
    if (!callback || callback.origin !== start.origin) {
      return fail("'callback' must be on the origin of the page that started the login, " + start.origin);
    }
    if (!callback.pathname.startsWith("/partcad/login/")) {
      return fail("'callback' must be a /partcad/login/ address");
    }
    if (!Array.isArray(raw.capture) || raw.capture.length === 0) {
      return fail("'capture' must list at least one value");
    }
    const names = new Set();
    const capture = [];
    for (const item of raw.capture) {
      const checked = validateCapture(item);
      if (checked.error) {
        return checked;
      }
      if (names.has(checked.capture.name)) {
        return fail("capture '" + checked.capture.name + "' is named twice");
      }
      names.add(checked.capture.name);
      capture.push(checked.capture);
    }
    const require = given(raw, "require") ? raw.require : "all";
    if (require !== "all" && require !== "any") {
      return fail("'require' must be \"all\" or \"any\"");
    }
    let doneWhen = null;
    if (given(raw, "done_when")) {
      const checked = validateDoneWhen(raw.done_when);
      if (checked.error) {
        return checked;
      }
      doneWhen = checked.doneWhen;
    }
    const guide = [];
    if (given(raw, "guide")) {
      if (!Array.isArray(raw.guide)) {
        return fail("'guide' must be a list");
      }
      for (const step of raw.guide) {
        if (!step || typeof step !== "object" || !isText(step.url) || !isText(step.selector)) {
          return fail("every 'guide' step needs 'url' and 'selector'");
        }
        const checked = validateContains(step, "guide step '" + step.selector + "'");
        if (checked.error) {
          return checked;
        }
        guide.push({
          url: step.url,
          selector: step.selector,
          contains: checked.contains,
          text: typeof step.text === "string" ? step.text : "",
        });
      }
    }
    let timeout = DEFAULT_TIMEOUT;
    if (given(raw, "timeout")) {
      if (typeof raw.timeout !== "number" || !(raw.timeout > 0)) {
        return fail("'timeout' must be a number of seconds");
      }
      timeout = Math.min(raw.timeout, MAX_TIMEOUT);
    }
    const title = typeof raw.title === "string" && raw.title.trim() ? raw.title.trim() : url.hostname;
    return {
      spec: {
        url: url.href,
        title: title,
        capture: capture,
        require: require,
        done_when: doneWhen,
        guide: guide,
        timeout: timeout,
        callback: callback.href,
      },
    };
  }

  const named = new WeakMap();

  // Every origin a spec names: exactly, by an http(s) URL or origin, or by the
  // origin part of a URL glob. The extension acts on these pages and no others.
  function namedOrigins(spec) {
    let origins = named.get(spec);
    if (origins) {
      return origins;
    }
    origins = { exact: new Set(), globs: [] };
    const addUrl = (value) => {
      const origin = originOf(value);
      if (origin) {
        origins.exact.add(origin);
      }
    };
    const addGlob = (glob) => {
      const origin = originGlobOf(glob);
      if (origin) {
        origins.globs.push(origin);
      }
    };
    addUrl(spec.url);
    for (const capture of spec.capture) {
      if (capture.cookie) {
        addUrl(capture.cookie.url);
      } else if (capture.localStorage || capture.sessionStorage) {
        origins.exact.add(capture[capture.kind].origin);
      } else if (capture.dom || capture.redirect) {
        addGlob(capture[capture.kind].url);
      }
    }
    for (const step of spec.guide) {
      addGlob(step.url);
    }
    if (spec.done_when && spec.done_when.url) {
      addGlob(spec.done_when.url);
    }
    if (spec.done_when && spec.done_when.fetch) {
      addUrl(spec.done_when.fetch.url);
    }
    named.set(spec, origins);
    return origins;
  }

  function isNamedOrigin(spec, origin) {
    if (!origin) {
      return false;
    }
    const origins = namedOrigins(spec);
    return origins.exact.has(origin) || origins.globs.some((glob) => globMatch(glob, origin));
  }

  // A redirect capture's value: from the query string, or from the fragment,
  // which is where the OAuth implicit flow puts it ("#access_token=...").
  function paramFrom(href, param) {
    let url;
    try {
      url = new URL(href);
    } catch (error) {
      return null;
    }
    const fromQuery = url.searchParams.get(param);
    if (fromQuery !== null) {
      return fromQuery;
    }
    let fragment = url.hash.replace(/^#/, "");
    const query = fragment.indexOf("?");
    if (query >= 0) {
      // "#/callback?access_token=..." -- a single-page application's route.
      fragment = fragment.slice(query + 1);
    }
    return new URLSearchParams(fragment).get(param);
  }

  // Whether a value may be taken for a capture: something there at all, of a
  // credible size, and of the shape `match` asks for. `match` is a JavaScript
  // regular expression tested anywhere in the value; anchor it to mean all of it.
  function accepts(capture, value) {
    if (typeof value !== "string" || value.length === 0 || value.length > MAX_VALUE_LENGTH) {
      return false;
    }
    if (capture.match === null || capture.match === undefined) {
      return true;
    }
    try {
      return new RegExp(capture.match).test(value);
    } catch (error) {
      return false;
    }
  }

  // What `contains` is tested against: the text a user sees on the element,
  // or, for one with none (an input, an icon button), what stands in for it.
  function visibleText(node) {
    const text = typeof node.innerText === "string" ? node.innerText.trim() : "";
    if (text) {
      return text;
    }
    if (typeof node.value === "string" && node.value.trim()) {
      return node.value.trim();
    }
    return (node.getAttribute("aria-label") || node.getAttribute("title") || "").trim();
  }

  function textMatches(contains, node) {
    if (contains === null || contains === undefined) {
      return true;
    }
    try {
      return new RegExp(contains, "i").test(visibleText(node));
    } catch (error) {
      return false;
    }
  }

  function progress(spec, values) {
    const missing = spec.capture.filter((capture) => !has(values, capture.name)).map((capture) => capture.name);
    const captured = spec.capture.length - missing.length;
    return {
      complete: spec.require === "any" ? captured > 0 : missing.length === 0,
      missing: missing,
      captured: captured,
    };
  }

  root.PartcadLogin = Object.freeze({
    SOURCES: SOURCES,
    accepts: accepts,
    globMatch: globMatch,
    has: has,
    isNamedOrigin: isNamedOrigin,
    originOf: originOf,
    paramFrom: paramFrom,
    progress: progress,
    startNonce: startNonce,
    textMatches: textMatches,
    validateSpec: validateSpec,
    visibleText: visibleText,
  });
})(globalThis);
