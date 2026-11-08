//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// Where the user is: the question this extension asks the first time it runs,
// and the form that answers it.
//
// PartCAD needs to know where somebody is for two things only -- ordering the
// manufacturing of parts and assemblies, and handling such orders oneself:
// prices in their currency, a delivery address, the shop nearest to them. For
// somebody who only designs, none of it is needed, and the dialog says so and
// makes leaving it blank the easy answer.
//
// None of it is kept here. The answers are the user's configuration, in
// `~/.partcad/config.yaml`, and they are read and written by running
// `pc system locale` -- the command line is the one implementation of that
// file, and of asking this machine's location service, which is three
// different things on three systems (`partcad_client.location`). Never over the
// daemon connection: a daemon can be on another machine, which is neither where
// the user is nor where their file is.
//
// "The first time" is per user, not per editor: the question is asked while
// the file has no `manufacturingOrders`, so the PartCAD IDE and a VS Code with
// this extension on the same machine ask it once between them.
//

import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as vscode from 'vscode';

import { runCli } from './common/backend';
import { traceError, traceInfo } from './common/log/logging';
import { NO_PROMPTS_ENV } from './common/provision';
import { toolsDirectory } from './common/terminalPath';

/** The command that opens the form, from the command palette and the PartCAD view. */
export const CONFIGURE_COMMAND = 'partcad.configureLocale';

// This installation was asked and closed the dialog without answering. Not an
// answer to write into the user's file -- they did not give one -- but not a
// reason to ask again on every start either: the command is there for later.
const DISMISSED_KEY = 'partcad.locale.dismissed';

// When the location was last asked of this machine, so that it is asked once a
// day at most -- and only while `locationAccess` is on.
const REFRESHED_KEY = 'partcad.locale.refreshed';
const REFRESH_INTERVAL_MS = 24 * 60 * 60 * 1000;

// How long the location service is given, in seconds. The first answer can
// include the system asking the user for permission.
const LOCATE_TIMEOUT_SECONDS = 30;

/** A place on Earth, in degrees. */
export interface Coordinates {
    latitude: number;
    longitude: number;
}

/** What `pc system locale show --json` answers. */
export interface LocaleState {
    configFile: string;
    asked: boolean;
    manufacturingOrders: string[] | null;
    locationAccess: boolean;
    configured: {
        country: string | null;
        language: string | null;
        currency: string | null;
        location: Coordinates | null;
        address: Record<string, string>;
    };
    resolved: {
        country: string | null;
        language: string | null;
        currency: string | null;
        location: Coordinates | null;
    };
    detected: { country: string | null; language: string | null; currency: string | null };
    locationService: string | null;
    settings: boolean;
}

/** What the form hands back. Every field is sent: an empty one is "leave it blank". */
export interface LocaleAnswers {
    orders: string[];
    country: string;
    language: string;
    currency: string;
    location: string;
    locationAccess: boolean;
    address: {
        line1: string;
        line2: string;
        city: string;
        stateCode: string;
        zipCode: string;
        countryCode: string;
    };
}

/** The two things where the user is matters for, as `manufacturingOrders` spells them. */
export const ORDERS = ['place', 'handle'];

/**
 * The state `show --json` printed, or undefined for anything else.
 *
 * A `pc` from before `pc system locale` prints its usage error and nothing on
 * stdout: that is not a user who has not been asked, it is a PartCAD that
 * cannot ask, and nothing is shown.
 */
export function parseState(stdout: string): LocaleState | undefined {
    let parsed: any;
    try {
        parsed = JSON.parse(stdout);
    } catch {
        return undefined;
    }
    if (!parsed || typeof parsed !== 'object' || typeof parsed.asked !== 'boolean' || !parsed.configured) {
        return undefined;
    }
    return parsed as LocaleState;
}

/** Whether this window asks the first-run question. */
export function shouldAsk(state: LocaleState | undefined, dismissed: boolean, noPrompts: boolean): boolean {
    return !noPrompts && !dismissed && state !== undefined && !state.asked;
}

/** Whether the location is due to be asked of this machine again. */
export function refreshDue(state: LocaleState | undefined, lastRefresh: number | undefined, now: number): boolean {
    if (!state || !state.locationAccess || !state.locationService) {
        return false;
    }
    return lastRefresh === undefined || now - lastRefresh >= REFRESH_INTERVAL_MS;
}

/** `pc` arguments for "used for neither": the answer, and nothing else written. */
export function leaveBlankArguments(): string[] {
    return ['system', 'locale', 'set', '--manufacturing-orders', 'none', '--json'];
}

/** `pc` arguments that write everything the form says, a blank field as a removal. */
export function setArguments(answers: LocaleAnswers): string[] {
    const orders = ORDERS.filter((order) => answers.orders.includes(order));
    const address = answers.address;
    return [
        'system',
        'locale',
        'set',
        '--manufacturing-orders',
        orders.length ? orders.join(',') : 'none',
        '--country',
        answers.country.trim(),
        '--language',
        answers.language.trim(),
        '--currency',
        answers.currency.trim(),
        '--location',
        answers.location.trim(),
        answers.locationAccess ? '--location-access' : '--no-location-access',
        '--line1',
        address.line1.trim(),
        '--line2',
        address.line2.trim(),
        '--city',
        address.city.trim(),
        '--state-code',
        address.stateCode.trim(),
        '--zip-code',
        address.zipCode.trim(),
        '--address-country',
        address.countryCode.trim(),
        '--json',
    ];
}

/** What the first-run dialog's buttons answer. */
const ORDER_BUTTON = 'Order Manufacturing';
const HANDLE_BUTTON = 'Handle Orders Myself';
const BLANK_BUTTON = 'Leave Blank';

export class LocaleSetup implements vscode.Disposable {
    private panel: vscode.WebviewPanel | undefined;
    // Whether the form open now has been saved.
    private saved = false;
    private readonly disposables: vscode.Disposable[] = [];

    constructor(
        private readonly context: vscode.ExtensionContext,
        private readonly serverId: string,
        private readonly outputChannel: vscode.LogOutputChannel,
    ) {
        this.disposables.push(vscode.commands.registerCommand(CONFIGURE_COMMAND, () => this.openForm()));
    }

    dispose(): void {
        this.panel?.dispose();
        this.disposables.forEach((d) => d.dispose());
    }

    /** `pc` as installed beside the service this window runs, or undefined before there is one. */
    private cli(): string | undefined {
        const directory = toolsDirectory(this.context, this.serverId);
        if (!directory) {
            return undefined;
        }
        const candidate = path.join(directory, process.platform === 'win32' ? 'pc.exe' : 'pc');
        return fs.existsSync(candidate) ? candidate : undefined;
    }

    /**
     * Run `pc system locale ...`, and parse its JSON.
     *
     * In the home directory rather than the workspace: nothing here is about a
     * package, and `pc` has no reason to look at one.
     */
    private async pc(args: string[], allowFailure = false): Promise<any> {
        const cli = this.cli();
        if (!cli) {
            throw new Error('PartCAD is not installed yet.');
        }
        const stdout = await runCli(cli, args, os.homedir(), this.outputChannel, undefined, { allowFailure });
        try {
            return JSON.parse(stdout);
        } catch {
            throw new Error('This PartCAD cannot ask where you are; update PartCAD and try again.');
        }
    }

    private async state(): Promise<LocaleState | undefined> {
        try {
            return parseState(JSON.stringify(await this.pc(['system', 'locale', 'show', '--json'])));
        } catch (e) {
            traceInfo(`PartCAD: not asking where you are (${e})`);
            return undefined;
        }
    }

    /**
     * What a window does once its backend has started: ask the question if it
     * has never been answered, and otherwise keep the location up to date when
     * the user allowed that.
     *
     * After the backend rather than at activation, because `pc` is what answers
     * and on a new machine there is none until the backend has been
     * downloaded -- whose own dialog comes first, rather than on top of this one.
     */
    async afterStart(): Promise<void> {
        if (process.env[NO_PROMPTS_ENV] === '1') {
            return;
        }
        const state = await this.state();
        if (refreshDue(state, this.context.globalState.get<number>(REFRESHED_KEY), Date.now())) {
            void this.refreshLocation();
        }
        if (!shouldAsk(state, this.context.globalState.get<boolean>(DISMISSED_KEY, false), false)) {
            return;
        }
        await this.ask();
    }

    /** The first-run question: a modal, because it is one question with three answers. */
    private async ask(): Promise<void> {
        const choice = await vscode.window.showInformationMessage(
            'Will you use PartCAD to order the manufacturing of parts and assemblies, or to handle manufacturing orders yourself?',
            {
                modal: true,
                detail:
                    'If so, PartCAD can use your country, language, currency, address and location: prices in ' +
                    'your currency, deliveries to your address, and the shops nearest to you. They are kept in ' +
                    '~/.partcad/config.yaml on this computer.\n\n' +
                    'If you only design, leave them blank and location access off -- nothing else in PartCAD ' +
                    'needs them. "PartCAD: Region, Address and Location" changes this later.',
            },
            ORDER_BUTTON,
            HANDLE_BUTTON,
            BLANK_BUTTON,
        );
        if (choice === undefined) {
            await this.context.globalState.update(DISMISSED_KEY, true);
            return;
        }
        if (choice === BLANK_BUTTON) {
            try {
                await this.pc(leaveBlankArguments());
            } catch (e: any) {
                traceError(`PartCAD: could not record the answer: ${e?.message ?? e}`);
            }
            return;
        }
        await this.openForm(choice === ORDER_BUTTON ? ['place'] : ['handle']);
    }

    /** Ask the location service, and save what it says when it has moved. */
    private async refreshLocation(): Promise<void> {
        await this.context.globalState.update(REFRESHED_KEY, Date.now());
        try {
            const answer = await this.pc(
                ['system', 'locale', 'locate', '--save', '--json', '--timeout', String(LOCATE_TIMEOUT_SECONDS)],
                true,
            );
            traceInfo(
                answer?.found
                    ? `PartCAD: location ${answer.saved ? 'updated' : 'unchanged'} (${answer.method})`
                    : `PartCAD: the location service did not answer: ${answer?.message ?? answer?.reason}`,
            );
        } catch (e) {
            traceInfo(`PartCAD: could not ask the location service: ${e}`);
        }
    }

    /** The form, with `orders` ticked when the dialog was answered with one of them. */
    async openForm(orders?: string[]): Promise<void> {
        if (!this.cli()) {
            vscode.window.showErrorMessage(
                'PartCAD is not installed yet. Open a PartCAD package first, and the extension will install it.',
            );
            return;
        }
        if (this.panel) {
            this.panel.reveal();
            return;
        }
        const panel = vscode.window.createWebviewPanel(
            'partcadLocale',
            'PartCAD: Region, Address and Location',
            vscode.ViewColumn.Active,
            { enableScripts: true, retainContextWhenHidden: true },
        );
        this.panel = panel;
        panel.iconPath = vscode.Uri.joinPath(this.context.extensionUri, 'resources', 'logo.svg');
        panel.onDidDispose(
            async () => {
                this.panel = undefined;
                // Opened by the first-run question and closed unsaved: the
                // user saw the question and walked away from it, which is not
                // an answer to write, and not a reason to ask on every start.
                if (orders && !this.saved) {
                    await this.context.globalState.update(DISMISSED_KEY, true);
                }
            },
            undefined,
            this.disposables,
        );
        this.saved = false;
        panel.webview.onDidReceiveMessage(
            (message) => this.handle(panel, message, orders),
            undefined,
            this.disposables,
        );
        panel.webview.html = formHtml();
    }

    private async handle(panel: vscode.WebviewPanel, message: any, orders: string[] | undefined): Promise<void> {
        const post = (reply: any) => void panel.webview.postMessage(reply);
        try {
            switch (message?.type) {
                case 'ready': {
                    const state = await this.state();
                    if (!state) {
                        post({ type: 'error', message: 'This PartCAD cannot ask where you are; update PartCAD.' });
                        return;
                    }
                    post({ type: 'state', state, orders: state.asked ? undefined : orders });
                    return;
                }
                case 'save': {
                    const state = parseState(JSON.stringify(await this.pc(setArguments(message.answers))));
                    this.saved = true;
                    post({ type: 'saved', state });
                    vscode.window.showInformationMessage(`Saved to ${state?.configFile ?? '~/.partcad/config.yaml'}.`);
                    panel.dispose();
                    return;
                }
                case 'locate': {
                    const answer = await this.pc(
                        ['system', 'locale', 'locate', '--json', '--timeout', String(LOCATE_TIMEOUT_SECONDS)],
                        true,
                    );
                    post({ type: 'located', answer });
                    return;
                }
                case 'settings': {
                    const answer = await this.pc(['system', 'locale', 'settings', '--json'], true);
                    post({ type: 'settingsOpened', answer });
                    return;
                }
            }
        } catch (e: any) {
            // Whatever `pc` said: a value it refused names the value.
            post({ type: 'error', message: `${e?.message ?? e}`.replace(/^pc [^:]*failed: /, '') });
        }
    }
}

function nonce(): string {
    const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    let text = '';
    for (let i = 0; i < 32; i++) {
        text += possible.charAt(Math.floor(Math.random() * possible.length));
    }
    return text;
}

/**
 * The form. Plain HTML and one script, inline, under a nonce: there is nothing
 * here worth a bundle of its own.
 *
 * The lists of countries, languages and currencies are not shipped: the
 * webview's own `Intl` knows every code and its name in the user's language,
 * which is both shorter and better than a table that would go stale.
 */
export function formHtml(): string {
    const scriptNonce = nonce();
    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${scriptNonce}'; script-src 'nonce-${scriptNonce}';">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Region, Address and Location</title>
<style nonce="${scriptNonce}">
  body { font-family: var(--vscode-font-family); font-size: var(--vscode-font-size); color: var(--vscode-foreground);
         max-width: 46rem; padding: 0 1.25rem 2rem; line-height: 1.45; }
  h1 { font-size: 1.5em; font-weight: 600; margin-bottom: .25rem; }
  h2 { font-size: 1.05em; font-weight: 600; margin: 1.5rem 0 .5rem; }
  p { margin: .4rem 0; }
  .lead, .hint, .footnote { color: var(--vscode-descriptionForeground); }
  fieldset { border: 1px solid var(--vscode-widget-border, var(--vscode-panel-border)); border-radius: 4px;
             padding: .5rem .9rem .8rem; margin: 1rem 0; }
  legend { font-weight: 600; padding: 0 .3rem; }
  label.check { display: flex; gap: .5rem; align-items: flex-start; margin: .35rem 0; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr)); gap: .6rem .9rem; }
  .grid label { display: flex; flex-direction: column; gap: .2rem; font-size: .92em; }
  .wide { grid-column: 1 / -1; }
  input[type=text], select { font: inherit; color: var(--vscode-input-foreground); background: var(--vscode-input-background);
         border: 1px solid var(--vscode-input-border, transparent); border-radius: 2px; padding: .3rem .4rem; }
  input[type=text]:focus, select:focus { outline: 1px solid var(--vscode-focusBorder); }
  button { font: inherit; border: none; border-radius: 2px; padding: .4rem .9rem; cursor: pointer;
           color: var(--vscode-button-foreground); background: var(--vscode-button-background); }
  button:hover { background: var(--vscode-button-hoverBackground); }
  button.secondary { color: var(--vscode-button-secondaryForeground); background: var(--vscode-button-secondaryBackground); }
  button.secondary:hover { background: var(--vscode-button-secondaryHoverBackground); }
  button:disabled { opacity: .5; cursor: default; }
  .row { display: flex; gap: .5rem; flex-wrap: wrap; align-items: center; margin-top: .5rem; }
  .muted { opacity: .55; }
  .status { min-height: 1.3em; }
  .error { color: var(--vscode-errorForeground); }
  code { font-family: var(--vscode-editor-font-family); }
</style>
</head>
<body>
<h1>Where you are</h1>
<p class="lead">PartCAD needs to know where you are for two things only: ordering the manufacturing of parts and
assemblies, and handling manufacturing orders yourself. Then it can quote in your currency, ship to your address and
find the shops nearest to you.</p>

<fieldset>
  <legend>What will you use PartCAD for?</legend>
  <label class="check"><input type="checkbox" id="place"> Ordering the manufacturing of parts and assemblies</label>
  <label class="check"><input type="checkbox" id="handle"> Handling manufacturing orders myself</label>
  <p class="hint" id="designOnly">Neither? If you only design, leave everything below blank and location access off:
  nothing else in PartCAD needs it.</p>
</fieldset>

<div id="details">
  <h2>Region</h2>
  <p class="hint">Left blank, PartCAD works them out from this computer's language and region settings.</p>
  <div class="grid">
    <label>Country <select id="country"></select></label>
    <label>Language <select id="language"></select></label>
    <label>Currency <select id="currency"></select></label>
  </div>

  <h2>Address</h2>
  <p class="hint">Where a manufacturer ships to and quotes for. Only a manufacturer you ask is given it.</p>
  <div class="grid">
    <label class="wide">Address line 1 <input type="text" id="line1" autocomplete="address-line1"></label>
    <label class="wide">Address line 2 <input type="text" id="line2" autocomplete="address-line2"></label>
    <label>City <input type="text" id="city" autocomplete="address-level2"></label>
    <label>State, province or region code <input type="text" id="stateCode" autocomplete="address-level1"></label>
    <label>ZIP or postal code <input type="text" id="zipCode" autocomplete="postal-code"></label>
    <label>Country <select id="countryCode"></select></label>
  </div>

  <h2>Location</h2>
  <p class="hint">Used to find the shop nearest to you, and never handed to anyone: PartCAD picks the shop itself.
  About a kilometre is enough.</p>
  <div class="grid">
    <label class="wide">Latitude, longitude <input type="text" id="location" placeholder="52.37, 4.89"></label>
  </div>
  <div class="row">
    <button class="secondary" id="locate">Use this computer's location</button>
    <button class="secondary" id="settings">Location settings</button>
  </div>
  <p class="status" id="locateStatus"></p>
  <label class="check"><input type="checkbox" id="locationAccess">
    <span>Let PartCAD ask this computer's location service <span id="service"></span>, and keep the location up to
    date when PartCAD starts. The system asks for its own permission the first time.</span></label>
</div>

<div class="row">
  <button id="save">Save</button>
  <button class="secondary" id="clear">Clear all</button>
</div>
<p class="status" id="status"></p>
<p class="footnote">Saved in <code id="file">~/.partcad/config.yaml</code>, on this computer. Stores are told your
country, state, city, language and currency; only a manufacturer is given your address.</p>

<script nonce="${scriptNonce}">
(function () {
  const vscode = acquireVsCodeApi();
  const $ = (id) => document.getElementById(id);
  const SERVICES = { windows: '(Windows location)', corelocation: '(Core Location)', geoclue: '(GeoClue)' };
  // Named, and not countries: unions, the unknown region, and codes ISO 3166
  // reserves for places it does not list as countries.
  const NOT_COUNTRIES = new Set(['EU', 'EZ', 'UN', 'QO', 'XA', 'XB', 'ZZ', 'AC', 'CP', 'CQ', 'DG', 'EA', 'IC', 'TA']);
  const letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';

  function names(type) {
    try { return new Intl.DisplayNames([navigator.language || 'en'], { type: type, fallback: 'none' }); }
    catch (e) { return { of: () => undefined }; }
  }
  const regionNames = names('region');
  const languageNames = names('language');
  const currencyNames = names('currency');

  // Every two-letter code the webview has a name for: ISO 3166-1 regions in
  // upper case, ISO 639-1 languages in lower case.
  function codes(upper, lookup) {
    const found = [];
    const alphabet = upper ? letters : letters.toLowerCase();
    for (const a of alphabet) for (const b of alphabet) {
      const name = lookup(a + b);
      if (name) found.push([a + b, name]);
    }
    return found;
  }
  // A code the standard has replaced ('UK', 'YU', 'iw') is named too, after
  // the one that replaced it, and would be listed twice.
  function canonical(tag) {
    try { return Intl.getCanonicalLocales(tag)[0]; } catch (e) { return tag; }
  }
  const countries = codes(true, (code) =>
    !NOT_COUNTRIES.has(code) && canonical('und-' + code) === 'und-' + code ? regionNames.of(code) : undefined);
  const languages = codes(false, (code) => {
    const name = languageNames.of(code);
    // 'tl' stays: what replaced it, 'fil', has no two-letter code to list instead.
    const replaced = canonical(code).split('-')[0];
    return name && name.toLowerCase() !== code && (replaced === code || replaced.length !== 2) ? name : undefined;
  });
  let currencies = [];
  try { currencies = Intl.supportedValuesOf('currency').map((code) => [code, currencyNames.of(code) || code]); }
  catch (e) { currencies = []; }
  const byName = (a, b) => a[1].localeCompare(b[1]);
  countries.sort(byName); languages.sort(byName); currencies.sort(byName);

  function label(list, code) {
    const found = list.find((entry) => entry[0] === code);
    return found ? found[1] + ' (' + code + ')' : code;
  }
  function fill(select, list, blank, value) {
    select.textContent = '';
    const first = document.createElement('option');
    first.value = ''; first.textContent = blank;
    select.appendChild(first);
    if (value && !list.find((entry) => entry[0] === value)) list = list.concat([[value, value]]);
    for (const [code, name] of list) {
      const option = document.createElement('option');
      option.value = code; option.textContent = name + ' (' + code + ')';
      select.appendChild(option);
    }
    select.value = value || '';
  }
  function automatic(list, code, what) {
    return code ? 'Worked out: ' + label(list, code) : 'Not set (' + what + ')';
  }

  function updateIntent() {
    const neither = !$('place').checked && !$('handle').checked;
    $('details').classList.toggle('muted', neither);
    $('designOnly').style.display = neither ? '' : 'none';
  }
  function setStatus(id, text, error) {
    $(id).textContent = text || '';
    $(id).classList.toggle('error', !!error);
  }
  let hasService = false;
  function busy(on) {
    for (const id of ['save', 'clear', 'settings']) $(id).disabled = on;
    $('locate').disabled = on || !hasService;
  }

  function show(state, orders) {
    const configured = state.configured, resolved = state.resolved, detected = state.detected;
    const ticked = orders || state.manufacturingOrders || [];
    $('place').checked = ticked.includes('place');
    $('handle').checked = ticked.includes('handle');
    const automaticCountry = configured.country ? detected.country : resolved.country || detected.country;
    const automaticLanguage = configured.language ? detected.language : resolved.language || detected.language;
    const automaticCurrency = configured.currency ? detected.currency : resolved.currency || detected.currency;
    fill($('country'), countries, automatic(countries, automaticCountry, 'none known'), configured.country);
    fill($('language'), languages, automatic(languages, automaticLanguage, 'none known'), configured.language);
    fill($('currency'), currencies, automaticCurrency ? 'From the country: ' + label(currencies, automaticCurrency)
      : 'Not set (from the country)', configured.currency);
    const address = configured.address || {};
    for (const field of ['line1', 'line2', 'city', 'stateCode', 'zipCode']) $(field).value = address[field] || '';
    fill($('countryCode'), countries, 'Not set', address.countryCode);
    const location = configured.location;
    $('location').value = location ? location.latitude + ', ' + location.longitude : '';
    $('locationAccess').checked = !!state.locationAccess;
    $('service').textContent = SERVICES[state.locationService] || '';
    hasService = !!state.locationService;
    $('locationAccess').disabled = !state.locationService && !state.locationAccess;
    if (!state.locationService) setStatus('locateStatus', 'This computer has no location service PartCAD can ask; type the location in.');
    $('settings').style.display = state.settings ? '' : 'none';
    $('file').textContent = state.configFile;
    updateIntent();
  }

  function answers() {
    return {
      orders: ['place', 'handle'].filter((id) => $(id).checked),
      country: $('country').value, language: $('language').value, currency: $('currency').value,
      location: $('location').value, locationAccess: $('locationAccess').checked,
      address: { line1: $('line1').value, line2: $('line2').value, city: $('city').value,
                 stateCode: $('stateCode').value, zipCode: $('zipCode').value, countryCode: $('countryCode').value },
    };
  }

  $('place').addEventListener('change', updateIntent);
  $('handle').addEventListener('change', updateIntent);
  $('clear').addEventListener('click', () => {
    for (const id of ['country', 'language', 'currency', 'countryCode']) $(id).value = '';
    for (const id of ['line1', 'line2', 'city', 'stateCode', 'zipCode', 'location']) $(id).value = '';
    $('locationAccess').checked = false;
    setStatus('status', 'Cleared. Save to leave everything blank.');
  });
  $('save').addEventListener('click', () => {
    const location = $('location').value.trim();
    if (location && !/^\\s*-?\\d+(\\.\\d+)?\\s*,\\s*-?\\d+(\\.\\d+)?\\s*$/.test(location)) {
      setStatus('status', 'The location is two numbers in degrees, latitude first: 52.37, 4.89', true);
      return;
    }
    busy(true); setStatus('status', 'Saving...');
    vscode.postMessage({ type: 'save', answers: answers() });
  });
  $('locate').addEventListener('click', () => {
    busy(true); setStatus('locateStatus', 'Asking this computer where it is...');
    vscode.postMessage({ type: 'locate' });
  });
  $('settings').addEventListener('click', () => vscode.postMessage({ type: 'settings' }));

  window.addEventListener('message', (event) => {
    const message = event.data;
    if (message.type === 'state') { show(message.state, message.orders); busy(false); }
    else if (message.type === 'located') {
      busy(false);
      const answer = message.answer || {};
      if (answer.found && answer.location) {
        $('location').value = answer.location.latitude + ', ' + answer.location.longitude;
        setStatus('locateStatus', 'Found, to about a kilometre. Save to keep it.');
      } else {
        setStatus('locateStatus', answer.message || 'The location service did not answer.', true);
      }
    }
    else if (message.type === 'settingsOpened') {
      const answer = message.answer || {};
      if (!answer.opened) setStatus('locateStatus', answer.detail || 'Could not open the location settings.', true);
    }
    else if (message.type === 'saved') { busy(false); setStatus('status', 'Saved.'); }
    else if (message.type === 'error') { busy(false); setStatus('status', message.message, true); }
  });
  busy(true);
  vscode.postMessage({ type: 'ready' });
})();
</script>
</body>
</html>`;
}
