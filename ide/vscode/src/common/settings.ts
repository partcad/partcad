// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

import { ConfigurationChangeEvent, ConfigurationScope } from 'vscode';
import { getConfiguration } from './vscodeapi';

export function getServicePathFromSetting(namespace: string, scope?: ConfigurationScope): string {
    const config = getConfiguration(namespace, scope);
    return config.get<string>('servicePath') ?? '';
}

export function getServiceChannelFromSetting(namespace: string, scope?: ConfigurationScope): string {
    const config = getConfiguration(namespace, scope);
    return config.get<string>('serviceChannel') ?? 'socket';
}

export function getServiceDownloadRepositoryFromSetting(namespace: string, scope?: ConfigurationScope): string {
    const config = getConfiguration(namespace, scope);
    return config.get<string>('serviceDownloadRepository') ?? 'partcad/partcad';
}

export function getPackagePathFromSetting(namespace: string, scope?: ConfigurationScope) {
    const config = getConfiguration(namespace, scope);
    return config.get<string>('packagePath');
}

export function getInstallOnOpenFromSetting(namespace: string, scope?: ConfigurationScope) {
    // Agrees with the declared default in package.json. A second, contradicting
    // default here would only ever be reached if the contribution went missing,
    // and would then silently restore the behaviour that default turns off.
    return getConfiguration(namespace, scope).get<string>('installOnOpen') ?? 'false';
}

export function getReopenTerminalFromSetting(namespace: string, scope?: ConfigurationScope) {
    // Agrees with the declared default in package.json, for the reason given
    // for `installOnOpen` above.
    return getConfiguration(namespace, scope).get<string>('reopenTerminal') ?? 'false';
}

export function getAddToolsToTerminalPathFromSetting(namespace: string, scope?: ConfigurationScope): boolean {
    const config = getConfiguration(namespace, scope);
    return config.get<boolean>('addToolsToTerminalPath') ?? true;
}

export function getPopupTerminalFromSetting(namespace: string, scope?: ConfigurationScope) {
    const config = getConfiguration(namespace, scope);
    return config.get<string>('popupTerminal');
}

/**
 * What `partcad.develIndex` tells the service: `true` or `false`, or `undefined` for nothing at all.
 *
 * A settings file that sets it decides. Where none does, the answer depends on whether this runs from
 * sources, the way PartCAD's own default does: an extension running from its sources -- an Extension
 * Development Host, or its test host -- turns it on, and an installed one says nothing, which leaves it to
 * PartCAD: on where PartCAD runs from its sources (an editable install), off where it is a wheel or a
 * bundle. `package.json` cannot declare a default that depends on anything, so its `false` is what the
 * Settings editor shows rather than what an unset setting means.
 */
export function getDevelIndexFromSetting(
    namespace: string,
    extensionFromSources: boolean,
    scope?: ConfigurationScope,
): boolean | undefined {
    const config = getConfiguration(namespace, scope);
    const inspected = config.inspect<boolean>('develIndex');
    const stated = [inspected?.globalValue, inspected?.workspaceValue, inspected?.workspaceFolderValue].some(
        (value) => value !== undefined,
    );
    return develIndexFor(stated ? config.get<boolean>('develIndex') === true : undefined, extensionFromSources);
}

/** `getDevelIndexFromSetting` once the settings files have been read. Exported for the test suite. */
export function develIndexFor(stated: boolean | undefined, extensionFromSources: boolean): boolean | undefined {
    if (stated !== undefined) {
        return stated;
    }
    return extensionFromSources ? true : undefined;
}

export function getViewerPerformanceDebugFromSetting(namespace: string, scope?: ConfigurationScope): boolean {
    const config = getConfiguration(namespace, scope);
    return config.get<boolean>('viewer.performanceDebug') ?? false;
}

export function checkIfConfigurationChanged(e: ConfigurationChangeEvent, namespace: string): boolean {
    const settings = [
        `${namespace}.servicePath`,
        `${namespace}.serviceChannel`,
        `${namespace}.serviceDownloadRepository`,
        `${namespace}.pythonSandbox`,
        `${namespace}.telemetry`,
        `${namespace}.verbosity`,
        `${namespace}.packagePath`,
        `${namespace}.forceUpdate`,
        `${namespace}.installOnOpen`,
        `${namespace}.develIndex`,
        // `${namespace}.args`,
        `${namespace}.path`,
        `${namespace}.showNotifications`,
        // Not `reopenTerminal` or `popupTerminal`: the terminal views read them
        // on every write, so changing one needs no restart.
    ];
    const changed = settings.map((s) => e.affectsConfiguration(s));
    return changed.includes(true);
}
