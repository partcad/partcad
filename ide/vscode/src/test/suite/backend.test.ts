//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// Reading `pc daemon start`'s answer, and what the service sends the terminal view.
//

import * as assert from 'assert';

import { CloseWatch, LOG_MODE_PARAMS, daemonEndpointIn, terminalText } from '../../common/backend';

suite('Where the daemon is', () => {
    test('a socket path is the endpoint', () => {
        assert.strictEqual(
            daemonEndpointIn('/home/me/.partcad/workspaces/0123456789abcdef/socket\n'),
            '/home/me/.partcad/workspaces/0123456789abcdef/socket',
        );
    });

    test('a Windows named pipe is the endpoint', () => {
        // Printed with CRLF by a Windows `pc`, and not an absolute path by any
        // definition `path.isAbsolute` has on a POSIX machine -- which is where
        // this test runs.
        assert.strictEqual(
            daemonEndpointIn('\\\\.\\pipe\\partcad-0123456789abcdef\r\n'),
            '\\\\.\\pipe\\partcad-0123456789abcdef',
        );
    });

    test('a sentence is not an endpoint', () => {
        // What a `pc` without a daemon for this platform prints -- on stdout,
        // with a zero exit status. Taking "the first non-empty line" handed it
        // to `net.connect`, which failed with ENOENT about a filename made of
        // English, and the window was left with no backend at all rather than
        // with a service over stdio.
        assert.strictEqual(
            daemonEndpointIn(
                'The PartCAD socket daemon is not available on Windows yet; ' +
                    'commands run a per-invocation service instead.\n',
            ),
            undefined,
        );
    });

    test('nothing at all is not an endpoint', () => {
        assert.strictEqual(daemonEndpointIn(''), undefined);
        assert.strictEqual(daemonEndpointIn('\n  \n'), undefined);
    });

    test('the endpoint is found past anything printed before it', () => {
        assert.strictEqual(daemonEndpointIn('Starting the daemon...\n/tmp/pc/socket\n'), '/tmp/pc/socket');
    });
});

suite('When the service goes away', () => {
    test('a close nobody asked for is news', () => {
        const watch = new CloseWatch();
        let told = 0;
        watch.onUnexpected(() => told++);
        watch.closed();
        assert.strictEqual(told, 1);
    });

    test('it is news once', () => {
        // `stop()` disposes a connection that has already closed, which can
        // close it again; a second reconnect would replace the first's backend.
        const watch = new CloseWatch();
        let told = 0;
        watch.onUnexpected(() => told++);
        watch.closed();
        watch.closed();
        assert.strictEqual(told, 1);
    });

    test('a close this side asked for is not', () => {
        // `stop()` and `stopDaemon()`: whoever called them reconnects, or means
        // there to be no connection at all.
        const watch = new CloseWatch();
        let told = 0;
        watch.onUnexpected(() => told++);
        watch.expect();
        watch.closed();
        assert.strictEqual(told, 0);
    });

    test('a handler that has been disposed is not told', () => {
        const watch = new CloseWatch();
        let told = 0;
        watch.onUnexpected(() => told++).dispose();
        watch.closed();
        assert.strictEqual(told, 0);
    });

    test('one handler failing does not keep the others from hearing', () => {
        const watch = new CloseWatch();
        let told = 0;
        watch.onUnexpected(() => {
            throw new Error('boom');
        });
        watch.onUnexpected(() => told++);
        watch.closed();
        assert.strictEqual(told, 1);
    });
});

suite('What the service drew', () => {
    const drawn = '\x1b[92m\x1b[1mINFO:\x1b[0m héllo, //pkg:part\n';

    test('the text a service sends as text is drawn as it is', () => {
        assert.strictEqual(terminalText({ text: drawn }), drawn);
    });

    test('the base64 an older service sends is still read, as UTF-8', () => {
        // `atob` would turn the 'é' into two characters of mojibake.
        assert.strictEqual(terminalText({ line: Buffer.from(drawn, 'utf8').toString('base64') }), drawn);
    });

    test('the text is preferred where a service sent both', () => {
        assert.strictEqual(terminalText({ text: drawn, line: Buffer.from('other').toString('base64') }), drawn);
    });

    test('a notification carrying neither draws nothing rather than throwing', () => {
        assert.strictEqual(terminalText({}), '');
        assert.strictEqual(terminalText(undefined), '');
        assert.strictEqual(terminalText({ text: 7 }), '');
    });

    test('the service is asked for text, which one from before ignores', () => {
        assert.deepStrictEqual(LOG_MODE_PARAMS, { ansi: true, text: true });
    });
});
