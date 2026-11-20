//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The comments the 3D view shows when "Comments" is ticked, and writes.
//
// A package and every object it declares may carry 'comments:' - a list of
// threads, each an ordered list of comments, oldest first, every comment saying
// who ('name', from git), when ('date', UTC to the second), what ('text',
// Markdown) and what goes with it ('attachments'). 'ref' says what *inside* the
// object a thread is about, in the terms of the object's kind: 'face:12' or
// 'edge:3' of a part or a sketch - or a selection, as its script would make one:
// CadQuery's 'faces(">Z")', build123d's 'faces().sort_by(Axis.Z)[-1]', which the
// daemon answers for a click on a part made by either ('comment.locate', and
// 'partcad_utils/selector_refs.py') - a link of an assembly or a scene - the link
// names down to it joined with ':', the way a port of something inside is named
// ('shape_ports.qualify', and 'reportedAs' in 'tree.ts'). The normative
// description, and the Python twin of the grammar, is 'partcad_utils/comments.py'.
//
// This file is the half of it that is not three.js: what the daemon answers
// ('comment.list'), where on the tree each thread is pinned ('pinThreads'), what
// a click on the model is about ('linkRef'), and what a thread's callout says,
// Markdown included ('renderMarkdown') - built node by node, like everything the
// panel shows: a comment is text somebody typed into a package, and it must not
// become markup.
//
// Free of three.js, so that it can be tested outside a browser; see
// 'src/test/suite/viewerComments.test.ts'.
//

import { el, link } from './dom';
import { ShowNode } from './messages';
import { walk } from './nodes';

/** One comment of a thread, as 'comment.list' answers it. */
export interface CommentEntry {
    ref?: string;
    name: string;
    date: string;
    text: string;
    attachments?: string[];
}

/** One thread of an object's comments. */
export interface CommentThread {
    /** Its position in the declaration's list: what a reply names. */
    index: number;
    /** What it is about - its first comment's 'ref' - or null for the object as a whole. */
    ref: string | null;
    /** The same, in words: 'face 12', 'base', 'the whole object'. */
    about: string;
    /**
     * For a face or an edge - by its number, or a CadQuery or build123d
     * selection of it - a point on it in the object's own frame, in millimetres,
     * where the daemon could work one out.
     */
    at?: [number, number, number];
    comments: CommentEntry[];
}

/** What 'comment.list' says about one object. */
export interface CommentedObject {
    object: string;
    kind?: string | null;
    package?: string;
    /** The 'partcad.yaml' the comments are written into, on the daemon's machine. */
    config?: string | null;
    /** The package's directory, which attachments are relative to. */
    directory?: string | null;
    /** Whether a comment can be written on it: declared in its own package's file, which is no template. */
    writable?: boolean;
    threads?: CommentThread[];
    /** Why nothing could be said about it. */
    error?: string;
}

/** The answer to 'comment.list', by the name each object was asked for under. */
export interface CommentsData {
    objects?: Record<string, CommentedObject>;
}

/** The answer to 'comment.locate': which face or edge a click is on. */
export interface CommentLocated {
    object: string;
    kind: string;
    ref: string;
    element: 'face' | 'edge';
    index: number;
    at: [number, number, number];
    distance: number;
    about: string;
    /** The element by its number ('face:12'), whatever 'ref' is. */
    numbered?: string;
    /** How 'ref' is written: 'cadquery', 'build123d' or 'number' - as the part's type says. */
    style?: string;
}

/** The answer to 'comment.add'. */
export interface CommentAdded {
    object: string;
    kind: string | null;
    config: string;
    thread: number;
    comment: CommentEntry;
}

/** How link names are joined into a path: as a port of something inside is named. */
export const LINK_SEPARATOR = ':';

/** The kinds whose comments are pinned to a face or an edge. */
export const ELEMENT_KINDS = ['part', 'sketch'];

const ELEMENT_REF = /^(face|edge):([1-9][0-9]*)$/;

/** ['face', 12] for 'face:12', or undefined for a reference to anything else. */
export function parseElementRef(ref: string | null | undefined): ['face' | 'edge', number] | undefined {
    const found = ELEMENT_REF.exec((ref ?? '').trim());
    return found ? [found[1] as 'face' | 'edge', Number(found[2])] : undefined;
}

/** What a reference points at, in words - the twin of 'describe_ref'. */
export function describeRef(ref: string | null | undefined): string {
    if (!ref) {
        return 'the whole object';
    }
    const element = parseElementRef(ref);
    return element ? `${element[0]} ${element[1]}` : ref;
}

/** What a node is called by the node holding it: its label, or its position there. */
function linkName(node: ShowNode, index: number): string {
    return node.label || `link#${index + 1}`;
}

/**
 * What a comment on the node at 'path' says it is about, as seen from the node
 * at 'from' (a prefix of it): the link names down from one to the other, joined
 * with ':'. Empty when the two are the same node - the object as a whole.
 */
export function linkRef(root: ShowNode, path: readonly number[], from: readonly number[] = []): string {
    const names: string[] = [];
    let node: ShowNode | undefined = root;
    path.forEach((index, depth) => {
        node = node?.assembly?.[index];
        if (node !== undefined && depth >= from.length) {
            names.push(linkName(node, index));
        }
    });
    return names.join(LINK_SEPARATOR);
}

/** Where one thread is pinned on the tree, and what it is. */
export interface ThreadPin {
    /** The node of the object the thread is on: the callout hangs under it. */
    path: number[];
    /** A point in that node's own frame, in millimetres: the face or the edge the thread is about. */
    at?: [number, number, number];
    /**
     * The node the thread is about, under that one - a link of the object - at
     * the top corner of which the callout goes. Absent with 'at', and for a
     * thread about the object as a whole, which goes to the top corner of the
     * node itself. Threads pinned to one place share one callout.
     */
    target?: number[];
    /** The object the thread is on, by the name it was asked for under. */
    object: string;
    /** And its kind, as the daemon says it. */
    kind: string | null;
    thread: CommentThread;
}

/**
 * Where each thread of the objects in a tree goes: one pin per thread.
 *
 * A thread is on an object, and an object can be in a tree many times - a bolt
 * an assembly places a hundred times - so it is pinned to the first node that
 * holds it, parents before children, rather than written out a hundred times.
 * A thread about a face or an edge is pinned where the daemon found it ('at');
 * one about a link, to the node that link names under that one, and one whose
 * link the tree does not have - renamed, or taken out - to the object as a
 * whole, as is one about nothing in particular. 'rootName' is what the root is
 * called where the root node does not say.
 */
export function pinThreads(root: ShowNode, data: CommentsData | undefined, rootName?: string): ThreadPin[] {
    const objects = data?.objects ?? {};
    const pins: ThreadPin[] = [];
    const seen = new Set<string>();
    walk(root, (node, path) => {
        const name = (path.length === 0 ? node.name || rootName : node.name) ?? undefined;
        if (!name || seen.has(name)) {
            return;
        }
        seen.add(name);
        const found = objects[name];
        for (const thread of found?.threads ?? []) {
            if (!thread.comments?.length) {
                continue;
            }
            const pin: ThreadPin = { path, object: name, kind: found?.kind ?? null, thread };
            if (thread.at !== undefined) {
                pin.at = thread.at;
            } else if (thread.ref) {
                const target = findLink(node, thread.ref);
                if (target !== undefined) {
                    pin.target = [...path, ...target];
                }
            }
            pins.push(pin);
        }
    });
    return pins;
}

/** The path, under 'node', of the node its link names 'ref' reach - or undefined. */
function findLink(node: ShowNode, ref: string): number[] | undefined {
    let found: number[] | undefined;
    walk(node, (_inner, path) => {
        if (found === undefined && path.length > 0 && linkRef(node, path) === ref) {
            found = path;
        }
    });
    return found;
}

/** The names of the objects a tree draws, each once: what 'comment.list' is asked about. */
export function objectNames(root: ShowNode, rootName?: string): string[] {
    const names = new Set<string>();
    walk(root, (node, path) => {
        const name = path.length === 0 ? node.name || rootName : node.name;
        if (name) {
            names.add(name);
        }
    });
    return [...names];
}

/** How many comments, and how many threads, as a note says it. */
export function countThreads(data: CommentsData | undefined): { threads: number; comments: number } {
    let threads = 0;
    let comments = 0;
    for (const found of Object.values(data?.objects ?? {})) {
        for (const thread of found.threads ?? []) {
            if (thread.comments?.length) {
                threads += 1;
                comments += thread.comments.length;
            }
        }
    }
    return { threads, comments };
}

/*
 * Markdown, the small part of it a comment uses.
 *
 * Parsed into blocks of inline runs first, which is plain data and what the
 * tests read, and only then built into elements: paragraphs, '#' headings,
 * '-'/'*'/'1.' list items, '```' code blocks and '>' quotes; and within a line,
 * `code`, **strong**, *emphasis* (or _emphasis_) and [links](https://...).
 * Anything else is the text it is. Nothing here ever becomes markup: every run
 * is a text node in an element this code chose.
 */

/** One run of text within a line, and how it is set. */
export interface MarkdownRun {
    text: string;
    code?: boolean;
    strong?: boolean;
    emphasis?: boolean;
    /** Where a link goes; the run is its text. */
    href?: string;
}

/** One block of a comment. */
export interface MarkdownBlock {
    kind: 'paragraph' | 'heading' | 'item' | 'ordered' | 'code' | 'quote';
    /** The lines of a paragraph, an item or a quote, each a list of runs; one line of one run for code. */
    lines: MarkdownRun[][];
    /** The number an ordered item is written with: a list goes on from where its first item says. */
    number?: number;
}

/**
 * The inline forms, tried in order at each position of a line: each a pattern
 * matched there ('y', from 'lastIndex') and what the run it matches is. An
 * underscore only opens emphasis where no letter or digit comes before it, so
 * that a snake_case name stays the text it is.
 *
 * None of them reads past the next character that would open or close the same
 * form - a link's text and its destination stop at the next bracket - so a line
 * is read once over however many delimiters in it are never closed: a line of
 * a thousand '[' does not read the rest of the line a thousand times. A link's
 * destination may hold a pair of parentheses, as a URL does
 * ('https://example.org/bracket(left)'), but not a bracket.
 */
const INLINE: { pattern: RegExp; run: (found: RegExpExecArray) => MarkdownRun; wordStart?: boolean }[] = [
    { pattern: /`([^`]+)`/y, run: (found) => ({ text: found[1], code: true }) },
    { pattern: /\*\*([^*]+)\*\*/y, run: (found) => ({ text: found[1], strong: true }) },
    { pattern: /__([^_]+)__/y, run: (found) => ({ text: found[1], strong: true }), wordStart: true },
    { pattern: /\*([^*\s][^*]*)\*/y, run: (found) => ({ text: found[1], emphasis: true }) },
    {
        pattern: /_([^_\s][^_]*)_(?![A-Za-z0-9])/y,
        run: (found) => ({ text: found[1], emphasis: true }),
        wordStart: true,
    },
    {
        pattern: /\[([^[\]]+)\]\(((?:[^()[\]\s]|\([^()[\]\s]*\))+)\)/y,
        run: (found) => ({ text: found[1], href: found[2] }),
    },
];

/** The runs of one line of text. */
export function parseInline(line: string): MarkdownRun[] {
    const runs: MarkdownRun[] = [];
    let plain = '';
    let i = 0;
    while (i < line.length) {
        const afterWord = /[A-Za-z0-9]/.test(line[i - 1] ?? '');
        let taken = 0;
        for (const form of INLINE) {
            if (form.wordStart && afterWord) {
                continue;
            }
            form.pattern.lastIndex = i;
            const found = form.pattern.exec(line);
            if (found !== null) {
                if (plain) {
                    runs.push({ text: plain });
                    plain = '';
                }
                runs.push(form.run(found));
                taken = found[0].length;
                break;
            }
        }
        if (taken === 0) {
            plain += line[i];
            taken = 1;
        }
        i += taken;
    }
    if (plain) {
        runs.push({ text: plain });
    }
    return runs;
}

/** A comment's text as blocks. */
export function parseMarkdown(text: string): MarkdownBlock[] {
    const blocks: MarkdownBlock[] = [];
    const lines = text.replace(/\r\n?/g, '\n').split('\n');
    let paragraph: MarkdownBlock | undefined;
    let i = 0;
    const end = () => {
        paragraph = undefined;
    };
    while (i < lines.length) {
        const line = lines[i];
        let match: RegExpExecArray | null;
        if (/^\s*```/.test(line)) {
            end();
            const code: string[] = [];
            i += 1;
            while (i < lines.length && !/^\s*```/.test(lines[i])) {
                code.push(lines[i]);
                i += 1;
            }
            blocks.push({ kind: 'code', lines: [[{ text: code.join('\n'), code: true }]] });
            i += 1;
            continue;
        }
        if (line.trim() === '') {
            end();
        } else if ((match = /^\s{0,3}#{1,6}\s+(.*)$/.exec(line))) {
            end();
            blocks.push({ kind: 'heading', lines: [parseInline(match[1].replace(/\s#+\s*$/, ''))] });
        } else if ((match = /^\s*[-*+]\s+(.*)$/.exec(line))) {
            end();
            paragraph = { kind: 'item', lines: [parseInline(match[1])] };
            blocks.push(paragraph);
        } else if ((match = /^\s*([0-9]{1,9})[.)]\s+(.*)$/.exec(line))) {
            end();
            paragraph = { kind: 'ordered', lines: [parseInline(match[2])], number: Number(match[1]) };
            blocks.push(paragraph);
        } else if ((match = /^\s*>\s?(.*)$/.exec(line))) {
            if (paragraph?.kind !== 'quote') {
                end();
                paragraph = { kind: 'quote', lines: [] };
                blocks.push(paragraph);
            }
            paragraph.lines.push(parseInline(match[1]));
        } else if (paragraph !== undefined && paragraph.kind !== 'quote') {
            // A line under a paragraph or an item continues it.
            paragraph.lines.push(parseInline(line.trim()));
        } else {
            paragraph = { kind: 'paragraph', lines: [parseInline(line.trim())] };
            blocks.push(paragraph);
        }
        i += 1;
    }
    return blocks;
}

function runElement(run: MarkdownRun): HTMLElement {
    if (run.href !== undefined) {
        const anchor = link(run.text, run.href, 'comment-link');
        anchor.title = run.href;
        return anchor;
    }
    if (run.code) {
        return el('code', undefined, run.text);
    }
    if (run.strong) {
        return el('strong', undefined, run.text);
    }
    if (run.emphasis) {
        return el('em', undefined, run.text);
    }
    return el('span', undefined, run.text);
}

function linesInto(into: HTMLElement, lines: MarkdownRun[][]): void {
    lines.forEach((runs, index) => {
        if (index > 0) {
            into.appendChild(el('br'));
        }
        runs.forEach((run) => into.appendChild(runElement(run)));
    });
}

/** A comment's text, as the elements it is shown as. */
export function renderMarkdown(text: string): HTMLElement {
    const body = el('div', 'comment-text');
    let list: HTMLElement | undefined;
    for (const block of parseMarkdown(text)) {
        if (block.kind === 'item' || block.kind === 'ordered') {
            const tag = block.kind === 'item' ? 'ul' : 'ol';
            if (list === undefined || list.tagName.toLowerCase() !== tag) {
                list = el(tag);
                // Steps 4 and 5 of something are shown as 4 and 5.
                if (block.number !== undefined && block.number !== 1) {
                    (list as HTMLOListElement).start = block.number;
                }
                body.appendChild(list);
            }
            const item = el('li');
            linesInto(item, block.lines);
            list.appendChild(item);
            continue;
        }
        list = undefined;
        if (block.kind === 'code') {
            body.appendChild(el('pre', 'comment-code', block.lines[0][0].text));
            continue;
        }
        const element = el(block.kind === 'heading' ? 'strong' : block.kind === 'quote' ? 'blockquote' : 'p');
        if (block.kind === 'heading') {
            element.className = 'comment-heading';
        }
        linesInto(element, block.lines);
        body.appendChild(element);
    }
    return body;
}

/** One comment, as a thread shows it: who and when, over what it says and what goes with it. */
export function renderComment(comment: CommentEntry): HTMLElement {
    const box = el('div', 'comment');
    const head = el('div', 'comment-head');
    head.appendChild(el('span', 'comment-name', comment.name || 'Somebody'));
    head.appendChild(el('span', 'comment-date', comment.date || ''));
    box.appendChild(head);
    box.appendChild(renderMarkdown(comment.text || ''));
    if (comment.attachments?.length) {
        const files = el('div', 'comment-attachments');
        for (const file of comment.attachments) {
            const item = el('span', 'comment-attachment', file);
            item.title = `Attached: ${file} (relative to the package)`;
            files.appendChild(item);
        }
        box.appendChild(files);
    }
    return box;
}

/** What a thread's callout heading says: what it is about, and on what. */
export function threadHeading(pin: Pick<ThreadPin, 'object' | 'thread'>): string {
    const object = pin.object.split(':').pop() || pin.object;
    const about = pin.thread.ref ? pin.thread.about || describeRef(pin.thread.ref) : 'the whole object';
    return `${about} · ${object}`;
}

/** The whole of a thread: its heading and every comment of it, oldest first. */
export function renderThread(pin: Pick<ThreadPin, 'object' | 'thread'>, into: HTMLElement): void {
    into.appendChild(el('div', 'callout-title', threadHeading(pin)));
    for (const comment of pin.thread.comments) {
        into.appendChild(renderComment(comment));
    }
}
