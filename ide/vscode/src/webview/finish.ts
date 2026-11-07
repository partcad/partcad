//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// How a face whose CMF finish says how rough or how metallic it is gets drawn in
// the 3D view (docs/design/cmf.md, section 9).
//
// PartCAD writes such a face's primitive with the finish in its material's
// 'extras', as 'partcadFinish: {roughness, metallic}' with the defaults filled in
// ('wrapper_gltf._with_looks'). Every other face says nothing, and is drawn with
// the viewer's Phong material exactly as before.
//
// A finished face is drawn as a shaded 'pc render' draws it -
// 'finished_light' in 'src/partcad/builtin/render/raster_scene.py', under the
// same lights ('ROOM_LIGHT' in 'scene.ts', and the rig beside it) - and so as
// three's Phong material, which is what that function was written against:
//
//   * its highlights as sharp as it is smooth: Blinn-Phong with shininess
//     '2 / r^4 - 2' ('shininessOf'), which is three's own 30 at a roughness of
//     0.5, so that a finish of the default roughness lights like any other face;
//   * tinted by its colour as far as it is metal: the specular colour is the
//     0.04 a dielectric reflects at normal incidence, blended into the colour by
//     the metalness - what the Phong material calls 'specular', where every
//     other face has three's #111111;
//   * its diffuse light what is no metal of it: the colour times '1 - metallic';
//   * on an image, tinted by the image's colour where it is metal, as a shaded
//     'pc render' tints it ('raster_scene._textured'): the specular colour
//     there is the dielectric's blended into the image's colour at that point,
//     rather than into the white the image is laid on;
//   * and the room reflected ('roomFresnel'): the light that falls from the way
//     the camera is mirrored, by Schlick's Fresnel, damped by the roughness -
//     every light the face is lit by, evaluated along the mirrored direction
//     rather than the normal, as 'finished_light' evaluates 'diffuse'.
//
// The first three are the Phong material's own parameters. The fourth is not
// something three's Phong material has, so each renderer is given it its own
// way, from the one formula:
//
//   * WebGL: a patch to the Phong shader ('ROOM_REFLECTION', 'onBeforeCompile'),
//     reading the lights the shader already has;
//   * WebGPU: a lighting model of its own, 'finishNode.ts', which three's node
//     materials take in place of a shader patch;
//   * the canvas painter ('painter.ts'): the same arithmetic on the CPU, per
//     triangle, with the lights the painter draws with ('paintFinished').
//
// **A finish is shown only when the model is drawn solid.** The Opacity slider
// below 100% draws every finished face as the plain material any other face of its
// colour is drawn with ('setFinishShown'): a see-through model is for seeing what
// is inside it, and a half-transparent metal - black where it is no diffuse colour
// and bright where it reflects the room - says the opposite of what is behind it.
// A colour that is see-through of itself ('#RRGGBBAA': glass) keeps its finish,
// since that is how the thing looks. So does everything a CMF set is chosen
// against: the faces left out are drawn plain and faint ('scene.ts').
//
// MeshStandardMaterial was the other way to do it, and was not taken: it is
// lit by a different model (GGX highlights, energy-conserving diffuse) from the
// Phong faces beside it, and its reflection reads 'scene.environment', which
// this view does not have (see the light probe in 'scene.ts'). A finished face
// would then look different from an unfinished one of the same colour even at
// the default roughness and no metal, which is the one case where the two must
// look the same.
//
// Only three's core is imported here, so the extension host's tests can import
// it (see 'viewerFinish.test.ts').
//

import * as THREE from 'three';

/** How rough and how metallic a face looks, each from 0 to 1. */
export interface Finish {
    readonly roughness: number;
    readonly metallic: number;
}

/**
 * The share of the light a surface that is no metal reflects at normal
 * incidence: 'raster_scene.DIELECTRIC_F0'.
 */
export const DIELECTRIC_F0 = 0.04;

/** The sharpest highlight a smooth finish is drawn with: 'raster_scene.MAX_SHININESS'. */
export const MAX_SHININESS = 2048;

/** What three's Phong material draws every face without a finish with: its defaults. */
export const PLAIN_SPECULAR = 0x111111;
export const PLAIN_SHININESS = 30;

/**
 * The extras key a glTF material says its finish under
 * ('wrapper_gltf._with_looks').
 */
export const FINISH_EXTRAS = 'partcadFinish';

/**
 * The finish a glTF material's extras say, or undefined where they say none.
 *
 * Both numbers or nothing: PartCAD writes both, with the defaults for what the
 * finish leaves unsaid, and anything else is not a finish this view can draw.
 */
export function parseFinish(value: unknown): Finish | undefined {
    if (typeof value !== 'object' || value === null) {
        return undefined;
    }
    const { roughness, metallic } = value as { roughness?: unknown; metallic?: unknown };
    if (typeof roughness !== 'number' || typeof metallic !== 'number') {
        return undefined;
    }
    if (!Number.isFinite(roughness) || !Number.isFinite(metallic)) {
        return undefined;
    }
    return { roughness: clamp(roughness), metallic: clamp(metallic) };
}

function clamp(value: number): number {
    return Math.min(1, Math.max(0, value));
}

/**
 * The Blinn-Phong shininess that draws a highlight as rough as 'roughness':
 * 'raster_scene.shininess_of'.
 *
 * '2 / alpha^2 - 2' with alpha the square of the roughness, as a GGX highlight
 * is approximated by a Phong one: 30 at 0.5, three's Phong default.
 */
export function shininessOf(roughness: number): number {
    const alpha = Math.max(roughness, 0.05) ** 2;
    return Math.min(MAX_SHININESS, Math.max(1, 2 / (alpha * alpha) - 2));
}

/** What a Phong material is given to draw a face: each colour in three's linear working space. */
export interface PhongLook {
    /** The diffuse colour. */
    readonly color: THREE.Color;
    readonly specular: THREE.Color;
    readonly shininess: number;
}

/**
 * The Phong parameters that draw 'finish' on a surface of 'albedo', 0xRRGGBB in
 * sRGB: white for one drawn with an image, as 'raster_scene.Scene' takes it.
 *
 * The diffuse colour is the albedo times what is no metal of it; the specular
 * colour the dielectric's 0.04 blended into the albedo by the metalness.
 */
export function finishedPhong(albedo: number, finish: Finish): PhongLook {
    const linear = new THREE.Color().setHex(albedo, THREE.SRGBColorSpace);
    const dielectric = DIELECTRIC_F0 * (1 - finish.metallic);
    return {
        color: linear.clone().multiplyScalar(1 - finish.metallic),
        specular: new THREE.Color(
            dielectric + linear.r * finish.metallic,
            dielectric + linear.g * finish.metallic,
            dielectric + linear.b * finish.metallic,
        ),
        shininess: shininessOf(finish.roughness),
    };
}

/** The Phong parameters of a face of 'albedo' drawn without its finish: three's defaults. */
export function plainPhong(albedo: number): PhongLook {
    return {
        color: new THREE.Color().setHex(albedo, THREE.SRGBColorSpace),
        specular: new THREE.Color().setHex(PLAIN_SPECULAR, THREE.SRGBColorSpace),
        shininess: PLAIN_SHININESS,
    };
}

/**
 * How much of the room's light, falling from the mirrored view direction, a
 * finished surface sends back towards the camera: per colour channel, into
 * 'into'.
 *
 * The second half of 'finished_light': Schlick's Fresnel with 'f0' the specular
 * colour, towards 'max(1 - roughness, f0)' at a glance, damped as the surface is
 * rough - times the irradiance from that direction over pi in three's
 * arithmetic, or times it alone in the painter's, whose Lambert term has no pi
 * either. The shaders spell the same formula in GLSL ('ROOM_REFLECTION') and TSL
 * ('finishNode.ts'); a test holds the three to agree.
 */
export function roomFresnel(f0: THREE.Color, dotNV: number, roughness: number, into: THREE.Color): THREE.Color {
    const strongest = Math.max(f0.r, f0.g, f0.b);
    const glance = Math.max(1 - roughness, strongest);
    const towards = Math.pow(1 - clamp(dotNV), 5);
    const damping = 1 - 0.5 * roughness;
    return into.setRGB(
        (f0.r + (glance - f0.r) * towards) * damping,
        (f0.g + (glance - f0.g) * towards) * damping,
        (f0.b + (glance - f0.b) * towards) * damping,
    );
}

/**
 * three's 'BRDF_BlinnPhong' for one light: Schlick's Fresnel of 'f0' at the half
 * vector, the implicit 0.25, and the normalised Blinn-Phong lobe - into 'into'.
 * What the painter adds per light for a finished face ('painter.ts').
 */
export function blinnPhong(
    f0: THREE.Color,
    shininess: number,
    dotNH: number,
    dotVH: number,
    into: THREE.Color,
): THREE.Color {
    const fresnel = Math.pow(2, (-5.55473 * dotVH - 6.98316) * dotVH);
    const lobe = 0.25 * ((shininess * 0.5 + 1) / Math.PI) * Math.pow(Math.max(0, dotNH), shininess);
    return into.setRGB(
        (f0.r * (1 - fresnel) + fresnel) * lobe,
        (f0.g * (1 - fresnel) + fresnel) * lobe,
        (f0.b * (1 - fresnel) + fresnel) * lobe,
    );
}

/**
 * What a finished material holds beyond a Phong material's own parameters: the
 * finish, the two looks it switches between, and the uniforms its room
 * reflection reads - shared by reference with the renderer's shader, so that
 * switching the finish off is a change of values and not of program.
 */
export interface FinishState {
    readonly finish: Finish;
    readonly finished: PhongLook;
    readonly plain: PhongLook;
    /**
     * The finish on the colour a face drawn with an image is drawn as where an
     * image cannot be: what the canvas painter, which draws no image, lights it
     * with. 'finished' itself for a face with no image.
     */
    readonly flat: PhongLook;
    /** The roughness the room's reflection is damped by. */
    readonly roughness: { value: number };
    /** 1 while the finish is shown, 0 while the face is drawn plain. */
    readonly strength: { value: number };
    /**
     * How far an image's colour tints the specular colour, where the face is
     * drawn with one: the metalness while the finish is shown, 0 while not.
     */
    readonly mapMetal: { value: number };
}

/** The values a finished material's shader reads that are not a Phong material's own. */
export type FinishUniform = 'roughness' | 'strength' | 'mapMetal';

const states = new WeakMap<THREE.Material, FinishState>();

/** The finish 'material' was made to draw, shown or not; undefined for every other material. */
export function finishStateOf(material: THREE.Material): FinishState | undefined {
    return states.get(material);
}

/** The finish 'material' draws now: undefined where it has none, or it is drawn plain. */
export function shownFinish(material: THREE.Material): FinishState | undefined {
    const state = states.get(material);
    return state !== undefined && state.strength.value > 0 ? state : undefined;
}

/**
 * Make 'material' a finished one, shown: its diffuse colour, specular colour and
 * shininess from the finish, and the state its renderer's room reflection reads.
 * 'albedo' is 0xRRGGBB in sRGB, white for a face drawn with an image, and
 * 'flat' what such a face is drawn as where an image cannot be (the albedo for
 * any other). 'userData.finish' says it is finished, in plain data.
 */
export function prepareFinish(
    material: THREE.MeshPhongMaterial,
    albedo: number,
    finish: Finish,
    flat: number = albedo,
    uniform: (name: FinishUniform, value: number) => { value: number } = (_name, value) => ({ value }),
): FinishState {
    const finished = finishedPhong(albedo, finish);
    const state: FinishState = {
        finish,
        finished,
        plain: plainPhong(albedo),
        flat: flat === albedo ? finished : finishedPhong(flat, finish),
        roughness: uniform('roughness', finish.roughness),
        strength: uniform('strength', 1),
        mapMetal: uniform('mapMetal', finish.metallic),
    };
    states.set(material, state);
    material.userData.finish = finish;
    setFinishShown(material, true);
    return state;
}

/**
 * Draw 'material' with its finish, or as the plain material of its colour.
 *
 * The same program either way - the room's reflection is scaled by a uniform -
 * so the Opacity slider can switch every finish in a show on every frame it
 * moves without three building a shader. A material without a finish is left
 * alone.
 */
export function setFinishShown(material: THREE.Material, shown: boolean): void {
    const state = states.get(material);
    if (state === undefined) {
        return;
    }
    const phong = material as THREE.MeshPhongMaterial;
    const look = shown ? state.finished : state.plain;
    phong.color.copy(look.color);
    phong.specular.copy(look.specular);
    phong.shininess = look.shininess;
    state.strength.value = shown ? 1 : 0;
    state.mapMetal.value = shown ? state.finish.metallic : 0;
}

/** Where 'ROOM_REFLECTION' is declared: after the Phong material's light functions. */
export const DECLARATION_ANCHOR = '#include <lights_phong_pars_fragment>';
/** Where the image's colour tints the specular: once the Phong material has set it, before any light reads it. */
export const TINT_ANCHOR = '#include <lights_phong_fragment>';
/** Where it is added to the light: once three has added every light of its own. */
export const ADDITION_ANCHOR = '#include <lights_fragment_end>';

/**
 * The room as a finished surface reflects it, in GLSL: 'roomFresnel' times the
 * irradiance from the mirrored view direction, over pi.
 *
 * Every light the shader has, evaluated along the mirrored view direction - the
 * irradiance a surface facing that way would receive, which is 'diffuse' of the
 * mirrored direction there. 'surfacePosition', 'surfaceNormal' and 'viewDir' are
 * in view space, as three's own light loop has them.
 */
export const ROOM_REFLECTION = /* glsl */ `
uniform float partcadRoughness;
uniform float partcadRoomStrength;
uniform float partcadMapMetal;

vec3 partcadRoomReflection( const in vec3 surfacePosition, const in vec3 surfaceNormal, const in vec3 viewDir, const in vec3 f0 ) {
	float dotNV = saturate( dot( surfaceNormal, viewDir ) );
	vec3 mirrored = 2.0 * dotNV * surfaceNormal - viewDir;
	vec3 roomIrradiance = getAmbientLightIrradiance( ambientLightColor );
	#if defined( USE_LIGHT_PROBES )
		roomIrradiance += getLightProbeIrradiance( lightProbe, mirrored );
	#endif
	#if ( NUM_HEMI_LIGHTS > 0 )
		#pragma unroll_loop_start
		for ( int i = 0; i < NUM_HEMI_LIGHTS; i ++ ) {
			roomIrradiance += getHemisphereLightIrradiance( hemisphereLights[ i ], mirrored );
		}
		#pragma unroll_loop_end
	#endif
	IncidentLight mirroredLight;
	#if ( NUM_POINT_LIGHTS > 0 )
		#pragma unroll_loop_start
		for ( int i = 0; i < NUM_POINT_LIGHTS; i ++ ) {
			getPointLightInfo( pointLights[ i ], surfacePosition, mirroredLight );
			roomIrradiance += saturate( dot( mirrored, mirroredLight.direction ) ) * mirroredLight.color;
		}
		#pragma unroll_loop_end
	#endif
	#if ( NUM_SPOT_LIGHTS > 0 )
		#pragma unroll_loop_start
		for ( int i = 0; i < NUM_SPOT_LIGHTS; i ++ ) {
			getSpotLightInfo( spotLights[ i ], surfacePosition, mirroredLight );
			roomIrradiance += saturate( dot( mirrored, mirroredLight.direction ) ) * mirroredLight.color;
		}
		#pragma unroll_loop_end
	#endif
	float strongest = max( max( f0.r, f0.g ), f0.b );
	vec3 glance = vec3( max( 1.0 - partcadRoughness, strongest ) );
	vec3 fresnel = f0 + ( glance - f0 ) * pow( 1.0 - dotNV, 5.0 );
	return fresnel * roomIrradiance * RECIPROCAL_PI * ( 1.0 - 0.5 * partcadRoughness ) * partcadRoomStrength;
}
`;

/**
 * What tints a finished face's specular colour by its image, where it is drawn
 * with one: 'map_fragment' has left the image's colour at this point in
 * 'sampledDiffuseColor', and the specular colour was blended into white.
 */
export const IMAGE_TINT = /* glsl */ `
#ifdef USE_MAP
	material.specularColor += partcadMapMetal * ( sampledDiffuseColor.rgb - 1.0 );
#endif
`;

/** What adds it, where three's light loop has left 'geometryPosition' and the rest in scope. */
export const ROOM_ADDITION = /* glsl */ `
reflectedLight.indirectSpecular += partcadRoomReflection( geometryPosition, geometryNormal, geometryViewDir, material.specularColor );
`;

/**
 * Three's Phong fragment shader with the room reflection in it, or undefined
 * where three's shader no longer has the places it goes (a test holds that).
 */
export function withRoomReflection(fragmentShader: string): string | undefined {
    for (const anchor of [DECLARATION_ANCHOR, TINT_ANCHOR, ADDITION_ANCHOR]) {
        if (!fragmentShader.includes(anchor)) {
            return undefined;
        }
    }
    return fragmentShader
        .replace(DECLARATION_ANCHOR, `${DECLARATION_ANCHOR}\n${ROOM_REFLECTION}`)
        .replace(TINT_ANCHOR, `${TINT_ANCHOR}\n${IMAGE_TINT}`)
        .replace(ADDITION_ANCHOR, `${ADDITION_ANCHOR}\n${ROOM_ADDITION}`);
}

/** The one shader program every finished face shares, whatever its finish: the roughness is a uniform. */
const PROGRAM_KEY = 'partcad-finish';

/**
 * Make a WebGL Phong 'material' draw 'finish' on a surface of 'albedo' (see
 * 'prepareFinish'), the room's reflection added to its shader.
 */
export function applyFinish(
    material: THREE.MeshPhongMaterial,
    albedo: number,
    finish: Finish,
    flat: number = albedo,
): FinishState {
    const state = prepareFinish(material, albedo, finish, flat);
    material.onBeforeCompile = (shader) => {
        const patched = withRoomReflection(shader.fragmentShader);
        if (patched !== undefined) {
            shader.uniforms.partcadRoughness = state.roughness;
            shader.uniforms.partcadRoomStrength = state.strength;
            shader.uniforms.partcadMapMetal = state.mapMetal;
            shader.fragmentShader = patched;
        }
    };
    material.customProgramCacheKey = () => PROGRAM_KEY;
    return state;
}
