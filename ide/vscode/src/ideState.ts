/*
 * PartCAD, 2026
 *
 * Licensed under Apache License, Version 2.0.
 */

/**
 * What this window is showing, for `pc ide state`.
 *
 * Three views, one document: the PartCAD Explorer's selection, the PartCAD
 * Inspector's object, and the PartCAD Viewer's tabs, filters, selections and a
 * screenshot. The shape is specified once, beside `MSG_STATE` in
 * `src/partcad_ide_client/protocol.py`; this collects it, and the viewer
 * server sends it back over the socket `pc` asked on.
 *
 * Each view is asked on its own and a view that fails says so in its own entry,
 * rather than failing the whole answer: a screenshot that could not be taken is
 * no reason not to say what is selected.
 */

import * as vscode from 'vscode';
import { ITEM_TYPE_PACKAGE } from './PartcadItem';

/** One selected row of the Explorer, as the state reports it. */
export interface ExplorerEntry {
    kind: string;
    /** The full path: `<package>:<object>`, or the package's own path for a package. */
    path: string;
    package: string;
    name: string;
    /** What the object is declared as (`cadquery`, `step`, `assy`, ...), where it says. */
    type: string | null;
    /** The file the object is read from, where it has one. */
    file: string | null;
}

/** The fields of an Explorer item the state reads; the item itself is a `PartcadItem`. */
export interface ExplorerItemLike {
    name: string;
    pkg: string;
    itemType: string;
    itemPath?: string;
    config?: { type?: string };
}

/** One Explorer row, as data. Pure, so that it is tested without a window. */
export function explorerEntry(item: ExplorerItemLike): ExplorerEntry {
    const isPackage = item.itemType === ITEM_TYPE_PACKAGE;
    return {
        kind: item.itemType,
        path: isPackage ? item.name : `${item.pkg}:${item.name}`,
        package: isPackage ? item.name : item.pkg,
        name: item.name,
        type: item.config?.type ?? null,
        file: item.itemPath ?? null,
    };
}

/** What a view that could not answer contributes: why, in its own entry. */
export function failed(error: unknown): { error: string } {
    return { error: error instanceof Error ? error.message : String(error) };
}

export interface StateSources {
    explorer: vscode.TreeView<ExplorerItemLike> | undefined;
    inspector: { state(): Promise<unknown> } | undefined;
    viewer: { state(): Promise<unknown> } | undefined;
    extensionVersion: string;
}

/** The whole answer to `pc ide state`. */
export async function collectIdeState(sources: StateSources): Promise<Record<string, unknown>> {
    const ask = async (view: { state(): Promise<unknown> } | undefined) => {
        if (view === undefined) {
            return null;
        }
        try {
            return await view.state();
        } catch (error) {
            return failed(error);
        }
    };
    // Asked at once: both are a round trip to a webview, and the screenshot is
    // the slow one.
    const [inspector, viewer] = await Promise.all([ask(sources.inspector), ask(sources.viewer)]);
    return {
        window: {
            pid: process.pid,
            workspaceFolders: (vscode.workspace.workspaceFolders ?? []).map((folder) => folder.uri.fsPath),
            extensionVersion: sources.extensionVersion,
        },
        explorer: { selection: (sources.explorer?.selection ?? []).map(explorerEntry) },
        inspector,
        viewer,
    };
}
