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
