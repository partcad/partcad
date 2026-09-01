//
// PartCAD, 2026
//
// Author: PartCAD (support@partcad.org)
//
// Licensed under Apache License, Version 2.0.
//
// The first start: the package the IDE creates for a new user and the workspace
// it opens, which happens once, in an order that survives the window being
// reopened on the new folder. All of it is invisible until an IDE is built,
// installed and started -- `.github/workflows/build-ide-standalone.yml` does
// exactly that, in about an hour -- so it is worth having the parts that are
// only JavaScript checked in a second.
//
// Run with:  node --test ide/standalone/bootstrap/test
//

const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { test, beforeEach, afterEach } = require('node:test');

const { makeVscode, makeContext, loadExtension } = require('./vscode-stub');

// The fake `pc` below is a shell script.
const posix = { skip: process.platform === 'win32' ? 'POSIX only' : false };

const STARTER = path.join('.partcad', 'projects', 'start');

let home;
let application;
let previousHome;

/** A home directory, and an application directory with tools beside it. */
beforeEach(() => {
    home = fs.mkdtempSync(path.join(os.tmpdir(), 'partcad-ide-home-'));
    application = fs.mkdtempSync(path.join(os.tmpdir(), 'partcad-ide-app-'));
    previousHome = { HOME: process.env.HOME, USERPROFILE: process.env.USERPROFILE };
    process.env.HOME = home;
    process.env.USERPROFILE = home;
});

afterEach(() => {
    for (const [name, value] of Object.entries(previousHome)) {
        if (value === undefined) {
            delete process.env[name];
        } else {
            process.env[name] = value;
        }
    }
    fs.rmSync(home, { recursive: true, force: true });
    fs.rmSync(application, { recursive: true, force: true });
});

/**
 * The command line tools, as the extension looks for them: `<resources>/app` is
 * `appRoot`, and they sit in `<resources>/partcad-cli`.
 *
 * The `pc` written here records how it was run and writes the file `pc init`
 * writes, so that a test can tell "it ran the tools" from "it found a package
 * that was already there".
 */
function bundleTools({ writesPackage = true } = {}) {
    const tools = path.join(application, 'resources', 'partcad-cli');
    fs.mkdirSync(tools, { recursive: true });
    fs.writeFileSync(path.join(tools, 'partcad-json-rpc'), '#!/bin/sh\n', { mode: 0o755 });
    fs.writeFileSync(
        path.join(tools, 'pc'),
        '#!/bin/sh\n' +
            `echo "$@" >> "${path.join(application, 'pc-was-run')}"\n` +
            'pwd >> ' + `"${path.join(application, 'pc-was-run')}"\n` +
            (writesPackage ? 'printf "dependencies:\\n" > partcad.yaml\n' : '') +
            'exit 0\n',
        { mode: 0o755 },
    );
    return path.join(application, 'resources', 'app');
}

function howPcWasRun() {
    const record = path.join(application, 'pc-was-run');
    return fs.existsSync(record) ? fs.readFileSync(record, 'utf-8').trim().split('\n') : [];
}

function commandsRun(vscode) {
    return vscode.calls.filter((call) => call[0] === 'command').map((call) => call.slice(1));
}

function openedFolders(vscode) {
    return commandsRun(vscode)
        .filter((call) => call[0] === 'vscode.openFolder')
        .map((call) => call[1].fsPath);
}

test('the first start creates a package and opens it as the workspace', posix, async () => {
    const appRoot = bundleTools();
    const vscode = makeVscode({ appRoot });
    const context = makeContext();

    await loadExtension(vscode).activate(context);

    const [arguments_, workingDirectory] = howPcWasRun();
    assert.match(arguments_, /^--no-ansi init --desc /, 'it runs `pc init`, with the logging a script wants');
    assert.strictEqual(fs.realpathSync(workingDirectory), fs.realpathSync(path.join(home, STARTER)));
    assert.deepStrictEqual(openedFolders(vscode), [path.join(home, STARTER)]);

    // Not yet: the walkthrough is an editor, and `vscode.openFolder` takes the
    // window it would be opened in with it.
    assert.deepStrictEqual(
        commandsRun(vscode).filter((call) => call[0] === 'workbench.action.openWalkthrough'),
        [],
    );
    assert.strictEqual(context.globalState.get('partcadIde.welcome.pending'), true);
});

test('the welcome window opens in the window that the folder was opened in', posix, async () => {
    const appRoot = bundleTools();
    const context = makeContext();

    const first = makeVscode({ appRoot });
    await loadExtension(first).activate(context);

    // What the editor does next: the same extension, activated again, in the
    // window that now has the starter package open.
    const second = makeVscode({ appRoot, workspaceFolders: [path.join(home, STARTER)] });
    await loadExtension(second).activate(context);

    assert.deepStrictEqual(
        commandsRun(second).filter((call) => call[0] === 'workbench.action.openWalkthrough'),
        [['workbench.action.openWalkthrough', 'PartCAD.partcad-ide-bootstrap#partcadStart', false]],
    );
    assert.deepStrictEqual(openedFolders(second), [], 'the first start does not happen twice');
    assert.strictEqual(context.globalState.get('partcadIde.welcome.pending'), false);

    // And a start after that is an ordinary one.
    const third = makeVscode({ appRoot, workspaceFolders: [path.join(home, STARTER)] });
    await loadExtension(third).activate(context);
    assert.deepStrictEqual(commandsRun(third), [['workbench.view.extension.partcad-container']]);
});

test('an IDE started on a folder of the user\'s own is left alone', posix, async () => {
    const appRoot = bundleTools();
    const project = path.join(home, 'projects', 'something-of-my-own');
    fs.mkdirSync(project, { recursive: true });

    const vscode = makeVscode({ appRoot, workspaceFolders: [project] });
    const context = makeContext();
    await loadExtension(vscode).activate(context);

    assert.deepStrictEqual(howPcWasRun(), [], 'nothing was created');
    assert.deepStrictEqual(openedFolders(vscode), [], 'and nothing was opened over their workspace');

    // And it does not happen to the next empty window either: the first start
    // has been had.
    const later = makeVscode({ appRoot });
    await loadExtension(later).activate(context);
    assert.deepStrictEqual(openedFolders(later), []);
});

test('a package that is already there is opened rather than created again', posix, async () => {
    const appRoot = bundleTools();
    const starter = path.join(home, STARTER);
    fs.mkdirSync(starter, { recursive: true });
    fs.writeFileSync(path.join(starter, 'partcad.yaml'), 'dependencies:\n');

    const vscode = makeVscode({ appRoot });
    await loadExtension(vscode).activate(makeContext());

    assert.deepStrictEqual(howPcWasRun(), [], '`pc init` would have refused, and said so to nobody');
    assert.deepStrictEqual(openedFolders(vscode), [starter]);
});

test('an IDE without the command line tools shows the welcome window and nothing else', posix, async () => {
    // A developer build, or this extension in an editor of the user's own:
    // there is no `pc` to run, so there is no package to open.
    const vscode = makeVscode({ appRoot: path.join(application, 'resources', 'app') });
    const context = makeContext();
    await loadExtension(vscode).activate(context);

    assert.deepStrictEqual(openedFolders(vscode), []);
    assert.ok(!fs.existsSync(path.join(home, '.partcad')), 'it did not leave an empty directory behind');
    assert.deepStrictEqual(
        commandsRun(vscode).filter((call) => call[0] === 'workbench.action.openWalkthrough'),
        [['workbench.action.openWalkthrough', 'PartCAD.partcad-ide-bootstrap#partcadStart', false]],
    );
});

test('a `pc init` that wrote nothing is not reported as a workspace', posix, async () => {
    // `pc init` reports a refusal by logging it and exiting 0, so the file it
    // was supposed to write is what says whether it worked.
    const appRoot = bundleTools({ writesPackage: false });
    const vscode = makeVscode({ appRoot });
    await loadExtension(vscode).activate(makeContext());

    assert.strictEqual(howPcWasRun().length, 2, 'it tried');
    assert.deepStrictEqual(openedFolders(vscode), [], 'and opened nothing');
    assert.ok(!fs.existsSync(path.join(home, STARTER)), 'and left no empty directory behind');
});

test('the starter package can be turned off', posix, async () => {
    const appRoot = bundleTools();
    const vscode = makeVscode({ appRoot });
    vscode.settings.set('partcadIde.createStarterPackage', false);

    await loadExtension(vscode).activate(makeContext());

    assert.deepStrictEqual(howPcWasRun(), []);
    assert.deepStrictEqual(openedFolders(vscode), []);
});

test('the command opens the package, and shows its configuration when it is open already', posix, async () => {
    const appRoot = bundleTools();
    const starter = path.join(home, STARTER);

    const vscode = makeVscode({ appRoot });
    const context = makeContext();
    const extension = loadExtension(vscode);
    await extension.activate(context);
    vscode.calls.length = 0;

    // In a window that has something else open, it opens the folder...
    const elsewhere = makeVscode({ appRoot, workspaceFolders: [path.join(home, 'elsewhere')] });
    const elsewhereContext = makeContext();
    await loadExtension(elsewhere).activate(elsewhereContext);
    elsewhere.calls.length = 0;
    await elsewhere.commands.registered.get('partcadIde.openStarterPackage')();
    assert.deepStrictEqual(openedFolders(elsewhere), [starter]);

    // ...and in the one that has the starter package open, it shows the file,
    // rather than reloading the window onto the folder it is already on.
    const opened = makeVscode({ appRoot, workspaceFolders: [starter] });
    await loadExtension(opened).activate(makeContext());
    opened.calls.length = 0;
    await opened.commands.registered.get('partcadIde.openStarterPackage')();
    assert.deepStrictEqual(openedFolders(opened), []);
    assert.deepStrictEqual(
        opened.calls.filter((call) => call[0] === 'showTextDocument'),
        [['showTextDocument', path.join(starter, 'partcad.yaml')]],
    );
});

// ---------------------------------------------------------------------------
// The examples the welcome window offers. They are packages copied into the
// extension when the IDE is built (`tools/copy_examples.py`), and copied again
// -- with whatever they reference -- into the user's own package when one is
// chosen.
// ---------------------------------------------------------------------------

/** An extension directory carrying two examples, one of which needs the other. */
function bundleExamples({ withPackages = true } = {}) {
    const extension = fs.mkdtempSync(path.join(os.tmpdir(), 'partcad-ide-ext-'));
    fs.writeFileSync(
        path.join(extension, 'examples.json'),
        JSON.stringify({
            examples: [
                { package: 'a_part', label: 'A part', detail: 'one script', open: 'cube.py' },
                {
                    package: 'an_assembly',
                    label: 'An assembly',
                    detail: 'parts from another package',
                    open: 'it.assy',
                    requires: ['a_part'],
                    documentation: 'https://partcad.readthedocs.io/en/latest/assy.html',
                },
            ],
        }),
    );
    if (withPackages) {
        for (const [name, file] of [
            ['a_part', 'cube.py'],
            ['an_assembly', 'it.assy'],
        ]) {
            const directory = path.join(extension, 'examples', name);
            fs.mkdirSync(directory, { recursive: true });
            fs.writeFileSync(path.join(directory, 'partcad.yaml'), 'parts:\n');
            fs.writeFileSync(path.join(directory, file), '# from the IDE\n');
        }
    }
    return extension;
}

test('an example is copied into the starter package, with what it needs', posix, async () => {
    const appRoot = bundleTools();
    const extension = bundleExamples();
    const vscode = makeVscode({ appRoot, workspaceFolders: [path.join(home, STARTER)] });
    vscode.window.picked = 'An assembly';
    vscode.window.pressed = 'Documentation';

    const context = makeContext(extension);
    await loadExtension(vscode).activate(context);
    await vscode.commands.registered.get('partcadIde.openExample')();

    const starter = path.join(home, STARTER);
    assert.ok(fs.existsSync(path.join(starter, 'an_assembly', 'it.assy')));
    assert.ok(fs.existsSync(path.join(starter, 'a_part', 'partcad.yaml')), 'the package its parts come from too');

    assert.deepStrictEqual(
        vscode.calls.filter((call) => call[0] === 'showTextDocument'),
        [['showTextDocument', path.join(starter, 'an_assembly', 'it.assy')]],
    );
    // The Explorer read the package when the workspace was opened, so a
    // subdirectory that appeared afterwards is one it has not seen.
    assert.ok(commandsRun(vscode).some((call) => call[0] === 'partcad.refresh'));
    assert.deepStrictEqual(
        vscode.calls.filter((call) => call[0] === 'openExternal'),
        [['openExternal', 'https://partcad.readthedocs.io/en/latest/assy.html']],
    );

    fs.rmSync(extension, { recursive: true, force: true });
});

test('a copy the user has already edited is left alone', posix, async () => {
    const appRoot = bundleTools();
    const extension = bundleExamples();
    const starter = path.join(home, STARTER);
    fs.mkdirSync(path.join(starter, 'a_part'), { recursive: true });
    fs.writeFileSync(path.join(starter, 'a_part', 'partcad.yaml'), '# mine now\n');
    fs.writeFileSync(path.join(starter, 'a_part', 'cube.py'), '# mine now\n');

    const vscode = makeVscode({ appRoot, workspaceFolders: [starter] });
    vscode.window.picked = 'A part';
    await loadExtension(vscode).activate(makeContext(extension));
    await vscode.commands.registered.get('partcadIde.openExample')();

    assert.strictEqual(fs.readFileSync(path.join(starter, 'a_part', 'cube.py'), 'utf-8'), '# mine now\n');

    fs.rmSync(extension, { recursive: true, force: true });
});

test('an IDE built without the examples says so rather than offering them', posix, async () => {
    const appRoot = bundleTools();
    const extension = bundleExamples({ withPackages: false });
    const vscode = makeVscode({ appRoot, workspaceFolders: [path.join(home, STARTER)] });

    await loadExtension(vscode).activate(makeContext(extension));
    await vscode.commands.registered.get('partcadIde.openExample')();

    assert.deepStrictEqual(
        vscode.calls.filter((call) => call[0] === 'quickPick'),
        [],
        'nothing was offered',
    );
    assert.match(vscode.calls.find((call) => call[0] === 'error')[1], /built without the example packages/);

    fs.rmSync(extension, { recursive: true, force: true });
});
