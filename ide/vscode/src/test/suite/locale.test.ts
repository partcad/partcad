//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// Where the user is: when the first-run question is asked, and what is run to
// answer it. The answers are written by `pc system locale set`, so the
// arguments built here are the contract with the command line;
// `tests/partcad_cli/unit/test_system_locale.py` runs the same list through the
// real `pc`.
//

import * as assert from 'assert';
import * as vscode from 'vscode';

import {
    CONFIGURE_COMMAND,
    LocaleAnswers,
    LocaleState,
    formHtml,
    leaveBlankArguments,
    parseState,
    refreshDue,
    setArguments,
    shouldAsk,
} from '../../locale';

const EXTENSION_ID = 'partcad.partcad-official';
const DAY = 24 * 60 * 60 * 1000;

function state(overrides: Partial<LocaleState> = {}): LocaleState {
    return {
        configFile: '/home/ann/.partcad/config.yaml',
        asked: false,
        manufacturingOrders: null,
        locationAccess: false,
        configured: { country: null, language: null, currency: null, location: null, address: {} },
        resolved: { country: 'NL', language: 'nl', currency: 'EUR', location: null },
        detected: { country: 'NL', language: 'nl', currency: 'EUR' },
        locationService: 'geoclue',
        settings: true,
        ...overrides,
    };
}

const BLANK: LocaleAnswers = {
    orders: [],
    country: '',
    language: '',
    currency: '',
    location: '',
    locationAccess: false,
    address: { line1: '', line2: '', city: '', stateCode: '', zipCode: '', countryCode: '' },
};

suite('Where the user is', () => {
    test('what `pc system locale show --json` prints is read, and anything else is not', () => {
        assert.strictEqual(parseState(JSON.stringify(state()))?.configFile, '/home/ann/.partcad/config.yaml');
        // A `pc` from before the command prints its usage error, and nothing on stdout.
        assert.strictEqual(parseState(''), undefined);
        assert.strictEqual(parseState('Usage: pc system [OPTIONS]'), undefined);
        assert.strictEqual(parseState('{"something": "else"}'), undefined);
    });

    test('the question is asked once, of a user nobody has asked, in a window that can answer', () => {
        assert.strictEqual(shouldAsk(state(), false, false), true);
        assert.strictEqual(shouldAsk(state({ asked: true, manufacturingOrders: [] }), false, false), false);
        // Closed unanswered in this installation: the command is there for later.
        assert.strictEqual(shouldAsk(state(), true, false), false);
        // The test run itself is a window nobody answers.
        assert.strictEqual(shouldAsk(state(), false, true), false);
        // A PartCAD that cannot ask.
        assert.strictEqual(shouldAsk(undefined, false, false), false);
    });

    test('the location is asked of this machine once a day, and only when the user allowed it', () => {
        const now = 10 * DAY;
        const allowed = state({ asked: true, locationAccess: true });
        assert.strictEqual(refreshDue(allowed, undefined, now), true);
        assert.strictEqual(refreshDue(allowed, now - DAY + 1, now), false);
        assert.strictEqual(refreshDue(allowed, now - DAY, now), true);
        assert.strictEqual(refreshDue(state({ asked: true }), undefined, now), false);
        assert.strictEqual(refreshDue(state({ locationAccess: true, locationService: null }), undefined, now), false);
    });

    test('"leave blank" writes the answer and nothing else', () => {
        assert.deepStrictEqual(leaveBlankArguments(), [
            'system',
            'locale',
            'set',
            '--manufacturing-orders',
            'none',
            '--json',
        ]);
    });

    test('the form writes every field, a blank one as a removal', () => {
        const answers: LocaleAnswers = {
            orders: ['handle', 'place', 'sell'],
            country: ' GB ',
            language: '',
            currency: 'EUR',
            location: '51.5072, -0.1276',
            locationAccess: true,
            address: {
                line1: '1 Example Street',
                line2: '',
                city: 'London',
                stateCode: '',
                zipCode: 'SW1A 1AA',
                countryCode: 'GB',
            },
        };
        assert.deepStrictEqual(setArguments(answers), [
            'system',
            'locale',
            'set',
            '--manufacturing-orders',
            'place,handle',
            '--country',
            'GB',
            '--language',
            '',
            '--currency',
            'EUR',
            '--location',
            '51.5072, -0.1276',
            '--location-access',
            '--line1',
            '1 Example Street',
            '--line2',
            '',
            '--city',
            'London',
            '--state-code',
            '',
            '--zip-code',
            'SW1A 1AA',
            '--address-country',
            'GB',
            '--json',
        ]);
        const blank = setArguments(BLANK);
        assert.deepStrictEqual(blank.slice(3, 5), ['--manufacturing-orders', 'none']);
        assert.ok(blank.includes('--no-location-access'));
    });

    test("the form's script is a script", () => {
        // It is a string to the compiler, so nothing else would notice a
        // syntax error in it before a user opened the form.
        const html = formHtml();
        const script = /<script nonce="[^"]+">([\s\S]*)<\/script>/.exec(html);
        assert.ok(script, 'the form has no inline script');
        assert.doesNotThrow(() => new Function(script[1]));
        // Everything it runs is under the nonce the policy names.
        const policyNonce = /script-src 'nonce-([^']+)'/.exec(html);
        assert.ok(policyNonce && html.includes(`<script nonce="${policyNonce[1]}">`));
    });

    test('the command is contributed under the name it is registered by', () => {
        const extension = vscode.extensions.getExtension(EXTENSION_ID);
        assert.ok(extension, `${EXTENSION_ID} is not installed`);
        const commands = extension.packageJSON.contributes.commands.map((c: { command: string }) => c.command);
        assert.ok(commands.includes(CONFIGURE_COMMAND));
    });
});
