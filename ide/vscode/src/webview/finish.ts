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
//   * and the room reflected: the light that falls from the way the camera is
//     mirrored, by Schlick's Fresnel, damped by the roughness. three's Phong
//     material has no such term, so it is added to the shader
//     ('ROOM_REFLECTION'), from the lights the shader already has - the light
//     probe, the ambient, hemisphere, point and spot lights - each evaluated
//     along the mirrored direction rather than the normal, as 'finished_light'
//     evaluates 'diffuse'.
//
// Everything but the last is the Phong material's own parameters, so it is
// drawn alike by WebGL and by WebGPU. The room reflection is a WebGL shader
// patch ('onBeforeCompile'), which three's WebGPU renderer does not run: there a
// finished face has its highlights and its colour and lacks the reflection of
// the room, which is the smaller part of how it looks. The canvas painter draws
// a face flat in its colour, finish or no finish (see 'painter.ts').
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
// it (see 'viewerAppearance.test.ts').
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

/** What a Phong material is given to draw a finish: each colour in three's linear working space. */
export interface FinishedPhong {
    /** The diffuse colour: the albedo times what is no metal of it. */
    readonly color: THREE.Color;
    /** The specular colour: the dielectric's 0.04 blended into the albedo by the metalness. */
    readonly specular: THREE.Color;
    readonly shininess: number;
}

/**
 * The Phong parameters that draw 'finish' on a surface of 'albedo', 0xRRGGBB in
 * sRGB: white for one drawn with an image, as 'raster_scene.Scene' takes it.
 */
export function finishedPhong(albedo: number, finish: Finish): FinishedPhong {
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

/** Where 'ROOM_REFLECTION' is declared: after the Phong material's light functions. */
export const DECLARATION_ANCHOR = '#include <lights_phong_pars_fragment>';
/** Where it is added to the light: once three has added every light of its own. */
export const ADDITION_ANCHOR = '#include <lights_fragment_end>';

/**
 * The room as a finished surface reflects it: the second half of
 * 'finished_light'.
 *
 * Every light the shader has, evaluated along the mirrored view direction - the
 * irradiance a surface facing that way would receive, which is 'diffuse' of the
 * mirrored direction there - by Schlick's Fresnel with 'f0' the specular colour,
 * towards 'max(1 - roughness, f0)' at a glance, and halved as the surface is
 * rough. 'position', 'normal' and 'viewDir' are in view space, as three's own
 * light loop has them.
 */
export const ROOM_REFLECTION = /* glsl */ `
uniform float partcadRoughness;

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
	return fresnel * roomIrradiance * RECIPROCAL_PI * ( 1.0 - 0.5 * partcadRoughness );
}
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
    if (!fragmentShader.includes(DECLARATION_ANCHOR) || !fragmentShader.includes(ADDITION_ANCHOR)) {
        return undefined;
    }
    return fragmentShader
        .replace(DECLARATION_ANCHOR, `${DECLARATION_ANCHOR}\n${ROOM_REFLECTION}`)
        .replace(ADDITION_ANCHOR, `${ADDITION_ANCHOR}\n${ROOM_ADDITION}`);
}

/** The one shader program every finished face shares, whatever its finish: the roughness is a uniform. */
const PROGRAM_KEY = 'partcad-finish';

/**
 * Make 'material' draw 'finish' on a surface of 'albedo' (see 'finishedPhong').
 *
 * Its diffuse colour, specular colour and shininess are set, and the room's
 * reflection added to its shader for the WebGL renderer. 'userData.finish'
 * says it is finished, for the canvas painter (see 'painter.ts').
 */
export function applyFinish(material: THREE.MeshPhongMaterial, albedo: number, finish: Finish): void {
    const phong = finishedPhong(albedo, finish);
    material.color.copy(phong.color);
    material.specular.copy(phong.specular);
    material.shininess = phong.shininess;
    material.userData.finish = finish;
    const roughness = { value: finish.roughness };
    material.onBeforeCompile = (shader) => {
        const patched = withRoomReflection(shader.fragmentShader);
        if (patched !== undefined) {
            shader.uniforms.partcadRoughness = roughness;
            shader.fragmentShader = patched;
        }
    };
    material.customProgramCacheKey = () => PROGRAM_KEY;
}
