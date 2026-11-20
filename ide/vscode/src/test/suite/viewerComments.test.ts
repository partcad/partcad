//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The 3D view's comments: what a reference says, where each thread is pinned on
// the tree, what a click on an assembly is about, the Markdown a comment is
// written in, and - on the host - the files picked to attach and the name a
// comment is signed with.
//
// What the scene draws for them is 'scene.ts', which cannot be loaded here; the
// grammar's normative twin is 'partcad_utils/comments.py', tested in
// 'tests/partcad_utils/test_comments.py'.
//

import * as assert from 'assert';
import { execFileSync } from 'child_process';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';

import { attachmentNames, gitAuthor } from '../../viewer/comments';
import {
    CommentsData,
    countThreads,
    describeRef,
    linkRef,
    objectNames,
    parseElementRef,
    parseInline,
    parseMarkdown,
    pinThreads,
    threadHeading,
} from '../../webview/comments';
import { ShowNode } from '../../webview/messages';

/** A frame of two brackets on a base, the second bracket inside a sub-assembly. */
const FRAME: ShowNode = {
    name: '//p:frame',
    assembly: [
        { name: '//p:base', label: 'base' },
        { name: '//p:bracket', label: 'left' },
        {
            name: '//p:arm',
            label: 'arm',
            assembly: [{ name: '//p:bracket', label: 'link#1' }, { name: '//p:bolt' }],
        },
    ],
};

function thread(index: number, ref: string | null, text = 'Hello', at?: [number, number, number]) {
    return {
        index,
        ref,
        about: describeRef(ref),
        ...(at ? { at } : {}),
        comments: [{ ...(ref ? { ref } : {}), name: 'Ada', date: '2026-11-19 14:31:01 UTC', text }],
    };
}

suite('Viewer comments', () => {
    test('a reference to a face or an edge is read, and nothing else is taken for one', () => {
        assert.deepStrictEqual(parseElementRef('face:12'), ['face', 12]);
        assert.deepStrictEqual(parseElementRef(' edge:3 '), ['edge', 3]);
        for (const other of ['face:0', 'face:', 'Face:1', 'vertex:2', 'base', 'link#2', '', null, undefined]) {
            assert.strictEqual(parseElementRef(other), undefined, String(other));
        }
        assert.strictEqual(describeRef('face:12'), 'face 12');
        assert.strictEqual(describeRef('arm:link#1'), 'arm:link#1');
        // A selection reads as it is written.
        assert.strictEqual(describeRef('faces().sort_by(Axis.Z)[-1]'), 'faces().sort_by(Axis.Z)[-1]');
        assert.strictEqual(parseElementRef('faces(">Z")'), undefined);
        assert.strictEqual(describeRef(undefined), 'the whole object');
    });

    test('a click on a part of an assembly is about the link names down to it', () => {
        assert.strictEqual(linkRef(FRAME, [0]), 'base');
        assert.strictEqual(linkRef(FRAME, [2, 0]), 'arm:link#1');
        // A child nothing named is its position, as 'Assembly.link_name' says.
        assert.strictEqual(linkRef(FRAME, [2, 1]), 'arm:link#2');
        // Seen from the sub-assembly, it is its own link.
        assert.strictEqual(linkRef(FRAME, [2, 1], [2]), 'link#2');
        assert.strictEqual(linkRef(FRAME, []), '');
    });

    test('every object the tree draws is asked about once', () => {
        assert.deepStrictEqual(objectNames(FRAME), ['//p:frame', '//p:base', '//p:bracket', '//p:arm', '//p:bolt']);
        assert.deepStrictEqual(objectNames({ assembly: [] }, '//p:root'), ['//p:root']);
    });

    test('each thread is pinned once: to its face, its link, or the object as a whole', () => {
        const data: CommentsData = {
            objects: {
                '//p:frame': {
                    object: '//p:frame',
                    kind: 'assembly',
                    threads: [thread(0, 'base'), thread(1, 'arm:link#1'), thread(2, null), thread(4, 'gone')],
                },
                '//p:bracket': {
                    object: '//p:bracket',
                    kind: 'part',
                    threads: [
                        thread(0, 'face:3', 'thin', [1, 2, 3]),
                        thread(1, 'edge:9'),
                        // A selection the daemon found where it is, as a CadQuery script writes one.
                        thread(2, 'faces(">Z")', 'top', [0, 0, 5]),
                    ],
                },
                '//p:arm': { object: '//p:arm', kind: 'assembly', threads: [thread(0, 'link#2')] },
                '//p:base': { object: '//p:base', error: 'not found' },
            },
        };
        const pins = pinThreads(FRAME, data);
        const summary = pins.map((pin) => [pin.object, pin.thread.index, pin.path, pin.target, pin.at]);
        assert.deepStrictEqual(summary, [
            ['//p:frame', 0, [], [0], undefined],
            ['//p:frame', 1, [], [2, 0], undefined],
            // About the whole object, and about a link the tree does not have.
            ['//p:frame', 2, [], undefined, undefined],
            ['//p:frame', 4, [], undefined, undefined],
            // The bracket is placed twice and pinned on the first; an edge the
            // daemon did not find goes to the part as a whole.
            ['//p:bracket', 0, [1], undefined, [1, 2, 3]],
            ['//p:bracket', 1, [1], undefined, undefined],
            ['//p:bracket', 2, [1], undefined, [0, 0, 5]],
            ['//p:arm', 0, [2], [2, 1], undefined],
        ]);
        assert.strictEqual(threadHeading(pins[4]), 'face 3 · bracket');
        assert.strictEqual(threadHeading(pins[2]), 'the whole object · frame');
        assert.deepStrictEqual(countThreads(data), { threads: 8, comments: 8 });
        // A root that does not say its name is named by the caller.
        const alone = pinThreads(
            {},
            { objects: { '//p:x': { object: '//p:x', threads: [thread(0, null)] } } },
            '//p:x',
        );
        assert.strictEqual(alone.length, 1);
    });

    test('a comment is Markdown, and only what it chose becomes formatting', () => {
        assert.deepStrictEqual(parseInline('a **b** *c* `d` [e](https://x.org) f'), [
            { text: 'a ' },
            { text: 'b', strong: true },
            { text: ' ' },
            { text: 'c', emphasis: true },
            { text: ' ' },
            { text: 'd', code: true },
            { text: ' ' },
            { text: 'e', href: 'https://x.org' },
            { text: ' f' },
        ]);
        // A snake_case name is a name, not emphasis.
        assert.deepStrictEqual(parseInline('min_wall_thickness'), [{ text: 'min_wall_thickness' }]);
        // Markup is text like any other.
        assert.deepStrictEqual(parseInline('<img src=x onerror=alert(1)>'), [{ text: '<img src=x onerror=alert(1)>' }]);

        const blocks = parseMarkdown('# Too thin\nThis face\nis thin.\n\n- one\n- two\n\n> quoted\n\n```\nx = 1\n```');
        assert.deepStrictEqual(
            blocks.map((block) => [block.kind, block.lines.map((line) => line.map((run) => run.text).join(''))]),
            [
                ['heading', ['Too thin']],
                ['paragraph', ['This face', 'is thin.']],
                ['item', ['one']],
                ['item', ['two']],
                ['quote', ['quoted']],
                ['code', ['x = 1']],
            ],
        );
    });

    test('a link keeps the parentheses of its destination, and a list goes on from its first number', () => {
        assert.deepStrictEqual(parseInline('see [drawing](https://example.org/bracket(left)).'), [
            { text: 'see ' },
            { text: 'drawing', href: 'https://example.org/bracket(left)' },
            { text: '.' },
        ]);
        const blocks = parseMarkdown('4. clamp it\n5. drill it\n\n1. again');
        assert.deepStrictEqual(
            blocks.map((block) => [block.kind, block.number]),
            [
                ['ordered', 4],
                ['ordered', 5],
                ['ordered', 1],
            ],
        );
    });

    test('a line is read once, however many delimiters in it are never closed', () => {
        // Each of these used to read the rest of the line again from every
        // position: some twenty seconds for a line of them, on the viewer's thread.
        for (const opener of ['[', '[a](b', '`', '*', '_ ']) {
            const line = opener.repeat(Math.ceil(200000 / opener.length));
            const started = Date.now();
            const runs = parseInline(line);
            assert.ok(Date.now() - started < 2000, `a line of '${opener}' took ${Date.now() - started} ms`);
            // Unmatched, it is the text it was.
            assert.strictEqual(runs.map((run) => run.text).join(''), line);
        }
    });

    test('an attachment is named relative to the package, and one outside it is refused', () => {
        const root = path.join(os.tmpdir(), 'package');
        const { files, outside } = attachmentNames(root, [
            path.join(root, 'photos', 'crack.jpg'),
            path.join(root, 'notes.md'),
            // A name that starts with two dots is a file of the package all the same.
            path.join(root, '..review.txt'),
            path.join(os.tmpdir(), 'elsewhere.txt'),
            root,
        ]);
        assert.deepStrictEqual(files, ['photos/crack.jpg', 'notes.md', '..review.txt']);
        assert.deepStrictEqual(outside, [path.join(os.tmpdir(), 'elsewhere.txt'), root]);
    });

    test("a comment is signed with git's name for whoever is at this machine", async function () {
        this.timeout(20000);
        const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'pc-comment-'));
        try {
            execFileSync('git', ['init', '-q'], { cwd: directory });
            execFileSync('git', ['config', 'user.name', 'Ada Lovelace'], { cwd: directory });
            assert.strictEqual(await gitAuthor(directory), 'Ada Lovelace');
            // No git at all names nobody, rather than failing.
            assert.strictEqual(await gitAuthor(directory, path.join(directory, 'no-such-git')), undefined);
        } finally {
            fs.rmSync(directory, { recursive: true, force: true });
        }
    });
});
