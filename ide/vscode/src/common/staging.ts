//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// Building an assembly in two phases, from the client's side of it.
//
// A service asked for an assembly whose sub-assemblies are not cached yet does
// no work and answers RETRY_LATER, naming them. The client builds each one --
// through `assembly.instantiate`, with `cacheOnly`, so the geometry stays on
// the service -- and asks again, which now finds them cached. Nesting needs
// nothing extra: a staging request is an assembly request and can be answered
// the same way.
//
// `src/partcad_utils/staging.py` is where this protocol is defined, and the
// Python client reads these values from it. This is the one place the extension
// restates them, because the extension speaks JSON-RPC itself; keep the two in
// step.
//

/** The JSON-RPC error code for "not yet -- build these first". */
export const RETRY_LATER = -32004;

/** The method that builds one assembly and leaves the result on the service. */
export const INSTANTIATE_METHOD = 'assembly.instantiate';

/** One assembly the service wants built before it will do the asked-for work. */
export interface PendingSubassembly {
    package?: string;
    name: string;
    /**
     * Which of the two it is. A scene is an assembly -- the same files, the
     * same tree -- but a package registers the two apart, so an entry that did
     * not say which it is would be looked for among the assemblies and not
     * found. Absent means "assembly".
     */
    kind?: string;
}

/**
 * What the service wants built before it will do this work, or nothing.
 *
 * Answers for any error, not only this one, so a caller can ask without first
 * deciding what it is looking at. Anything malformed reads as nothing: an error
 * nobody can act on is an error to report, and an empty list is what makes the
 * caller report it.
 */
export function pendingSubassemblies(code: unknown, data: unknown): PendingSubassembly[] {
    if (code !== RETRY_LATER || typeof data !== 'object' || data === null) {
        return [];
    }
    const items = (data as { subassemblies?: unknown }).subassemblies;
    if (!Array.isArray(items)) {
        return [];
    }
    return items.filter(
        (item): item is PendingSubassembly =>
            typeof item === 'object' && item !== null && typeof (item as PendingSubassembly).name === 'string',
    );
}

/**
 * How one entry is named -- for a message, and for not building it twice.
 *
 * The kind is part of it: a package may declare an assembly and a scene of one
 * name, and they are two objects.
 */
export function identity(item: PendingSubassembly): string {
    const name = `${item.package ?? ''}:${item.name ?? ''}`;
    const kind = item.kind ?? 'assembly';
    return kind === 'assembly' ? name : `${name} (${kind})`;
}

/** The params of the request that builds one entry. */
export function requestParams(item: PendingSubassembly, context?: unknown): Record<string, unknown> {
    const params: Record<string, unknown> = {
        package: item.package,
        name: item.name,
        kind: item.kind ?? 'assembly',
        cacheOnly: true,
    };
    if (context !== undefined) {
        params.context = context;
    }
    return params;
}
