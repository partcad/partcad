//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The PartCAD Viewer's 3D view: the renderer behind the first tab of the panel.
//
// Runs inside the webview, not in the extension host, so it has no access to
// 'vscode' or to node - the geometry arrives over postMessage as base64 binary
// glTF and is parsed straight out of memory. There is deliberately no network
// request anywhere in this file; the panel's CSP forbids one.
//
// The presentation follows 'react-partcad-prerendered' (see its
// 'src/components/Part.js'), which is the viewer PartCAD already ships on the
// web, so that a part looks the same in the IDE as it does on partcad.org:
//
//   * an auto-rotating orbit camera, framed on the model;
//   * drei's <Stage> lighting - an environment map plus an ambient/spot/point
//     trio scaled from the model's size;
//   * the hemisphere and point lights Part.js adds on top of Stage;
//   * MeshPhongMaterial (double-sided here: a sketch is one face, and Part.js
//     never has to draw one);
//   * a loading overlay showing the model size and progress.
//
// Two deliberate departures from Part.js, both forced by the webview: React and
// react-three-fiber are not used (a lot of bundle for one canvas), and the
// environment is three's procedural RoomEnvironment rather than drei's
// environment="city" preset, which is an HDRI fetched from a CDN that the CSP
// blocks and that would not work offline.
//
// A fourth departure: no shadows. <Stage shadows="contact"> puts a catcher under
// the model and the lights cast onto it, which is a studio's floor - and a CAD
// reader is looking at the shape rather than at where it sits. A flat model made
// the cost of it plain: a sketch lies *in* that catcher, so it z-fought with the
// thing it was catching the shadow of and shadowed itself, which is why one could
// not be seen at all. So the catcher, the shadow map and every cast/receive flag
// are gone rather than worked around.
//
// A third difference is not a choice. Part.js loads OBJ, a format with no scene
// graph and no units, so it has to rotate the model by -90 degrees about X
// itself to stand PartCAD's Z-up geometry up in a Y-up scene. glTF has both:
// build123d's export_gltf writes that same rotation into the node transform and
// converts millimetres to glTF's metres, so the geometry of every node arrives
// correctly oriented and rotating it again here would lay it on its side. What
// does not go through the exporter is every *placement* in the tree - a node's
// location and a port's - so those are converted; see 'frames.ts'.

import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { CSS2DObject, CSS2DRenderer } from 'three/examples/jsm/renderers/CSS2DRenderer.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';

import { calloutsOf } from './callouts';
import { el } from './dom';
import { MM_TO_M, TO_GLTF, placement, transformed } from './frames';
import { reportError } from './host';
import { ShowMessage, ShowNode } from './messages';
import { ItemId, PORT_COLOR, PORT_OPACITY, flickerOn, nodeId, portId, totalSize } from './nodes';

// Part.js: <Stage intensity={0.5}> and MeshPhongMaterial with no arguments.
const STAGE_INTENSITY = 0.5;
// Part.js: <OrbitControls autoRotate={true} autoRotateSpeed={5.0} />
const AUTO_ROTATE_SPEED = 5.0;
const container = document.getElementById('viewer') as HTMLDivElement;
const overlay = document.getElementById('overlay') as HTMLDivElement;

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(window.devicePixelRatio);
// The panel's background is the editor's, so the canvas stays transparent and
// the viewer follows the user's colour theme rather than fighting it.
renderer.setClearColor(0x000000, 0);
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.outputColorSpace = THREE.SRGBColorSpace;
container.appendChild(renderer.domElement);

// The text pinned to the model - what its metadata says about its elements - is
// DOM laid over the canvas rather than geometry drawn into it: text drawn as
// geometry would be a texture per callout, blurred at every zoom but one, and
// the DOM already knows how to set text in the editor's font and colours. Three
// places each element where its anchor projects on every frame.
const labelRenderer = new CSS2DRenderer();
labelRenderer.domElement.className = 'callouts';
container.appendChild(labelRenderer.domElement);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 10000);
camera.position.set(0, 0, 5);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.autoRotate = true;
controls.autoRotateSpeed = AUTO_ROTATE_SPEED;

// An environment map stands in for drei's <Environment preset="...">: image
// based lighting is what makes a machined surface read as one. RoomEnvironment
// is generated in code, so it costs no asset and works offline.
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
scene.environmentIntensity = STAGE_INTENSITY;

// <Stage>'s light rig, plus the two lights Part.js adds itself. Positions are
// set from the model's size in frame(), because a rig scaled for a 10 mm part
// lights a 2 m assembly not at all.
//
// Every positional light here has decay 0 - no inverse-square falloff - which
// is what makes these intensities mean the same thing whatever size the model
// is. With three's default physical decay of 2, irradiance is intensity/d², and
// glTF is in metres: a 10 mm part sits ~0.03 units from the rig, so intensity 1
// would arrive as ~1000 and burn the model to a white silhouette. (Part.js gets
// away with the default because its OBJ models are in millimetres, where the
// same lights land three orders of magnitude weaker and contribute almost
// nothing.) Turning decay off is the scale-invariant reading of that rig.
const ambientLight = new THREE.AmbientLight(0xffffff, STAGE_INTENSITY / 3);
const spotLight = new THREE.SpotLight(0xffffff, 2 * STAGE_INTENSITY, 0, Math.PI / 4, 1, 0);
const stagePointLight = new THREE.PointLight(0xffffff, STAGE_INTENSITY, 0, 0);
// Part.js: <hemisphereLight color="#40c040" intensity={0.7} groundColor="black" />
const hemisphereLight = new THREE.HemisphereLight(0x40c040, 0x000000, 0.7);
// Part.js: <pointLight intensity={1} />, at the scene origin.
const partPointLight = new THREE.PointLight(0xffffff, 1, 0, 0);
scene.add(ambientLight, spotLight, stagePointLight, hemisphereLight, partPointLight);

/**
 * Whether what a shape's metadata says about its elements is pinned to them.
 *
 * The "Show metadata" box. One switch over the whole layer rather than a flag per
 * callout, so that it holds for every show that follows without each of them
 * having to be told.
 */
export function setShowMetadata(enabled: boolean): void {
    labelRenderer.domElement.style.display = enabled ? '' : 'none';
}

/** Everything the current show put on the stage; replaced wholesale by the next. */
let content: THREE.Group | undefined;

/**
 * What each item of the control tree put on the stage, by item id.
 *
 * The geometry of one node is one glTF (PartCAD cuts it up that way - see
 * 'partcad/shape_envelope.py'), and a port's triad is one helper, so switching an
 * item off is setting 'visible' on what it drew. A list per item rather than a
 * group per item, because an item's drawables need not share a parent: a node's
 * geometry sits under the node's own group and a port's triad under the group
 * that converts into PartCAD's frame.
 */
const drawnBy = new Map<string, THREE.Object3D[]>();

/**
 * Which items are drawn, or undefined before anything has said.
 *
 * The panel sets this before every show, so that an item unchecked by default -
 * the ports of everything inside an assembly - is never drawn even for the frame
 * between its geometry arriving and the tree being built.
 */
let visibleItems: ReadonlySet<string> | undefined;

/**
 * The items being singled out, and when that started.
 *
 * Pointing at a part or a sub-assembly in the control pane flickers what it is on
 * screen - the only way to say "this row is that shape" without moving the camera
 * or recolouring anything. Held here rather than applied once, because a flicker is
 * a function of the clock and has to be re-applied every frame.
 */
let flickering: ReadonlySet<ItemId> | undefined;
let flickeringSince = 0;

/**
 * Single these items out, or nothing.
 *
 * Only what is already drawn flickers: an item switched off in the pane stays off,
 * because making it appear on hover would say the opposite of what its box says.
 */
export function flicker(items: Set<ItemId> | undefined): void {
    if (items !== undefined && items.size === 0) {
        items = undefined;
    }
    if (flickering !== undefined) {
        // Whatever was flickering goes back to what the pane says it should be.
        restoreVisibility(flickering);
    }
    flickering = items;
    flickeringSince = performance.now();
}

/** Set the visibility of these items from the pane's state, ignoring any flicker. */
function restoreVisibility(items: Iterable<ItemId>): void {
    for (const id of items) {
        const drawn = drawnBy.get(id);
        if (drawn === undefined) {
            continue;
        }
        const visible = visibleItems === undefined || visibleItems.has(id);
        for (const object of drawn) {
            object.visible = visible;
        }
    }
}

/** Remember what an item drew, and draw it only if that item is on. */
function drawnByItem(id: string, object: THREE.Object3D): void {
    object.visible = visibleItems === undefined || visibleItems.has(id);
    const drawn = drawnBy.get(id);
    if (drawn === undefined) {
        drawnBy.set(id, [object]);
    } else {
        drawn.push(object);
    }
}

/**
 * Draw these items of the control tree and nothing else.
 *
 * Called before a show, with what the incoming tree checks, and on every change
 * the user makes to it afterwards. An item with nothing on the stage - a group
 * row, an interface whose ports carry no boundary - simply matches nothing here.
 */
export function showItems(visible: ReadonlySet<string>): void {
    visibleItems = visible;
    for (const [id, drawn] of drawnBy) {
        for (const object of drawn) {
            object.visible = visible.has(id);
        }
    }
}

/**
 * Which show is the current one.
 *
 * Parsing a glTF is asynchronous, so a second show (or a clear) can arrive and
 * finish while the first is still decoding its objects. Without this, the older
 * call would go on to install its now-stale model over the newer one - visible
 * as the viewer showing the previously selected part after a quick change of
 * selection, or after a save that re-renders. Every show takes a generation on
 * entry and abandons its work as soon as it is no longer the newest.
 */
let generation = 0;

const loader = new GLTFLoader();

function base64ToArrayBuffer(base64: string): ArrayBuffer {
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i);
    }
    return bytes.buffer;
}

function parseGltf(buffer: ArrayBuffer): Promise<THREE.Group> {
    return new Promise((resolve, reject) => {
        // parse(), not load(): the bytes are already here, and load() would mean
        // a URL and therefore a network request the CSP forbids.
        loader.parse(buffer, '', (gltf) => resolve(gltf.scene), reject);
    });
}

/**
 * Let go of a material and of the textures it holds.
 *
 * 'Material.dispose()' frees the shader program and nothing else: a texture can
 * be shared between materials, so three.js leaves it to the application to say
 * when one is finished with. Here every texture came out of the glTF being
 * discarded and is referenced by nothing outside it, and 'dispose()' is
 * idempotent, so one shared between two materials of the same file is simply
 * disposed twice.
 */
function disposeMaterial(material: THREE.Material): void {
    for (const value of Object.values(material)) {
        const texture = value as THREE.Texture | undefined;
        if (texture?.isTexture) {
            texture.dispose();
        }
    }
    material.dispose();
}

/** The same, for the one-or-many a mesh's 'material' can be. */
function disposeMaterials(material: THREE.Material | THREE.Material[] | undefined): void {
    if (Array.isArray(material)) {
        material.forEach(disposeMaterial);
    } else if (material) {
        disposeMaterial(material);
    }
}

function disposeTree(root: THREE.Object3D): void {
    root.traverse((node) => {
        // A callout is an element in the DOM, not in the scene, and three removes
        // it only when the callout itself is what was removed - not when, as
        // here, something above it was. Left in place it would go on showing
        // where it last was, over a model that has gone.
        if (node instanceof CSS2DObject) {
            node.element.remove();
        }
        const mesh = node as THREE.Mesh;
        if (mesh.geometry) {
            mesh.geometry.dispose();
        }
        disposeMaterials(mesh.material as THREE.Material | THREE.Material[] | undefined);
    });
}

export function clearGeometry(): void {
    // Takes a generation too, so a show still decoding cannot undo the clear.
    generation += 1;
    if (content !== undefined) {
        scene.remove(content);
        disposeTree(content);
        content = undefined;
    }
    drawnBy.clear();
    visibleItems = undefined;
    flickering = undefined;
    overlay.textContent = 'Nothing to display yet.';
    overlay.style.display = '';
}

/**
 * Center the model at the origin and frame the camera on it, as
 * <Stage adjustCamera> does, and scale the light rig to it.
 */
function frame(group: THREE.Group, keepCamera: boolean): void {
    const box = new THREE.Box3().setFromObject(group);
    if (box.isEmpty()) {
        return;
    }

    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    const radius = Math.max(size.x, size.y, size.z) / 2 || 1;

    // Stage centers the model rather than moving the camera to it, so that
    // orbiting turns the model about itself.
    group.position.sub(center);

    spotLight.position.set(radius * 2, radius * 4, radius * 2);
    stagePointLight.position.set(-radius * 2, radius, -radius * 2);
    // Part.js leaves this one at the scene origin, i.e. inside the model.
    partPointLight.position.set(0, 0, 0);

    camera.near = radius / 100;
    camera.far = radius * 100;
    camera.updateProjectionMatrix();

    if (!keepCamera) {
        // Far enough back that the bounding sphere fits the vertical field of
        // view, with the same slight elevation Stage's default camera has.
        const distance = (radius * 1.6) / Math.tan((camera.fov * Math.PI) / 360);
        camera.position.set(distance * 0.6, distance * 0.5, distance * 0.8);
        controls.target.set(0, 0, 0);
    }
    controls.update();
}

/**
 * One node's ports: each as a triad, and as the boundary it is drawn with.
 *
 * A port is a coordinate frame, so the triad is what it *is* - the same thing
 * showing a bare location used to give. Most ports are also drawn with a sketch,
 * which is the shape the connection happens across: the circle of a hole, the
 * profile of a rail. Both belong to the port, so both are registered under it and
 * one checkbox draws or hides the pair.
 *
 * The two are placed differently because they arrive differently. A port's own
 * transform is a PartCAD location, so the triads go under a group carrying the
 * conversion into PartCAD's frame and keep their transforms exactly as PartCAD
 * stated them. A sketch has been through the exporter, so it is already in the
 * frame the scene is drawn in and takes the port's placement converted, exactly
 * as a child node does.
 */
function addPorts(
    parent: THREE.Group,
    node: ShowNode,
    path: number[],
    size: number,
    sketches: Map<string, THREE.Group>,
    material: THREE.Material,
): void {
    const ports = node.ports ?? [];
    if (ports.length === 0) {
        return;
    }

    const frame = transformed(TO_GLTF);
    parent.add(frame);

    ports.forEach((port, index) => {
        const item = portId(path, index);

        const [translation, axis, angle] = port.location;
        const axes = new THREE.AxesHelper(size);
        axes.position.set(translation[0], translation[1], translation[2]);
        const direction = new THREE.Vector3(axis[0], axis[1], axis[2]);
        if (direction.lengthSq() > 0) {
            axes.quaternion.setFromAxisAngle(direction.normalize(), (angle * Math.PI) / 180);
        }
        axes.name = port.name ?? 'port';
        frame.add(axes);
        drawnByItem(item, axes);

        const sketch = port.sketch ? sketches.get(port.sketch) : undefined;
        if (sketch === undefined) {
            return;
        }
        // Cloned per port, so forty holes drawn with one circle upload one
        // geometry and draw forty instances of it.
        const boundary = transformed(placement(port.location));
        const drawn = sketch.clone();
        drawn.traverse((child) => {
            const mesh = child as THREE.Mesh;
            if (mesh.isMesh) {
                mesh.material = material;
            }
        });
        boundary.add(drawn);
        parent.add(boundary);
        drawnByItem(item, boundary);
    });
}

/**
 * One node's callouts: what its metadata says about its elements, pinned to them.
 *
 * Placed like a port's triad, under a group converting PartCAD's frame into the
 * scene's, because what the metadata locates an element by is a PartCAD point in
 * millimetres. Registered under the node's own item, so the box that hides a
 * node's shape hides what is said about it too.
 *
 * Every element is built node by node through 'dom.ts': what a callout says is
 * text out of the drawing a package ships, and must not become markup.
 */
function addCallouts(parent: THREE.Group, node: ShowNode, path: number[]): void {
    const callouts = calloutsOf(node);
    if (callouts.length === 0) {
        return;
    }
    const frame = transformed(TO_GLTF);
    for (const callout of callouts) {
        const box = el('div', 'callout-box');
        if (callout.title !== undefined) {
            box.appendChild(el('div', 'callout-title', callout.title));
        }
        for (const line of callout.lines) {
            box.appendChild(el('div', 'callout-line', line));
        }
        const element = el('div', 'callout');
        element.appendChild(box);
        const label = new CSS2DObject(element);
        // Pinned by its bottom-left corner, where the leader line starts: the text
        // sits above and to the right of the element rather than over it.
        label.center.set(0, 1);
        label.position.set(callout.position[0], callout.position[1], callout.position[2]);
        frame.add(label);
    }
    parent.add(frame);
    drawnByItem(nodeId(path), frame);
}

/**
 * Give what a glTF draws the materials this viewer draws everything with.
 *
 * Part.js replaces whatever material the file carries with a plain
 * MeshPhongMaterial, which is what gives every PartCAD model the same look
 * regardless of how it was authored. Lines get one of their own: an edge that
 * bounds no face - the bend lines of a sheet metal drawing - arrives as glTF line
 * segments, and a lit material means nothing to a line.
 */
function restyle(group: THREE.Group, mesh: THREE.Material, line: THREE.Material): void {
    group.traverse((child) => {
        const drawable = child as THREE.Mesh | THREE.Line;
        let material: THREE.Material;
        if ((drawable as THREE.Mesh).isMesh) {
            material = mesh;
        } else if ((drawable as THREE.Line).isLine) {
            material = line;
        } else {
            return;
        }
        const previous = drawable.material as THREE.Material | THREE.Material[] | undefined;
        drawable.material = material;
        disposeMaterials(previous);
    });
}

/**
 * Every distinct piece of geometry in this tree, parsed once and handed out per use.
 *
 * PartCAD sends the geometry as a table on the root with the nodes naming entries
 * in it (see 'messages.ts'), so this parses the table - not the tree - and a shape
 * the tree holds a hundred times is parsed, and uploaded to the GPU, once.
 *
 * 'take' is what turns one parsed group into what a node adds to the stage: the
 * group itself for the first node that names it, and a clone for every node after
 * that. A clone is a fresh set of Object3Ds over the *same* BufferGeometry and the
 * same material, which is the whole point - one upload, one material, one instance
 * per node, and each node's own Object3D to switch on and off. Nothing is disposed
 * here: every group handed out ends up under the content group, and 'disposeTree'
 * frees it from there when the show is replaced.
 *
 * One material for all of it, for the same reason: every part of every PartCAD
 * model is drawn in this one blue, and a material per node is a material per node
 * for the renderer to set up.
 */
class Geometry {
    private readonly parsed = new Map<string, THREE.Group>();
    private readonly used = new Set<string>();
    readonly material = new THREE.MeshPhongMaterial({ color: 0x87ceeb, side: THREE.DoubleSide });
    // A deeper blue than the faces, so that a line lying on one - a bend line
    // across the blank it bends - reads against it, and unlit and not tone-mapped
    // so that it is that blue on a light theme and a dark one alike.
    readonly lineMaterial = new THREE.LineBasicMaterial({ color: 0x2f80ed, toneMapped: false });

    /** Parse the table, reporting progress as it goes. Returns what failed to parse. */
    async load(root: ShowNode, total: number, superseded: () => boolean): Promise<number> {
        let failed = 0;
        let bytes = 0;
        for (const [digest, entry] of Object.entries(root.geometry ?? {})) {
            try {
                const group = await parseGltf(base64ToArrayBuffer(entry.gltf));
                // Done here, once per distinct geometry, rather than per node that
                // draws it; see 'restyle'.
                //
                // Both sides of every face. A part is a closed solid and would look
                // the same either way, but a sketch and a port's boundary are
                // laminae: drawn front-side only, one whose face winds away from the
                // camera is not drawn at all, and the camera orbits past both sides
                // of it. Nothing says which way a sketch's one face points - the
                // ones in 'examples' happen to point up.
                restyle(group, this.material, this.lineMaterial);
                this.parsed.set(digest, group);
            } catch (error: any) {
                reportError(`failed to parse a shape of this object: ${error}`);
                failed += 1;
            }
            if (superseded()) {
                this.dispose();
                return failed;
            }
            bytes += entry.size ?? 0;
            const percent = total > 0 ? Math.round((bytes / total) * 100) : 100;
            overlay.textContent = `Model size: ${(total / 1048576.0).toFixed(2)}MB\n${percent}% loaded`;
        }
        return failed;
    }

    has(digest: string): boolean {
        return this.parsed.has(digest);
    }

    /** What the node naming 'digest' should add to the stage, or undefined. */
    take(digest: string): THREE.Group | undefined {
        const group = this.parsed.get(digest);
        if (group === undefined) {
            return undefined;
        }
        if (this.used.has(digest)) {
            return group.clone();
        }
        this.used.add(digest);
        return group;
    }

    /**
     * Everything parsed but never handed out - only reached when a show is dropped.
     *
     * What *was* handed out is not touched: its geometry is the geometry of every
     * clone of it, and those are under the content group, which 'disposeTree' frees
     * when the show is replaced. The material goes here because on this path
     * nothing is left holding it; 'dispose()' is idempotent, so the case where a
     * discarded group has already taken it with it costs nothing.
     */
    dispose(): void {
        for (const [digest, group] of this.parsed) {
            if (!this.used.has(digest)) {
                disposeTree(group);
            }
        }
        this.parsed.clear();
        this.material.dispose();
        this.lineMaterial.dispose();
    }
}

/**
 * The sketches the ports of this object are drawn with, parsed once each.
 *
 * Keyed by the reference the ports name, which is how PartCAD sends them: one
 * entry per sketch however many ports point at it (see 'port_sketches.py'). A
 * sketch that will not parse is left out, and the ports that name it keep their
 * triads.
 */
async function parseSketches(node: ShowNode, geometry: Geometry): Promise<Map<string, THREE.Group>> {
    const parsed = new Map<string, THREE.Group>();
    for (const [reference, sketch] of Object.entries(node.sketches ?? {})) {
        // A sketch names its geometry in the root's table like any node, so it is
        // already parsed; one that carries it outright is parsed here.
        if (sketch.gltfRef !== undefined) {
            const group = geometry.take(sketch.gltfRef);
            if (group !== undefined) {
                parsed.set(reference, group);
            }
            continue;
        }
        if (sketch.gltf === undefined) {
            continue;
        }
        try {
            const group = await parseGltf(base64ToArrayBuffer(sketch.gltf));
            // Its lines drawn like every other line; its faces are given the
            // boundary material per port, in 'addPorts'.
            restyle(group, geometry.material, geometry.lineMaterial);
            parsed.set(reference, group);
        } catch (error: any) {
            reportError(`failed to parse the port sketch '${reference}': ${error}`);
        }
    }
    return parsed;
}

/** How the parse of one tree went, so that a total failure can be reported as one. */
interface Loaded {
    parsed: number;
    failed: number;
    bytes: number;
    /**
     * Every node, with the group built for it.
     *
     * Collected as the tree is built rather than found again afterwards: the
     * ports cannot be added during the build because their size is a fraction of
     * the model's and the model is not measurable until all of it is there, and
     * matching groups back to nodes by position is exactly the kind of agreement
     * that stops holding the day a node gains a child of another sort.
     */
    built: { node: ShowNode; path: number[]; group: THREE.Group }[];
}

/**
 * One node as a group, with its geometry, its children and its ports inside it.
 *
 * The group carries the node's own placement, so the tree's locations compose the
 * way PartCAD states them and the way the BREP form realizes them - nothing is
 * baked into the geometry. Returns null once a newer show has superseded this
 * one, having disposed whatever it had built.
 */
async function buildNode(
    node: ShowNode,
    path: number[],
    superseded: () => boolean,
    loaded: Loaded,
    geometry: Geometry,
): Promise<THREE.Group | null> {
    const group = transformed(placement(node.location));
    group.name = node.label || node.name || nodeId(path);

    // Already parsed: the geometry of every node arrived in one table and was
    // parsed before the tree was walked, so what is left here is to take an
    // instance of it and put it where this node sits.
    let drawn: THREE.Group | undefined;
    if (node.gltfRef !== undefined) {
        drawn = geometry.take(node.gltfRef);
        if (drawn === undefined) {
            // Its entry failed to parse; reported once, where that happened.
            loaded.failed += 1;
        }
    } else if (node.gltf !== undefined) {
        // A node carrying its geometry outright, which PartCAD no longer sends and
        // a hand-written message still can.
        try {
            drawn = await parseGltf(base64ToArrayBuffer(node.gltf));
            restyle(drawn, geometry.material, geometry.lineMaterial);
        } catch (error: any) {
            reportError(`failed to parse '${node.name ?? group.name}': ${error}`);
            loaded.failed += 1;
        }
        if (superseded()) {
            if (drawn !== undefined) {
                disposeTree(drawn);
            }
            disposeTree(group);
            return null;
        }
    }
    if (drawn !== undefined) {
        group.add(drawn);
        drawnByItem(nodeId(path), drawn);
        loaded.parsed += 1;
    }

    const children = node.assembly ?? [];
    for (let index = 0; index < children.length; index++) {
        const child = await buildNode(children[index], [...path, index], superseded, loaded, geometry);
        if (child === null) {
            disposeTree(group);
            return null;
        }
        group.add(child);
    }

    loaded.built.push({ node, path, group });
    return group;
}

export async function showGeometry(message: ShowMessage): Promise<void> {
    const mine = (generation += 1);
    const superseded = () => generation !== mine;

    const object = message.object;
    if (object === null || object === undefined) {
        clearGeometry();
        return;
    }

    const total = totalSize(object);
    overlay.style.display = '';
    overlay.textContent = `Model size: ${(total / 1048576.0).toFixed(2)}MB\n0% loaded`;

    drawnBy.clear();
    flickering = undefined;

    // Parsed before the tree is walked, and once per distinct shape: this is where
    // the time of opening a large assembly goes, and it is the step that does not
    // grow with the number of times a shape is placed.
    const geometry = new Geometry();
    const failedToParse = await geometry.load(object, total, superseded);
    if (superseded()) {
        return;
    }
    const sketches = await parseSketches(object, geometry);
    if (superseded()) {
        geometry.dispose();
        sketches.forEach(disposeTree);
        return;
    }

    const loaded: Loaded = { parsed: 0, failed: failedToParse, bytes: total, built: [] };
    const root = await buildNode(object, [], superseded, loaded, geometry);
    if (root === null) {
        geometry.dispose();
        return;
    }

    // The object's own node carries a placement of its own, so what 'frame()'
    // centres is a group above it: moving the object's node would be moving the
    // model out of where the tree says it is.
    const group = new THREE.Group();
    group.add(root);

    // Drawn a quarter of the model's largest dimension, or 10 mm when there is no
    // geometry to measure against (an interface whose ports carry no boundary).
    // In millimetres, because that is the frame the triads are built in.
    const geometryBox = new THREE.Box3().setFromObject(group);
    const largest = geometryBox.isEmpty() ? 0 : Math.max(...geometryBox.getSize(new THREE.Vector3()).toArray());
    const size = largest > 0 ? largest / 4 / MM_TO_M : 10;
    // One material for every boundary of this show, and it goes when the content
    // does: 'disposeTree' frees it along with everything else, and the next show
    // makes a fresh one.
    //
    // Unlit and not tone-mapped, which is what makes it the same blue as the Z axis
    // beside it rather than merely the same number: 'AxesHelper' sets
    // 'toneMapped: false' on its own material, and this scene tone-maps
    // (ACESFilmic) everything that does not say otherwise. A lit material would
    // shade it away from the axis as well.
    const boundaryMaterial = new THREE.MeshBasicMaterial({
        color: PORT_COLOR,
        side: THREE.DoubleSide,
        toneMapped: false,
        // Half opaque: a boundary covers the opening it is the shape of, and a
        // solid one hides the very hole it is pointing at. 'depthWrite' off with
        // it, so two of them seen through each other - the near and far faces of a
        // through hole - both show rather than the nearer one claiming the depth
        // and hiding the other.
        transparent: true,
        opacity: PORT_OPACITY,
        depthWrite: false,
        // A hole's boundary is a disc lying *in* the face the hole opens through,
        // so it is coplanar with the part by construction and would z-fight with
        // it - speckling in and out as the camera turns. The offset biases its
        // depth toward the camera rather than moving it, so it wins consistently
        // and still sits exactly where the port is.
        polygonOffset: true,
        polygonOffsetFactor: -1,
        polygonOffsetUnits: -1,
    });
    // What keeps the Opacity slider off it: a boundary is drawn on the model rather
    // than being part of it. See 'setOpacity'.
    boundaryMaterial.userData.annotation = true;
    for (const { node, path, group: into } of loaded.built) {
        addPorts(into, node, path, size, sketches, boundaryMaterial);
        addCallouts(into, node, path);
    }

    if (superseded()) {
        disposeTree(group);
        return;
    }

    if (content !== undefined) {
        scene.remove(content);
        disposeTree(content);
    }
    content = group;
    scene.add(group);
    // Framed on everything the show carries, whether or not it is switched on:
    // the camera has to stay where it is when an item is unchecked, and a model
    // that reframed itself on every checkbox would be unusable.
    frame(group, message.keepCamera);

    // Nothing parsed: an empty scene with the overlay hidden is a viewer that
    // looks idle, which is the one thing this must not look like. The reason
    // went to the log by way of `reportError`; say here that there is one.
    if (loaded.failed > 0 && loaded.parsed === 0) {
        overlay.textContent =
            loaded.failed === 1
                ? 'The geometry could not be read. See the PartCAD output for why.'
                : `None of the ${loaded.failed} objects could be read. See the PartCAD output for why.`;
        overlay.style.display = '';
        return;
    }
    overlay.style.display = 'none';
}

export function resizeCanvas(): void {
    const width = container.clientWidth;
    const height = container.clientHeight;
    if (width === 0 || height === 0) {
        return;
    }
    renderer.setSize(width, height, false);
    labelRenderer.setSize(width, height);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
}

export function setAutoRotate(enabled: boolean): void {
    controls.autoRotate = enabled;
}

/**
 * How see-through the model is drawn.
 *
 * The model, and not what is drawn on top of it: an annotation has an opacity of
 * its own for a reason of its own - a port's boundary is half opaque so that the
 * opening it covers still reads as one - and this slider is about the shape. A
 * material that says it is an annotation is therefore left alone; otherwise
 * touching the slider at all would take that 50% away, and putting it back to 100%
 * would hide every hole behind a solid blue disc.
 */
export function setOpacity(opacity: number): void {
    if (content === undefined) {
        return;
    }
    const apply = (material: THREE.Material) => {
        if (material.userData.annotation === true) {
            return;
        }
        material.transparent = true;
        material.opacity = opacity;
        material.needsUpdate = true;
    };
    content.traverse((node) => {
        const mesh = node as THREE.Mesh;
        if (!mesh.isMesh) {
            return;
        }
        const material = mesh.material as THREE.Material | THREE.Material[] | undefined;
        if (Array.isArray(material)) {
            material.forEach(apply);
        } else if (material) {
            apply(material);
        }
    });
}

function animate(): void {
    controls.update();
    if (flickering !== undefined) {
        const on = flickerOn(performance.now() - flickeringSince);
        for (const id of flickering) {
            // Only what the pane is drawing: a hover says which of the things on
            // screen a row is, and cannot put one there.
            if (visibleItems !== undefined && !visibleItems.has(id)) {
                continue;
            }
            for (const object of drawnBy.get(id) ?? []) {
                object.visible = on;
            }
        }
    }
    renderer.render(scene, camera);
    labelRenderer.render(scene, camera);
}

window.addEventListener('resize', resizeCanvas);
resizeCanvas();
renderer.setAnimationLoop(animate);
