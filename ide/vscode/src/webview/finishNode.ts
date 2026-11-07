//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// A finished face drawn by three's WebGPU renderer (see 'finish.ts').
//
// That renderer draws with node materials, which it builds itself from a
// MeshPhongMaterial - and in doing so drops 'onBeforeCompile', the WebGL shader
// patch that adds the room's reflection. So under WebGPU a finished face is a
// MeshPhongNodeMaterial from the start, whose lighting model is three's Phong
// one plus that reflection, written in TSL: the same formula as the GLSL in
// 'finish.ts' ('ROOM_REFLECTION'), evaluated from the same lights along the
// mirrored view direction.
//
//   * The positional lights - the spot and the two point lights - come to the
//     lighting model one at a time, already attenuated ('direct'), and each adds
//     what it sends along the mirrored direction.
//   * The room's light - the light probe, the ambient light and the hemisphere -
//     reaches a node lighting model only as the irradiance along the normal, so
//     it is evaluated again along the mirrored direction from the rig's own
//     lights ('Rig'), which 'scene.ts' hands over and which are read on every
//     render, as three's own light nodes read them.
//
// Imported only where the window draws with WebGPU ('scene.ts'), because three's
// WebGPU build is ES modules only and the extension host's tests cannot load it.
// What it shares with the WebGL path - the finish's Phong parameters, the
// switch the Opacity slider throws - is 'finish.ts''s ('prepareFinish').
//

import * as THREE from 'three';
import { MeshPhongNodeMaterial, PhongLightingModel } from 'three/webgpu';
import {
    cameraWorldMatrix,
    float,
    getShIrradianceAt,
    materialReference,
    mix,
    normalView,
    positionViewDirection,
    specularColor,
    uniform,
    uniformArray,
    vec3,
} from 'three/tsl';

import { Finish, FinishUniform, prepareFinish } from './finish';

/** The room's lights a finished face reflects, beyond those that come to it one at a time. */
export interface Rig {
    readonly probe: THREE.LightProbe;
    readonly ambient: THREE.AmbientLight;
    readonly hemisphere: THREE.HemisphereLight;
}

// TSL is typed for its own use, not for a lighting model written outside three:
// the nodes below are built and combined as three's own models build them.
type NodeAny = any;

/** The rig as uniforms, shared by every finished material of a window and refreshed once per render. */
interface RigUniforms {
    readonly probe: NodeAny;
    readonly ambient: NodeAny;
    readonly sky: NodeAny;
    readonly ground: NodeAny;
    readonly up: NodeAny;
}

let shared: { rig: Rig; uniforms: RigUniforms } | undefined;

function rigUniforms(rig: Rig): RigUniforms {
    if (shared !== undefined && shared.rig === rig) {
        return shared.uniforms;
    }
    const probe: NodeAny = uniformArray(Array.from({ length: 9 }, () => new THREE.Vector3()));
    const ambient = uniform(new THREE.Color());
    const sky = uniform(new THREE.Color());
    const ground = uniform(new THREE.Color());
    const up = uniform(new THREE.Vector3(0, 1, 0));
    // Read as three's own light nodes read them (see 'LightProbeNode',
    // 'HemisphereLightNode'): each value times its light's intensity.
    (ambient as NodeAny).onRenderUpdate(() => {
        for (let i = 0; i < 9; i++) {
            probe.array[i].copy(rig.probe.sh.coefficients[i]).multiplyScalar(rig.probe.intensity);
        }
        ambient.value.copy(rig.ambient.color).multiplyScalar(rig.ambient.intensity);
        sky.value.copy(rig.hemisphere.color).multiplyScalar(rig.hemisphere.intensity);
        ground.value.copy(rig.hemisphere.groundColor).multiplyScalar(rig.hemisphere.intensity);
        up.value.setFromMatrixPosition(rig.hemisphere.matrixWorld).normalize();
    });
    const uniforms = { probe, ambient, sky, ground, up };
    shared = { rig, uniforms };
    return uniforms;
}

/**
 * Where a finished material keeps what its shader reads beyond a Phong material's
 * own, by 'FinishUniform'. Read through 'materialReference', which three reads
 * off whichever material it is drawing - not as a uniform node made per
 * material: three builds one program for every material whose nodes look alike
 * and keeps the nodes of the first, so a second finish drawn with the first's
 * uniforms was the first finish again.
 */
const PROPERTIES: Record<FinishUniform, string> = {
    roughness: 'partcadRoughness',
    strength: 'partcadRoomStrength',
    mapMetal: 'partcadMapMetal',
};

function property(name: FinishUniform): NodeAny {
    return (materialReference as NodeAny)(PROPERTIES[name], 'float');
}

/** Phong, plus the room as the face mirrors it ('finish.ts', 'ROOM_REFLECTION'). */
class FinishedLightingModel extends (PhongLightingModel as NodeAny) {
    constructor(private readonly room: RigUniforms) {
        super();
    }

    /** 'dot(N, V)' clamped, and the view direction mirrored about the normal, in view space. */
    private mirror(): { dotNV: NodeAny; mirrored: NodeAny } {
        const dotNV = (normalView as NodeAny).dot(positionViewDirection).clamp();
        const mirrored = (normalView as NodeAny).mul(dotNV.mul(2)).sub(positionViewDirection);
        return { dotNV, mirrored };
    }

    /** What the room's light from the mirrored direction is multiplied by: 'roomFresnel' over pi. */
    private reflects(dotNV: NodeAny): NodeAny {
        const roughness = property('roughness');
        const f0 = specularColor as NodeAny;
        const strongest = f0.r.max(f0.g).max(f0.b);
        const glance = vec3(float(1).sub(roughness).max(strongest));
        const fresnel = f0.add(glance.sub(f0).mul(float(1).sub(dotNV).pow(5)));
        return fresnel
            .mul(1 / Math.PI)
            .mul(float(1).sub(roughness.mul(0.5)))
            .mul(property('strength'));
    }

    direct(lightData: NodeAny, builder: NodeAny): void {
        super.direct(lightData, builder);
        const { lightDirection, lightColor, reflectedLight } = lightData;
        const { dotNV, mirrored } = this.mirror();
        const sent = mirrored.dot(lightDirection).clamp().mul(lightColor);
        reflectedLight.indirectSpecular.addAssign(sent.mul(this.reflects(dotNV)));
    }

    indirect(builder: NodeAny): void {
        super.indirect(builder);
        const { reflectedLight } = builder.context;
        const { dotNV, mirrored } = this.mirror();
        const world = mirrored.transformDirection(cameraWorldMatrix);
        const hemisphere = mix(this.room.ground, this.room.sky, world.dot(this.room.up).mul(0.5).add(0.5));
        const irradiance = (this.room.ambient as NodeAny)
            .add((getShIrradianceAt as NodeAny)(world, this.room.probe))
            .add(hemisphere);
        reflectedLight.indirectSpecular.addAssign(irradiance.mul(this.reflects(dotNV)));
    }
}

/** A MeshPhongNodeMaterial that draws a finish, with the room's reflection in its lighting. */
class FinishedPhongNodeMaterial extends (MeshPhongNodeMaterial as NodeAny) {
    constructor(
        parameters: THREE.MeshPhongMaterialParameters,
        private readonly room: RigUniforms,
    ) {
        super(parameters);
    }

    setupLightingModel(): NodeAny {
        return new FinishedLightingModel(this.room);
    }

    setupVariants(builder: NodeAny): void {
        super.setupVariants(builder);
        const self = this as NodeAny;
        if (self.map?.isTexture === true) {
            // Tinted by the image's colour where it is metal: 'IMAGE_TINT' in 'finish.ts'.
            const image = (materialReference as NodeAny)('map', 'texture').rgb;
            (specularColor as NodeAny).addAssign(image.sub(1).mul(property('mapMetal')));
        }
    }
}

/**
 * The material a finished face is drawn with under WebGPU: 'parameters' as
 * 'scene.ts' gives every face material, made to draw 'finish' on 'albedo' - and
 * 'flat' where an image cannot be drawn (see 'prepareFinish') - reflecting the
 * room 'rig' lights.
 */
export function finishedNodeMaterial(
    parameters: THREE.MeshPhongMaterialParameters,
    albedo: number,
    finish: Finish,
    flat: number,
    rig: Rig,
): THREE.MeshPhongMaterial {
    const material = new FinishedPhongNodeMaterial(parameters, rigUniforms(rig)) as unknown as THREE.MeshPhongMaterial;
    const values = material as unknown as Record<string, number>;
    prepareFinish(material, albedo, finish, flat, (name, value) => {
        const key = PROPERTIES[name];
        values[key] = value;
        return {
            get value() {
                return values[key];
            },
            set value(next: number) {
                values[key] = next;
            },
        };
    });
    return material;
}
