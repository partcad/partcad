//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The part types "Add part" offers, and the files each one is chosen from.
//
// The command ends in `add.object`, which is what `pc add part <type> <file>`
// sends, so every `kind` here is one of that command's `PART_KINDS`. Which
// extensions a type's files have is PartCAD's to say (`partcad_client.object_types`,
// with the other spellings PartCAD itself names its objects by,
// `partcad.shape.PART_EXTENSION_ALIASES`): this is a copy of it, the only one in
// the extension, and `tests/partcad_client/test_vscode_part_types.py` reads this
// file and fails when the two disagree -- a type `pc add part` takes and the
// picker does not offer, or an extension the dialog would hide.
//
// Kept free of `vscode` so that the table and the filters are tested as they
// are, without a window.
//

/** One entry of the "Add part" picker. */
export interface PartTypeChoice {
    /** What the picker shows, and the key of the type's templates in `examples.ts`. */
    label: string;
    /** The part's `type`, as `pc add part` takes it. */
    kind: string;
    /** Every extension a file of the type is stored in, the one PartCAD declares first, spelled as it does. */
    extensions: string[];
    /** A script, which may be a new file started from a template rather than a file the package has. */
    template?: boolean;
}

// One entry per line, as the test reads them.
// prettier-ignore
export const PART_TYPE_CHOICES: PartTypeChoice[] = [
    { label: 'STEP', kind: 'step', extensions: ['step', 'stp'] },
    { label: 'BREP', kind: 'brep', extensions: ['brep'] },
    { label: 'IGES', kind: 'iges', extensions: ['iges', 'igs'] },
    { label: 'STL', kind: 'stl', extensions: ['stl'] },
    { label: '3MF', kind: '3mf', extensions: ['3mf'] },
    { label: 'OBJ', kind: 'obj', extensions: ['obj'] },
    { label: 'glTF', kind: 'gltf', extensions: ['gltf', 'glb'] },
    { label: 'FreeCAD', kind: 'fcstd', extensions: ['FCStd'] },
    { label: 'Autodesk Fusion', kind: 'f3d', extensions: ['f3d'] },
    { label: 'SolidWorks', kind: 'sldprt', extensions: ['SLDPRT'] },
    { label: 'Autodesk Inventor', kind: 'ipt', extensions: ['ipt'] },
    { label: 'CATIA V5', kind: 'catpart', extensions: ['CATPart'] },
    { label: 'ACIS / ShapeManager', kind: 'sat', extensions: ['sat', 'sab', 'smb', 'smt'] },
    { label: 'Creo View', kind: 'pvz', extensions: ['pvz'] },
    { label: 'OpenUSD', kind: 'usd', extensions: ['usd', 'usda', 'usdc', 'usdz'] },
    { label: 'OpenSCAD', kind: 'scad', extensions: ['scad'], template: true },
    { label: 'CadQuery', kind: 'cadquery', extensions: ['py'], template: true },
    { label: 'build123d', kind: 'build123d', extensions: ['py'], template: true },
    { label: 'SDF', kind: 'sdf', extensions: ['py'], template: true },
    { label: 'Chili3D', kind: 'chili3d', extensions: ['chili'], template: true },
];

/** The entry the picker shows as ``label``; undefined for anything else. */
export function partTypeChoice(label: string): PartTypeChoice | undefined {
    return PART_TYPE_CHOICES.find((choice) => choice.label === label);
}

/** What the picker says beside a type: the extensions it is chosen from, `.step, .stp`. */
export function partTypeDescription(choice: PartTypeChoice): string {
    return choice.extensions.map((extension) => `.${extension}`).join(', ');
}

/**
 * The file dialog's filter for ``choice``: every extension of the type, each as
 * PartCAD spells it, lowercased and uppercased.
 *
 * Every case because whether a dialog matches an extension without regard to
 * case is the dialog's business, and they differ: the one VS Code draws itself
 * -- in a remote window, or with `files.simpleDialog.enable` -- keeps a file
 * only when its path `endsWith('.' + extension)`, as written (`filterFile` in
 * its simple file dialog), while an operating system's own dialog may fold
 * case. A SolidWorks file is `.SLDPRT` as often as `.sldprt`, and a dialog that
 * hides the one a user has is a part they cannot add. A duplicate costs nothing
 * where the dialog folds case, so all three are listed everywhere.
 */
export function partTypeFilters(choice: PartTypeChoice): { [name: string]: string[] } {
    const extensions: string[] = [];
    for (const extension of choice.extensions) {
        for (const spelling of [extension, extension.toLowerCase(), extension.toUpperCase()]) {
            if (!extensions.includes(spelling)) {
                extensions.push(spelling);
            }
        }
    }
    return { [choice.label]: extensions };
}
