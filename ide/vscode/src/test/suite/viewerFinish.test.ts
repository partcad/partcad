//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// How a face whose CMF finish says how rough or how metallic it is gets drawn in
// the 3D view: 'finish.ts', which mirrors 'finished_light' in
// 'src/partcad/builtin/render/raster_scene.py'.
//
// What can be held here without a GPU is held: the Phong parameters a finish
// becomes, that a primitive's glTF material brings its finish and keeps it apart
// from one with none, and that the shader patch still finds the places in
// three's Phong shader it goes - so that a three upgrade that moves them fails
// here rather than drawing a finish without its reflection, silently. The
// constants' agreement with the Python side is held by a test there, which reads
// 'finish.ts' itself.
//

import * as assert from 'assert';
import * as THREE from 'three';

import {
    Appearance,
    DEFAULT_APPEARANCE,
    appearanceKey,
    ownAppearance,
    primitiveAppearance,
} from '../../webview/appearance';
import {
    ADDITION_ANCHOR,
    DECLARATION_ANCHOR,
    DIELECTRIC_F0,
    FINISH_EXTRAS,
    MAX_SHININESS,
    PLAIN_SHININESS,
    PLAIN_SPECULAR,
    TINT_ANCHOR,
    applyFinish,
    blinnPhong,
    finishStateOf,
    finishedPhong,
    parseFinish,
    prepareFinish,
    roomFresnel,
    setFinishShown,
    shininessOf,
    shownFinish,
    withRoomReflection,
} from '../../webview/finish';

function close(actual: number, expected: number, what: string, tolerance = 1e-6): void {
    assert.ok(Math.abs(actual - expected) <= tolerance, `${what}: ${actual} is not ${expected}`);
}

suite('How a finish is drawn', () => {
    test("the default roughness is three's own Phong shininess, and rougher is duller", () => {
        // 'raster_scene.shininess_of': 2 / r^4 - 2, 30 at 0.5.
        close(shininessOf(0.5), 30, 'shininess at 0.5');
        close(shininessOf(0.25), 2 / 0.25 ** 4 - 2, 'shininess at 0.25');
        assert.ok(shininessOf(0.2) > shininessOf(0.5) && shininessOf(0.5) > shininessOf(0.8));
        // Clamped as the shaded render clamps it: a mirror is not infinitely sharp,
        // and the roughest finish still has a highlight.
        assert.strictEqual(shininessOf(0), MAX_SHININESS);
        assert.strictEqual(shininessOf(1), 1);
    });

    test('a finish of the default roughness and no metal is lit as any other face, but for its specular', () => {
        const phong = finishedPhong(0xdaa520, { roughness: 0.5, metallic: 0 });
        const goldenrod = new THREE.Color(0xdaa520);
        assert.ok(phong.color.equals(goldenrod));
        close(phong.shininess, 30, 'shininess');
        // A dielectric's 0.04, where three's default is #111111.
        for (const channel of [phong.specular.r, phong.specular.g, phong.specular.b]) {
            close(channel, DIELECTRIC_F0, 'specular');
        }
    });

    test('metal has no diffuse colour and its specular is its colour', () => {
        const phong = finishedPhong(0xb87333, { roughness: 0.3, metallic: 1 });
        const copper = new THREE.Color(0xb87333);
        assert.deepStrictEqual([phong.color.r, phong.color.g, phong.color.b], [0, 0, 0]);
        close(phong.specular.r, copper.r, 'red');
        close(phong.specular.g, copper.g, 'green');
        close(phong.specular.b, copper.b, 'blue');

        // Half metal is half of each, in linear light.
        const half = finishedPhong(0xb87333, { roughness: 0.3, metallic: 0.5 });
        close(half.color.r, copper.r / 2, 'diffuse red');
        close(half.specular.g, DIELECTRIC_F0 / 2 + copper.g / 2, 'specular green');
    });

    test('a finish is two numbers from 0 to 1, and nothing else is one', () => {
        assert.deepStrictEqual(parseFinish({ roughness: 0.25, metallic: 1 }), { roughness: 0.25, metallic: 1 });
        assert.deepStrictEqual(parseFinish({ roughness: -1, metallic: 3 }), { roughness: 0, metallic: 1 });
        for (const junk of [undefined, null, 'shiny', 0.5, {}, { roughness: 0.5 }, { roughness: '0.5', metallic: 0 }]) {
            assert.strictEqual(parseFinish(junk), undefined, JSON.stringify(junk));
        }
        assert.strictEqual(parseFinish({ roughness: NaN, metallic: 0 }), undefined);
    });

    test('a primitive brings its finish with its colour, and is a look of its own', () => {
        // What 'wrapper_gltf._with_looks' writes for brushed red steel.
        const material = new THREE.MeshStandardMaterial({ color: 0xff0000 });
        material.userData.partcadColor = '#FF0000';
        material.userData[FINISH_EXTRAS] = { roughness: 0.25, metallic: 1 };

        const own = ownAppearance(material, true);
        const finish = { roughness: 0.25, metallic: 1 };
        assert.deepStrictEqual(own, { color: 0xff0000, opacity: 1, finish });
        const drawn = primitiveAppearance(own, DEFAULT_APPEARANCE);
        assert.deepStrictEqual(drawn, { color: 0xff0000, opacity: 1, finish });
        // Red polished and red with no finish are two materials.
        assert.notStrictEqual(appearanceKey(drawn), appearanceKey({ color: 0xff0000, opacity: 1 }));
        assert.notStrictEqual(
            appearanceKey(drawn),
            appearanceKey({ color: 0xff0000, opacity: 1, finish: { roughness: 0.8, metallic: 1 } }),
        );
        // And a one-sided wall of it is still one-sided.
        assert.deepStrictEqual(primitiveAppearance(own, { ...DEFAULT_APPEARANCE, oneSided: true }), {
            ...drawn,
            oneSided: true,
        });
        material.dispose();
    });

    test("a primitive with a finish and no colour of its own is in its node's colour", () => {
        // A set saying a finish and no colour: 'partcadColor' is null, and the base
        // colour is only the file's stand-in for a reader that knows no extras.
        const material = new THREE.MeshStandardMaterial({ color: 0xdaa520 });
        material.userData.partcadColor = null;
        material.userData[FINISH_EXTRAS] = { roughness: 0.8, metallic: 0 };

        const own = ownAppearance(material, true);
        assert.deepStrictEqual(own, { finish: { roughness: 0.8, metallic: 0 } });
        const node: Appearance = { color: 0x336699, opacity: 0.5, oneSided: true };
        assert.deepStrictEqual(primitiveAppearance(own, node), { ...node, finish: { roughness: 0.8, metallic: 0 } });
        material.dispose();
    });

    test('a primitive that says no finish is drawn as it always was', () => {
        const material = new THREE.MeshStandardMaterial({ color: 0xc91a09 });
        assert.deepStrictEqual(ownAppearance(material, true), { color: 0xc91a09, opacity: 1 });
        assert.strictEqual(appearanceKey({ color: 0xc91a09, opacity: 1 }), 'c91a09ff');
        material.dispose();
    });

    test("the room reflection still finds where it goes in three's Phong shader", () => {
        const phong = THREE.ShaderLib.phong.fragmentShader;
        const patched = withRoomReflection(phong);
        assert.ok(patched !== undefined, "three's Phong shader has moved the places the reflection goes");
        // Declared after three's light functions, the image's tint after the
        // Phong material sets its specular colour and before any light reads it,
        // and the reflection added once every light of three's has been.
        assert.ok(patched.indexOf(DECLARATION_ANCHOR) < patched.indexOf('vec3 partcadRoomReflection('));
        assert.ok(patched.indexOf(TINT_ANCHOR) < patched.indexOf('partcadMapMetal * ( sampledDiffuseColor'));
        assert.ok(
            patched.indexOf('partcadMapMetal * ( sampledDiffuseColor') < patched.indexOf('lights_fragment_begin'),
        );
        assert.ok(patched.indexOf(ADDITION_ANCHOR) < patched.indexOf('+= partcadRoomReflection('));
        assert.strictEqual(withRoomReflection('void main() {}'), undefined);

        // What the patch reads of three's: the lights' functions, and what its
        // light loop leaves in scope. Renamed in three, and this patch would not
        // compile, which only a GPU would say.
        const chunks = THREE.ShaderChunk as unknown as Record<string, string>;
        for (const name of [
            'getAmbientLightIrradiance',
            'getLightProbeIrradiance',
            'getHemisphereLightIrradiance',
            'getPointLightInfo',
            'getSpotLightInfo',
        ]) {
            assert.ok(chunks.lights_pars_begin.includes(name), name);
        }
        for (const name of ['geometryPosition', 'geometryNormal', 'geometryViewDir']) {
            assert.ok(chunks.lights_fragment_begin.includes(`vec3 ${name} =`), name);
        }
        assert.ok(chunks.lights_phong_fragment.includes('material.specularColor'));
        assert.ok(chunks.map_fragment.includes('vec4 sampledDiffuseColor ='));
    });

    test("a finished material is the viewer's Phong material, set as the finish says", () => {
        const material = new THREE.MeshPhongMaterial();
        const finish = { roughness: 0.25, metallic: 1 };
        applyFinish(material, 0xff0000, finish);

        assert.ok(material.color.equals(new THREE.Color(0, 0, 0)));
        assert.ok(material.specular.equals(new THREE.Color(0xff0000)));
        close(material.shininess, shininessOf(0.25), 'shininess');
        assert.deepStrictEqual(material.userData.finish, finish);

        // Its shader gets the reflection, with its roughness as a uniform, and
        // every finished material shares one program whatever its finish.
        const shader = {
            fragmentShader: THREE.ShaderLib.phong.fragmentShader,
            uniforms: {} as Record<string, THREE.IUniform>,
        };
        material.onBeforeCompile(shader as unknown as THREE.WebGLProgramParametersWithUniforms, undefined as never);
        assert.ok(shader.fragmentShader.includes('partcadRoomReflection('));
        assert.strictEqual(shader.uniforms.partcadRoughness.value, 0.25);
        assert.strictEqual(shader.uniforms.partcadRoomStrength.value, 1);
        assert.strictEqual(shader.uniforms.partcadMapMetal.value, 1);
        const other = new THREE.MeshPhongMaterial();
        applyFinish(other, 0x00ff00, { roughness: 0.9, metallic: 0 });
        assert.strictEqual(material.customProgramCacheKey(), other.customProgramCacheKey());
        assert.notStrictEqual(material.customProgramCacheKey(), new THREE.MeshPhongMaterial().customProgramCacheKey());
        material.dispose();
        other.dispose();
    });

    test('below 100% opacity a finish is drawn as the plain material of its colour, and is back at 100%', () => {
        const material = new THREE.MeshPhongMaterial();
        const state = applyFinish(material, 0xb87333, { roughness: 0.3, metallic: 1 });
        const shader = {
            fragmentShader: THREE.ShaderLib.phong.fragmentShader,
            uniforms: {} as Record<string, THREE.IUniform>,
        };
        material.onBeforeCompile(shader as unknown as THREE.WebGLProgramParametersWithUniforms, undefined as never);
        const program = material.customProgramCacheKey();

        setFinishShown(material, false);
        // three's Phong defaults, in the colour itself: any other face of it.
        assert.ok(material.color.equals(new THREE.Color(0xb87333)));
        assert.ok(material.specular.equals(new THREE.Color(PLAIN_SPECULAR)));
        assert.strictEqual(material.shininess, PLAIN_SHININESS);
        // The reflection and the image's tint off, in the uniforms the shader
        // already has: the same program, nothing compiled again.
        assert.strictEqual(shader.uniforms.partcadRoomStrength.value, 0);
        assert.strictEqual(shader.uniforms.partcadMapMetal.value, 0);
        assert.strictEqual(material.customProgramCacheKey(), program);
        assert.strictEqual(shownFinish(material), undefined);
        assert.strictEqual(finishStateOf(material), state);

        setFinishShown(material, true);
        assert.ok(material.color.equals(state.finished.color));
        assert.ok(material.specular.equals(state.finished.specular));
        assert.strictEqual(shader.uniforms.partcadRoomStrength.value, 1);
        assert.strictEqual(shownFinish(material), state);
        material.dispose();

        // A material with no finish is left alone.
        const plain = new THREE.MeshPhongMaterial({ color: 0x336699 });
        setFinishShown(plain, false);
        assert.ok(plain.color.equals(new THREE.Color(0x336699)));
        assert.strictEqual(shownFinish(plain), undefined);
        plain.dispose();
    });

    test('a face drawn with an image is white under it, and drawn as its colour where an image cannot be', () => {
        const material = new THREE.MeshPhongMaterial({ map: new THREE.Texture() });
        const state = prepareFinish(material, 0xffffff, { roughness: 0.3, metallic: 1 }, 0x781478);
        // On the GPU: no diffuse colour, the specular white - the image tints it.
        assert.ok(material.color.equals(new THREE.Color(0, 0, 0)));
        assert.ok(material.specular.equals(new THREE.Color(1, 1, 1)));
        // The painter, which draws no image: the finish on the flat colour.
        assert.ok(state.flat.specular.equals(new THREE.Color(0x781478)));
        // And with no image, the two are one.
        const bare = new THREE.MeshPhongMaterial();
        assert.strictEqual(
            prepareFinish(bare, 0x781478, { roughness: 0.3, metallic: 1 }).flat.specular.getHex(),
            0x781478,
        );
        material.map?.dispose();
        material.dispose();
        bare.dispose();
    });

    test('the room and a highlight are what the shaded render works out', () => {
        // 'raster_scene.finished_light' for f0 (0.5, 0.3, 0.1), roughness 0.3:
        // the room's Fresnel at dot(N, V) 0.4, damped; and one light's
        // Blinn-Phong at dot(N, H) 0.995 and dot(V, H) 0.8.
        const f0 = new THREE.Color(0.5, 0.3, 0.1);
        const room = roomFresnel(f0, 0.4, 0.3, new THREE.Color());
        close(room.r, 0.4382192, 'room red');
        close(room.g, 0.2814384, 'room green');
        close(room.b, 0.1246576, 'room blue');
        const highlight = blinnPhong(f0, shininessOf(0.3), 0.995, 0.8, new THREE.Color());
        close(highlight.r, 1.4417378823335387, 'highlight red', 1e-9);
        close(highlight.g, 0.8670812997238999, 'highlight green', 1e-9);
        close(highlight.b, 0.29242471711426105, 'highlight blue', 1e-9);
    });
});
