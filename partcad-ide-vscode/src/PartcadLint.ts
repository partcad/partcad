//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// Syntax and schema checking for ASSY files.
//
// An `.assy` file is registered as YAML so it gets syntax highlighting, but it
// is not YAML: it is a Jinja2 template that renders to YAML and then has to
// match the ASSY schema. A plain YAML checker therefore both misses the errors
// that matter (a mistyped `locaton:`, a location that is not an OCCT location)
// and invents errors that are not there (every `{% for %}` line).
//
// The check runs locally, never on the daemon: it is the client's own file --
// usually one this editor has not saved -- and it needs no package graph, no CAD
// runtime and no loaded context. `partcad.lintFile` is answered by whichever
// local PartCAD the active backend has (`pc lint --file` for the service
// backend, the bundled language server for the Python one), so it keeps
// answering when the daemon is down or the package will not load because of the
// very file being typed into.
//
// This class is the editor half: it decides when to ask, and turns the answer
// into diagnostics. The checking is `partcad_utils.assy_lint`, which masks the
// Jinja2 template before parsing so each finding still carries the line and
// column of the source file.
//

import * as vscode from 'vscode';
import { traceVerbose } from './common/log/logging';

// How long to wait after the last keystroke before re-checking. Long enough not
// to check a half-typed line on every character -- and, under the service
// backend, not to spawn a `pc` per character -- short enough that the squiggle
// still tracks what the user is doing.
const DEBOUNCE_MS = 500;

/** One finding, as `partcad_utils.assy_lint.Diagnostic.to_dict()` returns it. */
type LintDiagnostic = {
    severity: string;
    message: string;
    line: number;
    column: number;
    endLine: number;
    endColumn: number;
    source?: string;
    code?: string;
    path?: string;
};

type LintResult = {
    path: string;
    diagnostics: LintDiagnostic[];
};

function isAssyDocument(document: vscode.TextDocument): boolean {
    return document.uri.scheme === 'file' && document.uri.fsPath.toLowerCase().endsWith('.assy');
}

function isEnabled(): boolean {
    return vscode.workspace.getConfiguration('partcad').get<boolean>('lint.enabled', true);
}

export class PartcadLint implements vscode.Disposable {
    private readonly collection: vscode.DiagnosticCollection;
    private readonly disposables: vscode.Disposable[] = [];
    private readonly pending = new Map<string, ReturnType<typeof setTimeout>>();
    // Documents with a check in flight. A check can cost a process, so a second
    // one is never started beside the first; the edit that arrived meanwhile is
    // picked up by the re-check the first one queues on its way out.
    private readonly running = new Set<string>();

    constructor() {
        this.collection = vscode.languages.createDiagnosticCollection('partcad');
        this.disposables.push(
            this.collection,
            vscode.workspace.onDidOpenTextDocument((d) => this.schedule(d, 0)),
            vscode.workspace.onDidChangeTextDocument((e) => this.schedule(e.document, DEBOUNCE_MS)),
            vscode.workspace.onDidSaveTextDocument((d) => this.schedule(d, 0)),
            vscode.workspace.onDidCloseTextDocument((d) => this.forget(d)),
            vscode.workspace.onDidChangeConfiguration((e) => {
                if (e.affectsConfiguration('partcad.lint.enabled')) {
                    this.refresh();
                }
            }),
        );
    }

    /**
     * Re-check every open ASSY file. Called once the backend is up: documents
     * opened before that were checked against a command that did not exist yet.
     */
    public refresh(): void {
        if (!isEnabled()) {
            this.collection.clear();
            return;
        }
        for (const document of vscode.workspace.textDocuments) {
            this.schedule(document, 0);
        }
    }

    public dispose(): void {
        for (const timer of this.pending.values()) {
            clearTimeout(timer);
        }
        this.pending.clear();
        this.disposables.forEach((d) => d.dispose());
        this.disposables.length = 0;
    }

    private forget(document: vscode.TextDocument): void {
        const key = document.uri.toString();
        const timer = this.pending.get(key);
        if (timer !== undefined) {
            clearTimeout(timer);
            this.pending.delete(key);
        }
        this.collection.delete(document.uri);
    }

    private schedule(document: vscode.TextDocument, delay: number): void {
        if (!isAssyDocument(document)) {
            return;
        }
        if (!isEnabled()) {
            this.collection.delete(document.uri);
            return;
        }
        const key = document.uri.toString();
        const previous = this.pending.get(key);
        if (previous !== undefined) {
            clearTimeout(previous);
        }
        this.pending.set(
            key,
            setTimeout(() => {
                this.pending.delete(key);
                void this.check(document);
            }, delay),
        );
    }

    private async check(document: vscode.TextDocument): Promise<void> {
        const key = document.uri.toString();
        if (this.running.has(key)) {
            this.schedule(document, DEBOUNCE_MS);
            return;
        }
        this.running.add(key);
        // The buffer is sent along with the path: the point of checking while
        // typing is to report what is on screen, not what was last saved.
        const version = document.version;
        let result: LintResult | undefined;
        try {
            result = await vscode.commands.executeCommand<LintResult>('partcad.lintFile', {
                path: document.uri.fsPath,
                text: document.getText(),
            });
        } catch (e) {
            // No backend yet, no local PartCAD to run, or one too old to know
            // the command. Leave whatever is already shown alone and try again
            // next time.
            traceVerbose(`Failed to check ${document.uri.fsPath}: ${e}`);
            return;
        } finally {
            this.running.delete(key);
        }
        if (document.version !== version) {
            // The document moved on while the check was running. Do not publish
            // findings about text that is no longer there; check again instead.
            this.schedule(document, 0);
            return;
        }
        if (!isEnabled() || document.isClosed) {
            // Checking was turned off, or the document was closed, while this
            // check was in flight: `refresh()` and `forget()` have already
            // cleared what was shown, and publishing now would put it back.
            return;
        }
        this.collection.set(document.uri, (result?.diagnostics ?? []).map(toDiagnostic));
    }
}

function toDiagnostic(finding: LintDiagnostic): vscode.Diagnostic {
    const range = new vscode.Range(
        Math.max(0, finding.line),
        Math.max(0, finding.column),
        Math.max(0, finding.endLine),
        Math.max(0, finding.endColumn),
    );
    const severity =
        finding.severity === 'warning' ? vscode.DiagnosticSeverity.Warning : vscode.DiagnosticSeverity.Error;
    const diagnostic = new vscode.Diagnostic(range, finding.message, severity);
    diagnostic.source = 'PartCAD';
    if (finding.code) {
        diagnostic.code = finding.code;
    }
    return diagnostic;
}
