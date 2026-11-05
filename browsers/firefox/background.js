/*
 * PartCAD, 2026
 *
 * Licensed under Apache License, Version 2.0.
 *
 * The background half of the PartCAD login extension: one login session at a
 * time, started by the page `pc login` serves on the loopback interface, and
 * ended by handing what it captured to that page's callback -- or by Cancel,
 * or by running out of time.
 *
 * Chromium runs this file as the extension's service worker, and stops it
 * whenever it has been idle for a while; Firefox runs it as an event page,
 * which is unloaded the same way. So nothing that has to outlive one event
 * lives only in a variable: the session is kept in `storage.session` -- held
 * in memory, never written to disk, gone when the browser exits -- and read
 * back when the script starts again.
 *
 * Byte-identical in `browsers/chromium` and `browsers/firefox`.
 */
"use strict";

if (typeof importScripts === "function" && typeof globalThis.PartcadLogin === "undefined") {
  // Chromium's service worker. Firefox lists common.js ahead of this file in
  // its manifest instead, and an event page has no importScripts.
  importScripts("common.js");
}

const api = globalThis.browser || globalThis.chrome;
const L = globalThis.PartcadLogin;

const EXPIRY_ALARM = "partcad-login-expiry";

// How often `done_when.fetch` asks the site whether the user is signed in, and
// how long a callback that failed waits before it is sent again on its own.
const FETCH_INTERVAL_MS = 2000;
const RETRY_INTERVAL_MS = 5000;
const NETWORK_TIMEOUT_MS = 15000;
// How long a start page that is still open gets to say that `pc login` behind
// it is still waiting, before its session counts as abandoned.
const PROBE_TIMEOUT_MS = 3000;

let session = null;

// What belongs to the session but must not be persisted with it: a flag left
// set by a worker stopped in the middle of a request would block every request
// after it.
let transient = freshTransient();

function freshTransient() {
  return { sending: false, failedAt: 0, fetching: false, fetchedAt: 0, fetchOk: false, timer: null };
}

const ready = Promise.resolve(api.storage.session.get("session")).then(
  (stored) => {
    session = (stored && stored.session) || null;
    if (session) {
      scheduleExpiry(session);
    }
  },
  () => {
    session = null;
  },
);

// One thing at a time for whatever reads the session, decides and changes it.
// Network requests run outside it (see `checkFetch` and `sendValues`), so a
// slow site never holds up the banner.
let queue = Promise.resolve();

function exclusive(task) {
  const run = queue.then(task, task);
  queue = run.catch(() => {});
  return run;
}

function persist() {
  const request = session ? api.storage.session.set({ session: session }) : api.storage.session.remove("session");
  return Promise.resolve(request).catch(() => {});
}

function fetchWithTimeout(url, init, milliseconds) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), milliseconds);
  return fetch(url, Object.assign({ signal: controller.signal }, init)).finally(() => clearTimeout(timer));
}

function scheduleExpiry(s) {
  // The alarm is what wakes a stopped worker to end the session; the timer is
  // the same thing at a resolution an alarm does not have.
  Promise.resolve(api.alarms.create(EXPIRY_ALARM, { when: s.expiresAt })).catch(() => {});
  clearTimeout(transient.timer);
  transient.timer = setTimeout(() => exclusive(evaluate), Math.max(0, s.expiresAt - Date.now()) + 50);
}

async function broadcast(message) {
  let tabs = [];
  try {
    tabs = await api.tabs.query({});
  } catch (error) {
    return;
  }
  for (const tab of tabs) {
    if (typeof tab.id === "number" && tab.id >= 0) {
      Promise.resolve(api.tabs.sendMessage(tab.id, message)).catch(() => {});
    }
  }
}

async function endSession(reason) {
  if (!session) {
    return;
  }
  session = null;
  clearTimeout(transient.timer);
  transient = freshTransient();
  await persist();
  Promise.resolve(api.alarms.clear(EXPIRY_ALARM)).catch(() => {});
  broadcast({ type: "end", reason: reason });
}

// The window the login ran in: the start tab's, wherever that tab is now.
async function loginWindow(s) {
  try {
    return (await api.tabs.get(s.tabId)).windowId;
  } catch (error) {
    return typeof s.windowId === "number" ? s.windowId : null;
  }
}

async function finish(s, reason) {
  const windowId = await loginWindow(s);
  await endSession(reason);
  if (windowId !== null) {
    Promise.resolve(api.windows.remove(windowId)).catch(() => {});
  }
}

// Whether `pc login` is still waiting behind a start page. Its listener answers
// the start page while the login is open and 404 (or nothing at all) after.
async function listening(startUrl) {
  try {
    const response = await fetchWithTimeout(
      startUrl,
      { cache: "no-store", credentials: "omit", redirect: "error" },
      PROBE_TIMEOUT_MS,
    );
    return response.ok;
  } catch (error) {
    return false;
  }
}

function take(s, capture, value) {
  if (!L.accepts(capture, value) || s.values[capture.name] === value) {
    return false;
  }
  s.values[capture.name] = value;
  return true;
}

// Redirect captures: any tab, at any URL the capture's glob matches. The URL
// is all that is needed, so a redirect to a port nothing listens on -- the
// usual OAuth "redirect_uri" for a desktop application -- is as good as any.
function noticeUrl(s, url) {
  let changed = false;
  for (const capture of s.spec.capture) {
    if (capture.redirect && L.globMatch(capture.redirect.url, url)) {
      changed = take(s, capture, L.paramFrom(url, capture.redirect.param)) || changed;
    }
  }
  return changed;
}

// Cookies are read fresh every time rather than remembered: a cookie that went
// away was a session that ended, and its value no longer signs anybody in.
async function readCookies(s) {
  let changed = false;
  for (const capture of s.spec.capture) {
    if (!capture.cookie) {
      continue;
    }
    let cookie = null;
    try {
      cookie = await api.cookies.get({ url: capture.cookie.url, name: capture.cookie.name });
    } catch (error) {
      cookie = null;
    }
    if (cookie && L.accepts(capture, cookie.value)) {
      changed = take(s, capture, cookie.value) || changed;
    } else if (L.has(s.values, capture.name)) {
      delete s.values[capture.name];
      changed = true;
    }
  }
  return changed;
}

function checkFetch(s) {
  const t = transient;
  if (t.fetching || Date.now() - t.fetchedAt < FETCH_INTERVAL_MS) {
    return;
  }
  t.fetching = true;
  const check = s.spec.done_when.fetch;
  // The browser's own cookies -- the user's session on the site -- and the
  // status the site answers itself: following a redirect would read a login
  // page's 200 as "signed in".
  fetchWithTimeout(check.url, { credentials: "include", cache: "no-store", redirect: "manual" }, NETWORK_TIMEOUT_MS)
    .then(
      (response) => response.status === check.status,
      () => false,
    )
    .then((ok) => {
      t.fetching = false;
      t.fetchedAt = Date.now();
      t.fetchOk = ok;
      if (ok && session === s) {
        exclusive(evaluate);
      }
    });
}

function doneWhenHolds(s, tabs) {
  const when = s.spec.done_when;
  if (when.url) {
    return tabs.some((tab) => L.globMatch(when.url, tab.url || ""));
  }
  if (when.selector) {
    return s.doneSelectorSeen === true;
  }
  checkFetch(s);
  return transient.fetchOk;
}

async function sendValues(s) {
  const t = transient;
  t.sending = true;
  const url = new URL(s.spec.callback);
  for (const capture of s.spec.capture) {
    if (L.has(s.values, capture.name)) {
      url.searchParams.set(capture.name, s.values[capture.name]);
    }
  }
  let status = 0;
  let reason = "";
  try {
    // `redirect: "error"`: the values go to the callback and nowhere it might
    // forward them.
    const response = await fetchWithTimeout(
      url.href,
      { headers: { Accept: "application/json" }, cache: "no-store", credentials: "omit", redirect: "error" },
      NETWORK_TIMEOUT_MS,
    );
    status = response.status;
  } catch (error) {
    reason = String((error && error.message) || error);
  }
  t.sending = false;
  if (session !== s) {
    return;
  }
  if (status === 200) {
    await finish(s, "sent");
    return;
  }
  t.failedAt = Date.now();
  s.error = status ? "PartCAD did not take the login (HTTP " + status + ")." : "PartCAD is not answering: " + reason;
  persist();
}

// Brings the session up to date with the browser and sends it once it is
// complete. Called for every event that could change the answer.
async function evaluate() {
  const s = session;
  if (!s) {
    return;
  }
  if (Date.now() >= s.expiresAt) {
    await endSession("expired");
    return;
  }
  let changed = await readCookies(s);
  if (session !== s) {
    return;
  }
  let tabs = [];
  try {
    tabs = await api.tabs.query({});
  } catch (error) {
    tabs = [];
  }
  if (session !== s) {
    return;
  }
  for (const tab of tabs) {
    if (tab.url) {
      changed = noticeUrl(s, tab.url) || changed;
    }
  }
  if (changed) {
    s.error = null;
    persist();
  }
  if (transient.sending || !L.progress(s.spec, s.values).complete) {
    return;
  }
  if (s.spec.done_when ? !doneWhenHolds(s, tabs) : !s.doneRequested) {
    return;
  }
  if (Date.now() - transient.failedAt < RETRY_INTERVAL_MS) {
    return;
  }
  sendValues(s);
}

// The origin of the page a message came from, if it came from a top-level page
// of a tab -- which is the only place the content script does anything.
function senderOrigin(sender) {
  if (!sender.tab || sender.frameId !== 0) {
    return null;
  }
  return L.originOf(sender.url);
}

function statusText(s, progress) {
  if (transient.sending) {
    return "Handing the login to PartCAD\u2026";
  }
  if (!progress.complete) {
    return (s.spec.require === "any" ? "Waiting for any of: " : "Waiting for: ") + progress.missing.join(", ");
  }
  if (s.spec.done_when) {
    return "Waiting for the site to confirm that you are logged in\u2026";
  }
  return "PartCAD has what it needs. Press Done once you are logged in.";
}

// What a page of the login is told: what to show, and what to read for it.
// Never a captured value -- only which ones are captured.
function describe(s, origin, pageUrl) {
  const progress = L.progress(s.spec, s.values);
  return {
    active: true,
    title: s.spec.title,
    captures: s.spec.capture.map((capture) => ({
      name: capture.name,
      kind: capture.kind,
      captured: L.has(s.values, capture.name),
      ask: capture.ask ? { label: capture.ask.label, secret: capture.ask.secret } : null,
    })),
    storage: s.spec.capture
      .filter((capture) => (capture.localStorage || capture.sessionStorage) && capture[capture.kind].origin === origin)
      .map((capture) => ({ name: capture.name, area: capture.kind, key: capture[capture.kind].key })),
    dom: s.spec.capture
      .filter((capture) => capture.dom && L.globMatch(capture.dom.url, pageUrl))
      .map((capture) => ({
        name: capture.name,
        selector: capture.dom.selector,
        property: capture.dom.property,
        attribute: capture.dom.attribute,
      })),
    guide: s.spec.guide
      .filter((step) => L.globMatch(step.url, pageUrl))
      .map((step) => ({ selector: step.selector, contains: step.contains, text: step.text })),
    doneSelector:
      s.spec.done_when && s.spec.done_when.selector
        ? { selector: s.spec.done_when.selector, contains: s.spec.done_when.contains }
        : null,
    complete: progress.complete,
    sending: transient.sending,
    status: statusText(s, progress),
    error: s.error || null,
  };
}

async function onStart(message, sender) {
  const startUrl = String(sender.url || "").split("#")[0];
  if (!sender.tab || sender.frameId !== 0 || !L.startNonce(startUrl)) {
    return { ok: false, error: "This is not a PartCAD login page." };
  }
  const checked = L.validateSpec(message.spec, startUrl);
  if (checked.error) {
    return { ok: false, error: "PartCAD asked for something the extension cannot do: " + checked.error + "." };
  }
  const spec = checked.spec;
  if (session && session.startUrl === startUrl) {
    // The start page again -- reloaded, or gone back to. Same login, so it
    // carries on where it was.
    session.tabId = sender.tab.id;
    session.windowId = sender.tab.windowId;
    persist();
    await api.tabs.update(sender.tab.id, { url: session.spec.url });
    return { ok: true, title: session.spec.title };
  }
  if (session) {
    // One login at a time. The one in progress keeps the browser unless
    // `pc login` behind it has stopped waiting -- then it is abandoned, and
    // keeping it until it times out would only make the user wait.
    if (Date.now() < session.expiresAt && (await listening(session.startUrl))) {
      return {
        ok: false,
        busy: true,
        error:
          "Another PartCAD login is in progress in this browser (" +
          session.spec.title +
          "). Finish or cancel that one, then reload this page.",
      };
    }
    await endSession("abandoned");
  }
  const now = Date.now();
  session = {
    startUrl: startUrl,
    origin: L.originOf(startUrl),
    spec: spec,
    tabId: sender.tab.id,
    windowId: sender.tab.windowId,
    startedAt: now,
    expiresAt: now + spec.timeout * 1000,
    values: {},
    doneRequested: false,
    doneSelectorSeen: false,
    error: null,
  };
  transient = freshTransient();
  await persist();
  scheduleExpiry(session);
  try {
    await api.tabs.update(sender.tab.id, { url: spec.url });
  } catch (error) {
    await endSession("failed");
    return { ok: false, error: "The browser would not open " + spec.url + ": " + error.message };
  }
  broadcast({ type: "wake" });
  return { ok: true, title: spec.title };
}

async function onPoll(message, sender) {
  const s = session;
  const origin = senderOrigin(sender);
  if (!s || !origin || !L.isNamedOrigin(s.spec, origin)) {
    return { active: false };
  }
  // The content script says which URL it is at, because a single-page
  // application moves without the browser noticing. Believed only within the
  // origin the browser says the message came from.
  const pageUrl = L.originOf(message.url) === origin ? message.url : sender.url;
  const report = message.report;
  if (report && typeof report === "object") {
    let changed = false;
    for (const capture of s.spec.capture) {
      if ((capture.localStorage || capture.sessionStorage) && capture[capture.kind].origin === origin) {
        changed = take(s, capture, report.storage && report.storage[capture.name]) || changed;
      } else if (capture.dom && L.globMatch(capture.dom.url, pageUrl)) {
        changed = take(s, capture, report.dom && report.dom[capture.name]) || changed;
      }
    }
    if (s.spec.done_when && s.spec.done_when.selector && report.doneSelector === true && !s.doneSelectorSeen) {
      s.doneSelectorSeen = true;
      changed = true;
    }
    if (changed) {
      s.error = null;
      persist();
    }
  }
  await exclusive(evaluate);
  return session === s ? describe(s, origin, pageUrl) : { active: false };
}

async function onAsk(message, sender) {
  const s = session;
  const origin = senderOrigin(sender);
  if (!s || !origin || !L.isNamedOrigin(s.spec, origin)) {
    return { active: false };
  }
  const capture = s.spec.capture.find((item) => item.name === message.name && item.ask);
  if (capture) {
    const value = typeof message.value === "string" ? message.value.trim() : "";
    if (L.accepts(capture, value)) {
      s.values[capture.name] = value;
    } else {
      delete s.values[capture.name];
    }
    s.error = null;
    persist();
    await exclusive(evaluate);
  }
  return session === s ? describe(s, origin, message.url || sender.url) : { active: false };
}

async function onDone(message, sender) {
  const s = session;
  const origin = senderOrigin(sender);
  if (!s || !origin || !L.isNamedOrigin(s.spec, origin)) {
    return { active: false };
  }
  if (L.progress(s.spec, s.values).complete) {
    s.doneRequested = true;
    s.error = null;
    // A press of Done is also "try again now", and "ask the site again now".
    transient.failedAt = 0;
    transient.fetchedAt = 0;
    persist();
    await exclusive(evaluate);
  }
  return session === s ? describe(s, origin, message.url || sender.url) : { active: false };
}

async function onCancel(message, sender) {
  const s = session;
  const origin = senderOrigin(sender);
  if (!s || !origin || !L.isNamedOrigin(s.spec, origin)) {
    return { active: false };
  }
  try {
    await fetchWithTimeout(
      new URL("cancel", s.startUrl).href,
      { cache: "no-store", credentials: "omit", redirect: "error" },
      NETWORK_TIMEOUT_MS,
    );
  } catch (error) {
    // Nothing is waiting any more; the login is over all the same.
  }
  if (session === s) {
    await finish(s, "cancelled");
  }
  return { active: false };
}

const HANDLERS = { start: onStart, poll: onPoll, ask: onAsk, done: onDone, cancel: onCancel };

api.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // Only this extension's own content scripts: a web page cannot message an
  // extension that declares no "externally_connectable", and another extension
  // would arrive through onMessageExternal, which is not listened to.
  if (sender.id !== api.runtime.id || !message || !L.has(HANDLERS, message.type)) {
    return false;
  }
  ready
    .then(() => HANDLERS[message.type](message, sender))
    .then(sendResponse, (error) => sendResponse({ ok: false, active: false, error: String(error) }));
  return true;
});

// Everything below can change what has been captured, so it re-evaluates --
// and does nothing at all while no login is in progress.
function onUrl(url) {
  ready.then(() => {
    const s = session;
    if (!s || typeof url !== "string") {
      return;
    }
    if (noticeUrl(s, url)) {
      s.error = null;
      persist();
    }
    exclusive(evaluate);
  });
}

api.cookies.onChanged.addListener((change) => {
  ready.then(() => {
    const s = session;
    if (s && s.spec.capture.some((capture) => capture.cookie && capture.cookie.name === change.cookie.name)) {
      exclusive(evaluate);
    }
  });
});

for (const event of [
  api.webNavigation.onBeforeNavigate,
  api.webNavigation.onCommitted,
  api.webNavigation.onErrorOccurred,
  api.webNavigation.onReferenceFragmentUpdated,
  api.webNavigation.onHistoryStateUpdated,
]) {
  event.addListener((details) => {
    if (details.frameId === 0) {
      onUrl(details.url);
    }
  });
}

// A start page can finish loading before the extension's content script is in
// place -- the browser starts the extension and opens `pc login`'s page at the
// same moment. Injected again here, the content script runs once all the same.
function inject(tabId) {
  Promise.resolve(api.scripting.executeScript({ target: { tabId: tabId }, files: ["common.js", "content.js"] })).catch(
    () => {},
  );
}

api.tabs.onUpdated.addListener((tabId, change, tab) => {
  if (change.url) {
    onUrl(change.url);
  }
  if (change.status === "complete" && tab && L.startNonce(tab.url || "")) {
    inject(tabId);
  }
});

api.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === EXPIRY_ALARM) {
    ready.then(() => exclusive(evaluate));
  }
});

ready.then(async () => {
  let tabs = [];
  try {
    tabs = await api.tabs.query({});
  } catch (error) {
    return;
  }
  for (const tab of tabs) {
    if (tab.status === "complete" && L.startNonce(tab.url || "")) {
      inject(tab.id);
    }
  }
});
