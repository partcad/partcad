import * as vscode from 'vscode';
import path = require('path');

function joinPath(uri: vscode.Uri, ...pathFragment: string[]): vscode.Uri {
    // Reimplementation of
    // https://github.com/microsoft/vscode/blob/b251bd952b84a3bdf68dad0141c37137dac55d64/src/vs/base/common/uri.ts#L346-L357
    // with Node.JS path. This is a temporary workaround for https://github.com/eclipse-theia/theia/issues/8752.
    if (!uri.path) {
        throw new Error('[UriError]: cannot call joinPaths on URI without path');
    }
    return uri.with({ path: vscode.Uri.file(path.join(uri.fsPath, ...pathFragment)).path });
}

export { joinPath };
