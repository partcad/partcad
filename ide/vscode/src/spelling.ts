//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// PartCAD's words for Code Spell Checker, where it is installed.
//
// ASSY files and `partcad.yaml` are written in words no English dictionary has
// -- `assy`, `cadquery`, `connectPorts` -- and Code Spell Checker, which checks
// every language by default, underlined them in every file. It takes words from
// other extensions through its API: `registerConfig` adds a configuration file
// of the same shape as a `cspell.json`, which is how its own language
// dictionaries arrive. Ours (`cspell/cspell-ext.json`) defines one dictionary,
// generated from PartCAD's schemas, and gives it to the two languages this
// extension owns and to nothing else -- a typo in a `desc:` is still a typo.
//
// Optional both ways: nothing here needs the spell checker, and the spell
// checker does not need this. Registered whenever it turns up, including after
// this extension activated, and never more than once.
//

import * as path from 'path';
import * as vscode from 'vscode';
import { traceVerbose } from './common/log/logging';

export const CSPELL_EXTENSION_ID = 'streetsidesoftware.code-spell-checker';

/** What Code Spell Checker's `activate` returns, as much of it as is used here. */
type CSpellApi = { registerConfig?: (configPath: string) => void };

export function registerSpellingDictionary(context: vscode.ExtensionContext): void {
    const configPath = path.join(context.extensionPath, 'cspell', 'cspell-ext.json');
    let registered = false;
    const register = async () => {
        const cspell = vscode.extensions.getExtension<CSpellApi>(CSPELL_EXTENSION_ID);
        if (registered || cspell === undefined) {
            return;
        }
        registered = true;
        try {
            const api = cspell.isActive ? cspell.exports : await cspell.activate();
            if (typeof api?.registerConfig === 'function') {
                api.registerConfig(configPath);
            }
        } catch (e) {
            // A spell checker that will not take the words is not a reason to
            // stop anything else: it underlines them, as it did before.
            traceVerbose(`Code Spell Checker did not take PartCAD's dictionary: ${e}`);
        }
    };
    void register();
    // Installed, or enabled, after this extension activated.
    context.subscriptions.push(vscode.extensions.onDidChange(() => void register()));
}
