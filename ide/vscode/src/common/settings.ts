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
    return getConfiguration(namespace, scope).get<string>('installOnOpen') ?? 'true';
}

export function getReopenTerminalFromSetting(namespace: string, scope?: ConfigurationScope) {
    const config = getConfiguration(namespace, scope);
    return config.get<string>('reopenTerminal');
}

export function getAddToolsToTerminalPathFromSetting(namespace: string, scope?: ConfigurationScope): boolean {
    const config = getConfiguration(namespace, scope);
    return config.get<boolean>('addToolsToTerminalPath') ?? true;
}

export function getPopupTerminalFromSetting(namespace: string, scope?: ConfigurationScope) {
    const config = getConfiguration(namespace, scope);
    return config.get<string>('popupTerminal');
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
        `${namespace}.reopenTerminal`,
        `${namespace}.popupTerminal`,
    ];
    const changed = settings.map((s) => e.affectsConfiguration(s));
    return changed.includes(true);
}
