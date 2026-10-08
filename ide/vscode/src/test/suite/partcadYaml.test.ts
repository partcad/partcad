//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The languages PartCAD's two YAML documents open as: an `.assy` file is
// `partcad-assy` and a package's `partcad.yaml` is `partcad-yaml`. Each is a
// Jinja2 template that renders to YAML, so neither is handed to a YAML checker,
// and both are highlighted by `syntaxes/partcad-yaml.tmLanguage.json` -- the
// editor's YAML grammar with the template's tags injected on top.
//
// The tokens come from the editor itself (`_workbench.captureSyntaxTokens`,
// which VS Code's own colorization tests read), so what is checked is what the
// running editor draws, with the YAML grammar it has -- VS Code's own, under
// `npm test` and in the PartCAD IDE run alike. A YAML extension somebody has
// installed can replace it with one of its own, which no run here covers; that
// is what broke this grammar while it was written, and every failure looked
// the same: correct templates painted as invalid YAML.
//

import * as assert from 'assert';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as vscode from 'vscode';

import { lintOptions } from '../../PartcadLint';
import { pathKey } from '../../common/paths';

type Token = { line: number; column: number; text: string; scopes: string[] };

// Every placement of a template tag that once came out wrong: tags opening the
// file, tag-only lines indented less than the YAML around them (and inside a
// block scalar), expressions as flow entries, signed and joined expressions,
// expressions in quotes, keys and flow mapping values, and comments.
const ASSY_FIXTURE = [
    '{# A header comment #}',
    '{% set gap = 2 %}',
    'links:',
    '{% for i in range(3) %}',
    '  - part: cube',
    '    name: cube-{{ i }}',
    '    location: [[{{ i * gap }}, {{ -i }}, 0], [0, 0, 1], 0]',
    '    other: [-{{ gap }}, -{{gap}}, 1]',
    '    params: { size: {{ gap }}, other: -{{ gap }}, last: 1 }',
    '    nested: {a: [{{ x }}, {{ y }}, 0], b: [{x: {{ g }}, y: 1}, [ {{ g }}, 1 ]]}',
    '    quoted: "{{ gap }} mm"',
    "    single: '{{ gap }}'",
    '    {{ "key" }}: value',
    '    joined: {{ a }}-{{ b }}',
    '    choice: {% if i == 0 %}first{% else %}rest{% endif %}',
    '    list:',
    '      - {{ gap }}',
    '      - {{ gap }}-suffix',
    '    note: value {# inline comment #}',
    '    connect:',
    '      to: x',
    '      {% if i %}',
    '      comment: |',
    '        before',
    '    {% if i %}',
    '        inside {{ i }}',
    '    {% endif %}',
    '        after',
    '      {% endif %}',
    '      how:',
    '        stage: {{ i }}',
    '  {% if i %}  - part: between{% endif %}',
    '  {% endfor %}',
    '  - part: last',
    '    multiline: [',
    '      {{ x }},',
    '      -{{ y }},',
    '      0,',
    '    ]',
    '    location: [[0, 0, 0], [0, 0, 1], {{ angle | default(0) }}]',
    '{#- A comment',
    '    over several lines #}',
    '{% macro leg(x) %}',
    '  - part: leg',
    '    location: [[{{ x }}, 0, 0], [0, 0, 1], 0]',
    '{% endmacro %}',
    '{{ leg(1) }}',
    '',
].join('\n');

const CONFIG_FIXTURE = [
    '{% set new = partcad_version_at_least("0.8.77") %}',
    'name: //pub/example',
    'desc: |',
    '  Rendered by PartCAD {{ partcad_version }}.',
    'parts:',
    '{% for size in [3, 4] %}',
    '  m{{ size }}:',
    '    type: cadquery',
    '    path: screw.py',
    '    parameters:',
    '      diameter: {type: float, default: {{ size }}}',
    '{% endfor %}',
    '{% if new %}',
    '  chosen:',
    '    type: alias',
    '    source: :m3',
    '{% endif %}',
    '',
].join('\n');

/** The tokens the running editor draws for `file`, each put back on its line and column. */
async function tokenize(file: string): Promise<Token[]> {
    const captured = await vscode.commands.executeCommand<{ c: string; t: string }[]>(
        '_workbench.captureSyntaxTokens',
        vscode.Uri.file(file),
    );
    assert.ok(Array.isArray(captured) && captured.length > 0, `the editor returned no tokens for ${file}`);
    // The tokens come line after line without the lines, and without empty
    // ones, so each line takes as many as it has characters for.
    const tokens: Token[] = [];
    let next = 0;
    fs.readFileSync(file, 'utf8')
        .split(/\r?\n/)
        .forEach((line, index) => {
            for (let column = 0; column < line.length && next < captured.length; next++) {
                const token = captured[next];
                tokens.push({ line: index, column, text: token.c, scopes: token.t.split(' ') });
                column += token.c.length;
            }
        });
    assert.strictEqual(next, captured.length, `the tokens for ${file} do not add up to its lines`);
    return tokens;
}

/** What is wrong with how the editor draws `file`, one line per problem; empty when nothing is. */
async function problems(file: string): Promise<string[]> {
    const text = fs.readFileSync(file, 'utf8');
    const tokens = await tokenize(file);
    const found: string[] = [];
    for (const token of tokens) {
        const invalid = token.scopes.find((scope) => scope.startsWith('invalid.'));
        if (invalid !== undefined) {
            found.push(`${token.line + 1}:${token.column + 1} ${JSON.stringify(token.text)} is ${invalid}`);
        }
    }
    // Every tag starts a token of the template's own.
    text.split(/\r?\n/).forEach((line, index) => {
        for (const match of line.matchAll(/\{[{%#]/g)) {
            const token = tokens.find((t) => t.line === index && t.column === match.index);
            if (
                token === undefined ||
                !token.scopes.some((scope) => scope.endsWith('.jinja') && scope !== 'meta.template.jinja')
            ) {
                found.push(
                    `${index + 1}:${(match.index ?? 0) + 1} ${JSON.stringify(match[0])} is not read as a template tag`,
                );
            }
        }
    });
    // And the YAML around them is still read as YAML: without this, a grammar
    // that lost YAML altogether would pass both checks above.
    if (
        /^\s*-?\s*[A-Za-z]\w*:/m.test(text) &&
        !tokens.some((t) => t.scopes.some((s) => s.startsWith('entity.name.tag')))
    ) {
        found.push('no mapping key is read as one: the YAML grammar is not reached');
    }
    return found;
}

function filesUnder(directory: string, wanted: (name: string) => boolean): string[] {
    const found: string[] = [];
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
        const entryPath = path.join(directory, entry.name);
        if (entry.isDirectory()) {
            found.push(...filesUnder(entryPath, wanted));
        } else if (wanted(entry.name)) {
            found.push(entryPath);
        }
    }
    return found;
}

suite("PartCAD's YAML languages", () => {
    let directory: string;

    setup(() => {
        directory = fs.mkdtempSync(path.join(os.tmpdir(), 'partcad-yaml-'));
    });

    teardown(() => {
        fs.rmSync(directory, { recursive: true, force: true });
    });

    function write(name: string, text: string): string {
        const file = path.join(directory, name);
        fs.mkdirSync(path.dirname(file), { recursive: true });
        fs.writeFileSync(file, text);
        return file;
    }

    test('an .assy file opens as PartCAD ASSY, and partcad.yaml as a PartCAD package configuration', async () => {
        const assy = await vscode.workspace.openTextDocument(write('robot.assy', 'links: []\n'));
        assert.strictEqual(assy.languageId, 'partcad-assy');
        const config = await vscode.workspace.openTextDocument(write('partcad.yaml', 'parts: {}\n'));
        assert.strictEqual(config.languageId, 'partcad-yaml');
        // Somebody else's YAML is still YAML.
        const other = await vscode.workspace.openTextDocument(write('parts.yaml', 'parts: {}\n'));
        assert.strictEqual(other.languageId, 'yaml');
    });

    test('the Lint settings are read per document, and only in the shape pc parses', async () => {
        const config = vscode.workspace.getConfiguration('partcad.lint');
        const target = vscode.ConfigurationTarget.Global;
        await config.update('includePaths', ['shared', ' '], target);
        await config.update(
            'extraParams',
            ['desk.length=60', 'not a param', 'a=b=c', ' //pub/v1.2:desk.v2.width=30 ', 'desk.label=a.b=c'],
            target,
        );
        try {
            // A file outside every workspace folder: relative to its own directory.
            const document = await vscode.workspace.openTextDocument(write('robot.assy', 'links: []\n'));
            const options = lintOptions(document);
            // Compared as one file, not as one string: the directory comes from
            // `Uri.fsPath`, which spells a Windows drive letter in lower case.
            assert.deepStrictEqual(
                options.includePaths.map((entry) => pathKey(entry)),
                [pathKey(path.join(directory, 'shared'))],
            );
            assert.deepStrictEqual(options.extraParams, [
                'desk.length=60',
                '//pub/v1.2:desk.v2.width=30',
                'desk.label=a.b=c',
            ]);
        } finally {
            await config.update('includePaths', undefined, target);
            await config.update('extraParams', undefined, target);
        }
    });

    test('template tags are highlighted wherever they are, and correct YAML around them is not an error', async () => {
        assert.deepStrictEqual(await problems(write('opens-with-a-tag.assy', ASSY_FIXTURE)), []);
        // A line with YAML between two tags is not a line of tags: its YAML is
        // still read as YAML, from where the leading tag ends.
        const tokens = await tokenize(path.join(directory, 'opens-with-a-tag.assy'));
        const between = ASSY_FIXTURE.split('\n').findIndex((line) => line.includes('part: between'));
        const key = tokens.find((token) => token.line === between && token.text === 'part');
        assert.ok(
            key?.scopes.some((scope) => scope.startsWith('entity.name.tag')),
            `'part' between two tags is read as ${key?.scopes.join(' ')}`,
        );
        // The same file with YAML on its first line: VS Code picks its full YAML
        // grammar by what the first line is, and its "embedded" one otherwise.
        assert.deepStrictEqual(await problems(write('opens-with-yaml.assy', '# A comment\n' + ASSY_FIXTURE)), []);
        assert.deepStrictEqual(await problems(write('package/partcad.yaml', CONFIG_FIXTURE)), []);
    });

    test('every templated file PartCAD ships is highlighted without errors', async () => {
        const extension = vscode.extensions.getExtension('partcad.partcad-official');
        assert.ok(extension);
        const repository = path.resolve(extension.extensionPath, '..', '..');
        // Only the files with a tag in them: the editor colours every token for
        // several themes on the way, which costs about half a second a file,
        // and a file without one is plain YAML that the fixtures above cover.
        const files = ['examples', path.join('src', 'partcad')]
            .flatMap((root) =>
                filesUnder(path.join(repository, root), (name) => name.endsWith('.assy') || name === 'partcad.yaml'),
            )
            .filter((file) => /\{[{%#]/.test(fs.readFileSync(file, 'utf8')));
        assert.ok(
            files.some((file) => file.endsWith('.assy')),
            `no templated .assy files under ${repository}`,
        );
        const found: string[] = [];
        for (const file of files) {
            for (const problem of await problems(file)) {
                found.push(`${path.relative(repository, file)}:${problem}`);
            }
        }
        assert.deepStrictEqual(found, []);
    });
});
