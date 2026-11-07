/*
 * PartCAD, 2026
 *
 * Licensed under Apache License, Version 2.0.
 *
 * The script of confirm.html: shows the login request the background is
 * holding, and says yes or no to it. The request is named by the token in
 * this page's URL, so a yes is never given to one the page was not showing.
 *
 * Continue is armed only after the page has been in view for a moment, so
 * that the second click of a double-click on the page that brought this one
 * up, or a click aimed at something else as it appeared, is not a yes. Cancel
 * has the focus, so Enter is a no.
 *
 * Byte-identical in `browsers/chromium` and `browsers/firefox`.
 */
"use strict";

(function () {
  const api = globalThis.browser || globalThis.chrome;
  const token = location.hash.slice(1);
  const ARM_DELAY_MS = 1000;

  const byId = (id) => document.getElementById(id);
  const continueButton = byId("continue");
  const cancelButton = byId("cancel");
  let armTimer = null;
  let answered = false;

  function send(message) {
    return Promise.resolve(api.runtime.sendMessage(message)).catch((error) => ({
      ok: false,
      error: String((error && error.message) || error),
    }));
  }

  function gone(reason) {
    byId("request").hidden = true;
    byId("reason").textContent = reason || "This login request is no longer waiting.";
    byId("gone").hidden = false;
    document.title = "PartCAD login";
  }

  function failed(error) {
    const line = byId("error");
    line.textContent = error || "The extension did not answer.";
    line.hidden = false;
  }

  // Everything shown is set as text: the request is what a page asked for, and
  // none of it is markup.
  function show(request) {
    byId("title").textContent = request.title;
    byId("site").textContent = request.site;
    byId("requester").textContent = request.requester;
    const list = byId("captures");
    for (const capture of request.captures) {
      const item = document.createElement("li");
      const name = document.createElement("code");
      name.textContent = capture.name;
      item.append(name, ": " + capture.from);
      list.append(item);
    }
    document.title = "PartCAD login: " + request.title + "?";
    byId("request").hidden = false;
    cancelButton.focus();
  }

  function arm() {
    clearTimeout(armTimer);
    continueButton.disabled = true;
    if (answered || document.visibilityState !== "visible") {
      return;
    }
    armTimer = setTimeout(() => {
      if (!answered) {
        continueButton.disabled = false;
      }
    }, ARM_DELAY_MS);
  }

  continueButton.addEventListener("click", async () => {
    if (continueButton.disabled || answered) {
      return;
    }
    answered = true;
    continueButton.disabled = true;
    cancelButton.disabled = true;
    const answer = await send({ type: "confirm", token: token });
    // On a yes the background takes this tab to the site; nothing else to do.
    if (!answer || !answer.ok) {
      if (answer && answer.busy) {
        failed(answer.error);
      } else {
        gone(answer && answer.error);
      }
    }
  });

  cancelButton.addEventListener("click", async () => {
    if (answered) {
      return;
    }
    answered = true;
    continueButton.disabled = true;
    cancelButton.disabled = true;
    await send({ type: "decline", token: token });
    // The background closes this tab; if it is the last one, say so here.
    gone("Cancelled: nothing was captured.");
  });

  document.addEventListener("visibilitychange", arm);

  send({ type: "review", token: token }).then((answer) => {
    if (!answer || !answer.ok) {
      gone(answer && answer.error);
      return;
    }
    show(answer.request);
    arm();
  });
})();
