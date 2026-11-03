//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The types "Add part" offers and the files its dialog lists for each. Which
// types and extensions there are is held to PartCAD's own tables on the Python
// side (`tests/partcad_client/test_vscode_part_types.py`); this is what the
// command makes of them.
//

import * as assert from 'assert';

import { examples } from '../../examples';
import { PART_TYPE_CHOICES, partTypeChoice, partTypeDescription, partTypeFilters } from '../../partTypes';

function filterOf(label: string): string[] {
    const choice = partTypeChoice(label);
    assert.ok(choice, label);
    return partTypeFilters(choice)[label];
}

suite('Add part: the types offered', () => {
    test('the native CAD formats are offered as the types `pc add part` takes', () => {
        const kinds = Object.fromEntries(PART_TYPE_CHOICES.map((choice) => [choice.label, choice.kind]));
        assert.deepStrictEqual(
            [
                kinds['FreeCAD'],
                kinds['Autodesk Fusion'],
                kinds['SolidWorks'],
                kinds['Autodesk Inventor'],
                kinds['CATIA V5'],
                kinds['ACIS / ShapeManager'],
                kinds['Creo View'],
                kinds['IGES'],
            ],
            ['fcstd', 'f3d', 'sldprt', 'ipt', 'catpart', 'sat', 'pvz', 'iges'],
        );
    });

    test('so are the files PartCAD reads that the picker used to leave out', () => {
        assert.strictEqual(partTypeChoice('BREP')?.kind, 'brep');
        assert.strictEqual(partTypeChoice('OBJ')?.kind, 'obj');
        assert.strictEqual(partTypeChoice('glTF')?.kind, 'gltf');
    });

    test('every label is one entry, and only the picker labels are found', () => {
        const labels = PART_TYPE_CHOICES.map((choice) => choice.label);
        assert.strictEqual(new Set(labels).size, labels.length);
        assert.strictEqual(partTypeChoice('Rhino'), undefined);
    });

    test('a type started from a template has templates', () => {
        // The command opens `examples[label]` for a script file that does not exist yet.
        for (const choice of PART_TYPE_CHOICES.filter((c) => c.template)) {
            assert.ok(Object.keys(examples[choice.label] ?? {}).length > 0, choice.label);
        }
    });

    test('a file the package has is chosen, never created, for every other type', () => {
        for (const label of ['STEP', 'FreeCAD', 'SolidWorks', 'ACIS / ShapeManager', 'Creo View']) {
            assert.notStrictEqual(partTypeChoice(label)?.template, true, label);
        }
    });

    test('the picker says which files each type is chosen from', () => {
        assert.strictEqual(partTypeDescription(partTypeChoice('IGES')!), '.iges, .igs');
        assert.strictEqual(partTypeDescription(partTypeChoice('CATIA V5')!), '.CATPart');
    });
});

suite('Add part: the file dialog', () => {
    test('every extension of a type is listed', () => {
        assert.deepStrictEqual(filterOf('STEP'), ['step', 'STEP', 'stp', 'STP']);
        assert.deepStrictEqual(filterOf('IGES'), ['iges', 'IGES', 'igs', 'IGS']);
        assert.deepStrictEqual(filterOf('ACIS / ShapeManager'), [
            'sat',
            'SAT',
            'sab',
            'SAB',
            'smb',
            'SMB',
            'smt',
            'SMT',
        ]);
        assert.deepStrictEqual(filterOf('glTF'), ['gltf', 'GLTF', 'glb', 'GLB']);
    });

    test('a mixed-case extension is listed as declared, lowercased and uppercased', () => {
        // A dialog that compares extensions as written would otherwise hide
        // 'bracket.sldprt' behind 'SLDPRT', or 'design.FCStd' behind 'fcstd'.
        assert.deepStrictEqual(filterOf('FreeCAD'), ['FCStd', 'fcstd', 'FCSTD']);
        assert.deepStrictEqual(filterOf('SolidWorks'), ['SLDPRT', 'sldprt']);
        assert.deepStrictEqual(filterOf('CATIA V5'), ['CATPart', 'catpart', 'CATPART']);
    });

    test('the filter is named after the type', () => {
        const choice = partTypeChoice('Creo View')!;
        assert.deepStrictEqual(Object.keys(partTypeFilters(choice)), ['Creo View']);
    });
});
