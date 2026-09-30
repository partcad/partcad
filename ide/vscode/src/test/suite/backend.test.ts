//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// Reading `pc daemon start`'s answer.
//

import * as assert from 'assert';

import { daemonEndpointIn } from '../../common/backend';

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
