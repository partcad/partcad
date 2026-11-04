//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The Digital Thread's 3D view: the renderer behind the first tab of the panel.
//
// Runs inside the webview, not in the extension host, so it has no access to
// 'vscode' or to node - the geometry arrives over postMessage as the ArrayBuffers
// of binary glTF and is parsed straight out of memory, once per digest for as long
// as the host has it kept ('geometryCache.ts'). There is deliberately no network
// request anywhere in this file; the panel's CSP forbids one.
//
// The presentation follows 'react-partcad-prerendered' (see its
// 'src/components/Part.js'), which is the viewer PartCAD already ships on the
// web, so that a part looks the same in the IDE as it does on partcad.org:
//
//   * an auto-rotating orbit camera, framed on the model;
//   * drei's <Stage> lighting - an environment's light plus an ambient/spot/point
//     trio scaled from the model's size;
//   * the hemisphere and point lights Part.js adds on top of Stage (the
//     hemisphere white here rather than green - see below);
//   * MeshPhongMaterial (double-sided here: a sketch is one face, and Part.js
//     never has to draw one);
//   * a loading overlay showing the model size and progress.
//
// Two deliberate departures from Part.js, both forced by the webview: React and
// react-three-fiber are not used (a lot of bundle for one canvas), and the
// environment is three's procedural RoomEnvironment (as a light probe - see
// ROOM_LIGHT) rather than drei's environment="city" preset, which is an HDRI
// fetched from a CDN that the CSP blocks and that would not work offline.
//
// A fourth departure: no shadows. <Stage shadows="contact"> puts a catcher under
// the model and the lights cast onto it, which is a studio's floor - and a CAD
// reader is looking at the shape rather than at where it sits. A flat model made
// the cost of it plain: a sketch lies *in* that catcher, so it z-fought with the
// thing it was catching the shadow of and shadowed itself, which is why one could
// not be seen at all. So the catcher, the shadow map and every cast/receive flag
// are gone rather than worked around.
//
// A fifth departure is the colour. Part.js draws every model in one colour of its
// own - a sky-blue material under a green hemisphere light, which together come
// out green - whatever the model is. This view draws a shape in the colour it
// says it is ('properties: color'), and one that says nothing in goldenrod: the
// colour OCCT draws an uncoloured shape in, and the colour PartCAD's own 2D
// projections draw one in, so that the 3D tab and the 2D tab beside it show the
// same part (see 'appearance.ts'). A coloured light would turn every one of those
// colours into another, so the hemisphere light is white. A part whose faces
// are in colours of their own arrives as a mesh per colour, each with its own
// glTF material, and each mesh is drawn in its own colour - with this view's
// material, not the file's (see 'paint', and 'appearance.ts').
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
import { GLTF, GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { CSS2DObject, CSS2DRenderer } from 'three/examples/jsm/renderers/CSS2DRenderer.js';

import {
    Appearance,
    DEFAULT_APPEARANCE,
    OWN_APPEARANCE,
    appearanceKey,
    appearanceOf,
    edgeColor,
    ownAppearance,
    primitiveAppearance,
} from './appearance';
import { assemblyRows, calloutsOf, componentName, componentRows, isComponent } from './callouts';
import {
    SceneFrame,
    enclosingRadius,
    fitDistance,
    fitProgress,
    fromStage,
    placeCamera as aimCamera,
    readViewpoint,
} from './cameraView';
import { el, empty } from './dom';
import { MM_TO_M, TO_GLTF, placement, transformed } from './frames';
import { GeometryCache, geometryCache } from './geometryCache';
import { geometryMissing, reportError } from './host';
import { ShowMessage, ShowNode } from './messages';
import { LABEL_DEFAULTS, LabelChoices } from './labels';
import {
    ItemId,
    PORT_COLOR,
    PORT_OPACITY,
    flickerOn,
    groupPorts,
    interfaceId,
    interfaceLabel,
    nodeId,
    portId,
    portLabel,
    totalSize,
} from './nodes';
import { Bounds } from './section';
import { Navigable, onScreen, spaceMouse } from './spacemouse';
import {
    SOFTWARE_TRIANGLE_BUDGET,
    Surface,
    boxesOf,
    createSurface,
    disposeBoxes,
    softwareNotice,
    trianglesOf,
} from './surface';
import { Viewpoint } from './viewpoint';

// Part.js: <Stage intensity={0.5}> and MeshPhongMaterial with no arguments.
const STAGE_INTENSITY = 0.5;

/**
 * The diffuse light of three's RoomEnvironment, as the coefficients of a
 * 'SphericalHarmonics3' - three's order, each band's red, green and blue.
 *
 * Worked out with three's own tools rather than by hand: the room rendered into a
 * floating point cube map from its centre, by a cube camera with the near and far
 * planes 'PMREMGenerator.fromScene' uses (0.1 and 100), and handed to
 * 'LightProbeGenerator.fromCubeRenderTarget'. A 256- and a 512-pixel cube agree to
 * within a percent. The room is white, so each band's three are one number; the
 * second band, brighter above than below, is what makes it a room rather than a
 * fog. Fixed numbers rather than worked out at load, because working them out
 * reads the cube back from the GPU, which each renderer does its own way and the
 * software renderer cannot do at all.
 */
const ROOM_LIGHT = [3.78, 1.73, 1.59, 0.26, 0.19, 1.03, 1.19, -0.34, -0.63].flatMap((band) => [band, band, band]);
// Part.js: <OrbitControls autoRotate={true} autoRotateSpeed={5.0} />
const AUTO_ROTATE_SPEED = 5.0;
const container = document.getElementById('viewer') as HTMLDivElement;
const overlay = document.getElementById('overlay') as HTMLDivElement;

/**
 * What draws the stage: the GPU through WebGL, the GPU through WebGPU, or the
 * CPU into a canvas - the first of the three this window can give (see
 * 'surface.ts', which every 3D pane of the panel draws with).
 *
 * Every one of them draws only when something changed ('invalidate'). The canvas
 * painter is a different renderer with different limits, and this file says
 * where it differs: a big model is drawn as boxes while the camera is being
 * moved ('proxies').
 *
 * Tone-mapped with Khronos' PBR Neutral, because a shape is drawn in the colour
 * it says it is and this is the tone mapper made for showing one: below the
 * highlights it leaves a colour alone, so a face the light falls on squarely
 * comes out as the colour that was asked for. ACES Filmic, which this used to be
 * when every model was one colour of the viewer's choosing, bends every
 * saturated colour toward yellow and white as it brightens it: measured on the
 * same face, goldenrod came out as a paler, yellower gold, and a red as a lighter
 * and pinker one.
 */
const surface: Surface = await createSurface('the 3D view', { toneMapping: THREE.NeutralToneMapping });

/** Which of the three draws the 3D view (see 'Surface'). */
export const backend = surface.backend;

/** Whether the 3D view is drawn without a GPU at all, by the canvas painter. */
export const software = surface.backend === 'software';

surface.domElement.classList.add('surface');
container.appendChild(surface.domElement);

if (software) {
    container.appendChild(softwareNotice());
}

/** Draw the stage once. */
function drawStage(): void {
    surface.render(scene, camera);
}

/**
 * Something on the stage changed: the stage is drawn on the next frame.
 *
 * Nothing is drawn otherwise, on any backend. A frame of the painter is every
 * triangle filled on the CPU, and a frame of the GPU is every triangle of the
 * model again: a complex assembly drawn sixty times a second kept a core busy
 * for as long as the panel was open, with nothing on it moving (#838) - and
 * every one of those frames is CPU time where Chromium draws WebGL on the CPU
 * itself (SwiftShader), which this cannot tell from a GPU. So whatever changes
 * what is on screen says so here.
 */
let dirty = true;

function invalidate(): void {
    dirty = true;
}

// A context the browser took away and gave back is an empty canvas; and a page
// that was hidden may come back with its last frame gone, which costs one frame
// to put back.
surface.domElement.addEventListener('webglcontextrestored', invalidate);
document.addEventListener('visibilitychange', invalidate);

// The text pinned to the model - what its metadata says about its elements - is
// DOM laid over the canvas rather than geometry drawn into it: text drawn as
// geometry would be a texture per callout, blurred at every zoom but one, and
// the DOM already knows how to set text in the editor's font and colours. Three
// places each element where its anchor projects on every frame.
const labelRenderer = new CSS2DRenderer();
labelRenderer.domElement.className = 'callouts';
container.appendChild(labelRenderer.domElement);

/** Who is told when the camera moves: the view panel, which says where it is looking from. */
const viewListeners = new Set<() => void>();

/** Be told whenever the camera moves, however it was moved. */
export function onViewChange(listener: () => void): void {
    viewListeners.add(listener);
}

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 10000);
camera.position.set(0, 0, 5);

const controls = new OrbitControls(camera, surface.domElement);
controls.enableDamping = true;
// Turning on its own is a frame every 16 ms for as long as the panel is open,
// which the software renderer cannot afford: off there until it is asked for.
controls.autoRotate = !software;
controls.autoRotateSpeed = AUTO_ROTATE_SPEED;

/**
 * What the Animate box says: on from the start, except where the canvas painter
 * draws (see above). A SpaceMouse being moved pauses the turn without unticking
 * it ('animate'). A show does not touch it, and after the first one does not
 * turn the camera either, so the turn carries on from one object to the next.
 */
let autoRotate = controls.autoRotate;

/**
 * What the Auto-fit box says, beside Animate: whether a show of the same object
 * again - an edit saved, an agent's next version of it - is fitted too, as a
 * show of another object always is. On from the start, so that a model which
 * grows or shrinks stays in view; off for somebody zoomed in on one corner of
 * a part they are editing, whose view a save must not take away.
 */
let autoFit = true;

// Any movement of the camera - a drag, the damping after it, a turn of the
// model on its own - is a new picture, and a new viewpoint for the view panel.
controls.addEventListener('change', invalidate);
controls.addEventListener('change', () => viewListeners.forEach((listener) => listener()));

// The light of a room stands in for drei's <Environment preset="...">: light
// from every direction, brighter from above, is what makes a machined surface
// read as one. The room is three's RoomEnvironment, and what of it lights the
// model is its diffuse light - which is a light probe: the room's light as nine
// spherical harmonics, worked out once (see ROOM_LIGHT) rather than shipped.
//
// A light probe and not the room as 'scene.environment', which is what this
// used to be, because the two GPU renderers do not read an environment the same
// way. Three's WebGL renderer lights a Phong material with it, as a light from
// every direction; its WebGPU renderer only reflects it - a Phong material there
// is lit by the lights alone, which measured on the same face was half as
// bright, and a goldenrod part came out the brown of an old coin. A light probe
// is a light, and every renderer lights every lit material with it the same
// way. The software renderer lights with its own rig and ignores it (see
// below).
const roomLight = new THREE.LightProbe(new THREE.SphericalHarmonics3().fromArray(ROOM_LIGHT), STAGE_INTENSITY);
scene.add(roomLight);

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
// Part.js: <hemisphereLight color="#40c040" intensity={0.7} groundColor="black" />,
// but white: Part.js's green sky is what made every model it draws green, and a
// shape here is drawn in its own colour (see the header). The intensity is
// Part.js's, so a face turned up to the sky is as bright as it was there.
const hemisphereLight = new THREE.HemisphereLight(0xffffff, 0x000000, 0.7);
// Part.js: <pointLight intensity={1} />, at the scene origin.
const partPointLight = new THREE.PointLight(0xffffff, 1, 0, 0);
scene.add(ambientLight, spotLight, stagePointLight, hemisphereLight, partPointLight);

// Drawn without a GPU, the model is lit differently: the software renderer
// knows ambient, directional and point lights and nothing else, and a flat face
// takes one colour, so the rig above - a spot, a hemisphere, point lights tuned
// for image-based lighting - washes every face out to the same pale tint. What
// reads instead is a light that moves with the viewer, so that faces turned
// away from it darken as they turn, and enough ambient light that none goes
// black.
if (software) {
    scene.remove(roomLight, spotLight, stagePointLight, hemisphereLight, partPointLight);
    ambientLight.intensity = 0.2;
    const headlight = new THREE.DirectionalLight(0xffffff, 0.85);
    // From above and to the left of the viewer rather than from the viewer: a
    // light from the eye lights every face it can see about equally, and flat
    // faces that differ by their angle alone then read as one.
    headlight.position.set(-0.7, 1, 0.5);
    camera.add(headlight);
    camera.add(headlight.target);
    headlight.target.position.set(0, 0, -1);
    scene.add(camera);
}

/**
 * The callouts one show pinned to the model, by the box that switches them.
 *
 * Every one is a child of what it is about - a component's of its geometry, a
 * port's of its triad, an element's of its node - so the tree's boxes, which
 * switch those on and off, take the callout with them: three's 'CSS2DRenderer'
 * hides a callout under anything hidden. What is left to these switches is a
 * callout's own 'visible', which nothing else touches. An interface's is the
 * exception, being on the node rather than on any one port: see
 * 'refreshInterfaceCallouts'.
 *
 * Made per show and put in place only once the show is ('showGeometry'), so that
 * a box changed while a show is still decoding applies to what is on screen.
 */
interface Callouts {
    /** What a shape's metadata says about its elements: the Metadata box. */
    metadata: CSS2DObject[];
    /**
     * One per component, its rows written by 'refreshComponentCallouts' - and one
     * per node that holds others ('holds'), which writes something only when it
     * is priced as a whole (see 'assemblyRows').
     */
    components: {
        object: CSS2DObject;
        box: HTMLElement;
        name: string;
        objectName: string | undefined;
        holds: boolean;
    }[];
    /** One per port, at the tip of its +Z axis. */
    ports: CSS2DObject[];
    /** One per interface instance, in the middle of its ports, and the items it is drawn with. */
    interfaces: { object: CSS2DObject; item: ItemId; ports: ItemId[] }[];
}

function noCallouts(): Callouts {
    return { metadata: [], components: [], ports: [], interfaces: [] };
}

let callouts: Callouts = noCallouts();

/** What the Metadata box says; kept across shows. */
let showMetadata = true;

/** What the callout boxes under the tree say ('labels.ts'); kept across shows. */
let labelChoices: LabelChoices = { ...LABEL_DEFAULTS };

/** The price of each component, as text, by the object it is ('<package>:<name>'). */
let priceTexts: Readonly<Record<string, string>> = {};

/**
 * Whether what a shape's metadata says about its elements is pinned to them.
 *
 * The "Metadata" box. Held here rather than set on each callout once, so that it
 * holds for every show that follows without each of them having to be told.
 */
export function setShowMetadata(enabled: boolean): void {
    showMetadata = enabled;
    callouts.metadata.forEach((object) => (object.visible = enabled));
    invalidate();
}

/** What the callout boxes say: which of the four kinds of callout are written. */
export function setLabels(choices: LabelChoices): void {
    labelChoices = { ...choices };
    refreshComponentCallouts();
    callouts.ports.forEach((object) => (object.visible = labelChoices.portNames));
    refreshInterfaceCallouts();
    invalidate();
}

/**
 * What each component costs, as the text its callout writes, by the object it
 * is - or nothing, while it is being asked and when nobody quoted it. Kept for
 * the shows that follow, which are told it as they are drawn.
 */
export function setComponentPrices(prices: Readonly<Record<string, string>>): void {
    priceTexts = { ...prices };
    refreshComponentCallouts();
    invalidate();
}

/** Write every component's callout over, as the boxes and the prices now say; none where it has nothing to say. */
function refreshComponentCallouts(made: Callouts = callouts): void {
    for (const callout of made.components) {
        const price = callout.objectName !== undefined ? priceTexts[callout.objectName] : undefined;
        const rows = (callout.holds ? assemblyRows : componentRows)(callout.name, price, labelChoices);
        empty(callout.box);
        rows.forEach((row) => callout.box.appendChild(el('div', 'callout-line', row)));
        callout.object.visible = rows.length > 0;
    }
}

/** Whether the tree draws an item. */
function itemShown(id: ItemId): boolean {
    return visibleItems === undefined || visibleItems.has(id);
}

/**
 * Show each interface's name where the tree draws that interface and at least
 * one of its ports: the name is pinned in the middle of the ports, which are
 * the only thing of it that is drawn, so with none of them drawn it would name
 * nothing - which is also what the 2D tab's picture does, writing an interface's
 * name only beside ports it draws.
 */
function refreshInterfaceCallouts(made: Callouts = callouts): void {
    for (const callout of made.interfaces) {
        callout.object.visible =
            labelChoices.interfaceNames && itemShown(callout.item) && callout.ports.some(itemShown);
    }
}

/**
 * One callout: rows of text in a box, pinned by its bottom-left corner - where
 * its leader line starts - so the text sits above and to the right of what it
 * is about rather than over it. Built node by node through 'dom.ts': what it
 * says is text out of a package, and must not become markup.
 */
function calloutObject(kind: string, rows: string[], title?: string): { object: CSS2DObject; box: HTMLElement } {
    const box = el('div', 'callout-box');
    if (title !== undefined) {
        box.appendChild(el('div', 'callout-title', title));
    }
    for (const row of rows) {
        box.appendChild(el('div', 'callout-line', row));
    }
    const element = el('div', `callout ${kind}`);
    element.appendChild(box);
    const object = new CSS2DObject(element);
    object.center.set(0, 1);
    return { object, box };
}

/** Everything the current show put on the stage; replaced wholesale by the next. */
let content: THREE.Group | undefined;

/** Whether what is on the stage is a cross-section of the object rather than the whole of it. */
let shownCut = false;

/** What 'content' was built from, whose materials go when it does (see 'Geometry.disposeMaterials'). */
let shownGeometry: Geometry | undefined;

/**
 * The radius of the sphere holding what the current show was framed on, however
 * it is turned ('enclosingRadius'), and where its middle is on the stage: what a
 * fit fits (see 'frame').
 */
let framedRadius = 1;
const framedCentre = new THREE.Vector3();

/**
 * A "Fit" on its way: where the camera started from, and when.
 *
 * Only where it started from is kept, and not where it is going: the camera
 * goes on turning while it moves - Animate, the damping of a drag - and the
 * canvas can change shape, so where it is going is worked out on every frame
 * ('stepFit').
 */
interface Fitting {
    since: number;
    target: THREE.Vector3;
    distance: number;
}

let fitting: Fitting | undefined;

/**
 * The radius the camera was last fitted to, while it is still where that fit put
 * it, give or take the turntable.
 *
 * While it is, a canvas that changes shape is fitted again ('resizeCanvas'): the
 * fit depends on the canvas's shape, and a show can be fitted while the 3D tab is
 * hidden, which is to a shape the canvas no longer has. Moving the camera by hand
 * - a drag, the wheel, a SpaceMouse - ends that, and the camera stays put.
 *
 * The radius of that fit and not the current show's: a show that keeps the camera
 * (a cut, or the same object again with Auto-fit off) keeps the view it had, and a
 * resize after it changes that view by what the canvas did and not by what the
 * show did.
 *
 * Undefined, too, while a "Fit" is on its way ('fitting'), which follows the
 * canvas itself, and set once it has arrived.
 */
let fittedTo: number | undefined;

/**
 * Whether somebody has hold of the view right now, by hand - a drag or a turn of
 * the wheel, between the orbit controls' own 'start' and 'end' - and by
 * SpaceMouse, between the 'start' and 'end' it relays through the same controls
 * ('navigable.moving').
 *
 * A fit is stopped when somebody takes hold of the view, and that alone is not
 * enough: a fit can also start while they are holding it - a show arriving in
 * the middle of a drag, a push - and 'start' has been and gone. So a fit does
 * not take a step while the view is held ('stepFit').
 *
 * Two flags rather than one, because a push that comes and goes in the middle of
 * a drag must not let go of the drag; and not a count of 'start's and 'end's,
 * because the controls do not pair them - a touch sends a 'start' for each
 * finger and one 'end' for all of them, and a button they ignore sends an 'end'
 * with no 'start' - so a count drifts, and one stuck above nought would stop
 * every fit for good.
 */
let dragging = false;
let pushing = false;

/** Set while the SpaceMouse relays its 'start' or 'end', so that the listeners below do not take it for a drag's. */
let relaying = false;

controls.addEventListener('start', () => {
    fittedTo = undefined;
    if (!relaying) {
        dragging = true;
    }
    // Two hands on one wheel: whoever takes hold of the view has it.
    fitting = undefined;
});
controls.addEventListener('end', () => {
    if (!relaying) {
        dragging = false;
    }
});

/** Which way the camera looks at the model from: Stage's default, slightly above. */
const VIEW_DIRECTION = new THREE.Vector3(0.6, 0.5, 0.8);

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
    invalidate();
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
    refreshInterfaceCallouts();
    invalidate();
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

/**
 * The bytes of a glTF payload as a webview receives one: the ArrayBuffer the
 * host posted, as it is. Base64 only from a hand-written message or a test,
 * which is the one place a loop over characters is still worth its cost.
 */
function bufferOf(payload: ArrayBuffer | string): ArrayBuffer {
    if (payload instanceof ArrayBuffer) {
        return payload;
    }
    const binary = atob(payload);
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
        loader.parse(
            buffer,
            '',
            (gltf) => {
                keepOwnColors(gltf);
                resolve(gltf.scene);
            },
            reject,
        );
    });
}

/**
 * Note on each primitive the colour its file gives it, before anything takes
 * the file's materials away (see 'ownAppearance').
 *
 * Kept in 'userData' because that is what a clone copies: every instance of a
 * cached shape is a clone of its template, and is painted as it is handed out.
 * Which materials the file declares is the loader's to say ('associations'),
 * since three gives a primitive with none a default material indistinguishable
 * from a white one.
 */
function keepOwnColors(gltf: GLTF): void {
    gltf.scene.traverse((child) => {
        const mesh = child as THREE.Mesh;
        if (!mesh.isMesh) {
            return;
        }
        const material = mesh.material as THREE.Material;
        const own = ownAppearance(material, gltf.parser.associations.get(material)?.materials !== undefined);
        if (own !== undefined) {
            const { map, ...plain } = own;
            mesh.userData[OWN_APPEARANCE] = plain;
            if (map !== undefined) {
                // Not in 'userData', which a clone copies through JSON and a
                // texture does not survive: by the geometry, which every clone
                // of the template shares. The template's to free, not a show's.
                map.userData.cached = true;
                ownTextures.set(mesh.geometry, map);
            }
        }
    });
}

/**
 * The image each primitive of a parsed shape is drawn with, where its colour is
 * drawn with one (see 'ownAppearance'), by the primitive's geometry: what every
 * clone of a template shares. Freed with the template ('releaseTemplate').
 */
const ownTextures = new WeakMap<THREE.BufferGeometry, THREE.Texture>();

/**
 * The materials a cached shape carries while nothing draws it. Never drawn with:
 * every instance of it is painted as it is handed out (see 'buildNode' and
 * 'addPorts'). Shared, and never freed, so that freeing a show cannot free the
 * cache's materials and the cache's cannot be any show's.
 */
const TEMPLATE_FACES = new THREE.MeshBasicMaterial();
const TEMPLATE_LINES = new THREE.LineBasicMaterial();

/**
 * Every parsed shape the renderer keeps across shows, by digest; see
 * 'geometryCache.ts'. What is kept is a template: never on the stage itself, and
 * only ever cloned - a clone is new Object3Ds over the template's BufferGeometry -
 * so that it is the same untouched group for every show that draws it.
 */
const templates = geometryCache as GeometryCache<THREE.Group>;
templates.onRelease(releaseTemplate);

/**
 * A shape parsed for the cache: the file's own materials gone, and every geometry
 * in it marked as the cache's, so that freeing a show's content leaves it alone.
 */
async function parseTemplate(buffer: ArrayBuffer): Promise<THREE.Group> {
    const group = await parseGltf(buffer);
    group.traverse((child) => {
        const drawable = child as THREE.Mesh | THREE.Line;
        if (drawable.geometry !== undefined) {
            drawable.geometry.userData.cached = true;
        }
        if ((drawable as THREE.Mesh).isMesh || (drawable as THREE.Line).isLine) {
            disposeMaterials(drawable.material as THREE.Material | THREE.Material[] | undefined);
            drawable.material = (drawable as THREE.Mesh).isMesh ? TEMPLATE_FACES : TEMPLATE_LINES;
        } else if (drawable.material !== undefined) {
            // Neither faces nor lines - nothing PartCAD writes - and so kept,
            // and marked to go with the template rather than with a show.
            for (const material of [drawable.material].flat()) {
                material.userData.cached = true;
            }
        }
    });
    return group;
}

/**
 * Free the images the primitives of a parsed glTF are drawn with (see
 * 'keepOwnColors'), once nothing draws any of them: the GPU texture, and the
 * decoded image under it. three's GLTFLoader decodes an embedded image into an
 * 'ImageBitmap', which 'Texture.dispose()' leaves alone and which is not given
 * back until it is closed (see the note at the top of 'GLTFLoader.js').
 *
 * 'geometries' are every primitive of one parsed file, which are all that hold
 * its images - each parse makes images of its own, and the primitives of one
 * file drawn with one image share it - so each is freed once, after all of them
 * have let go.
 */
function releaseOwnTextures(geometries: Iterable<THREE.BufferGeometry>): void {
    const textures = new Set<THREE.Texture>();
    for (const geometry of geometries) {
        const texture = ownTextures.get(geometry);
        if (texture !== undefined) {
            textures.add(texture);
            ownTextures.delete(geometry);
        }
    }
    for (const texture of textures) {
        texture.dispose();
        const image = texture.image as unknown;
        if (typeof ImageBitmap !== 'undefined' && image instanceof ImageBitmap) {
            image.close();
        }
    }
}

/** Free a template the cache let go of, once nothing on the stage draws it. */
function releaseTemplate(group: THREE.Group): void {
    const geometries: THREE.BufferGeometry[] = [];
    group.traverse((child) => {
        const drawable = child as THREE.Mesh;
        if (drawable.geometry !== undefined) {
            geometries.push(drawable.geometry);
        }
        drawable.geometry?.dispose();
        for (const material of [drawable.material ?? []].flat()) {
            if (material !== TEMPLATE_FACES && material !== TEMPLATE_LINES) {
                disposeMaterial(material);
            }
        }
    });
    releaseOwnTextures(geometries);
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
        // An image a primitive is drawn with is its template's, and goes with
        // the template (see 'keepOwnColors'), not with a show that drew it.
        if (texture?.isTexture && !texture.userData.cached) {
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

/**
 * Free what a show put on the stage - but not what the cache keeps: the geometry
 * of a cached shape is the geometry of every show that draws it, the next one
 * included, and goes when the cache lets go of it ('releaseTemplate').
 */
function disposeTree(root: THREE.Object3D): void {
    // The geometry a show parsed for itself goes here, and with it the images
    // its primitives are drawn with, which nothing else frees: they are marked
    // as a template's are ('keepOwnColors'), and there is no template.
    const local: THREE.BufferGeometry[] = [];
    root.traverse((node) => {
        // A callout is an element in the DOM, not in the scene, and three removes
        // it only when the callout itself is what was removed - not when, as
        // here, something above it was. Left in place it would go on showing
        // where it last was, over a model that has gone.
        if (node instanceof CSS2DObject) {
            node.element.remove();
        }
        const mesh = node as THREE.Mesh;
        if (mesh.geometry && !mesh.geometry.userData.cached) {
            mesh.geometry.dispose();
            local.push(mesh.geometry);
        }
        for (const material of [mesh.material ?? []].flat()) {
            if (material !== TEMPLATE_FACES && material !== TEMPLATE_LINES && !material.userData.cached) {
                disposeMaterial(material);
            }
        }
    });
    releaseOwnTextures(local);
}

export function clearGeometry(): void {
    // Takes a generation too, so a show still decoding cannot undo the clear.
    generation += 1;
    if (content !== undefined) {
        scene.remove(content);
        disposeTree(content);
        content = undefined;
    }
    shownGeometry?.disposeMaterials();
    shownGeometry = undefined;
    shownCut = false;
    fitting = undefined;
    drawnBy.clear();
    callouts = noCallouts();
    visibleItems = undefined;
    flickering = undefined;
    dropProxies();
    // Nothing is drawn now, so whatever the cache let go of can go.
    templates.use([]);
    invalidate();
    overlay.textContent = 'Nothing to display yet.';
    overlay.style.display = '';
}

/**
 * Center 'box' at the origin, moving the model with it, and scale the light rig
 * and the clipping planes to it, as <Stage adjustCamera> does - and, with
 * 'place', put the camera on it at the opening view, as a first show does.
 * Every other show leaves the camera where it is and asks for a "Fit"
 * ('showGeometry'), so that it gets there over a second rather than jumping.
 *
 * 'centred' is where the last show put the model instead, for a show that cuts
 * it or takes a cut away: the cut is a part of the same object, and centred on
 * itself it would jump on the stage every time a slider is let go, with the
 * camera kept where it was. So the object stays where it was put.
 */
function frame(group: THREE.Group, box: THREE.Box3, place: boolean, centred?: THREE.Vector3): void {
    if (box.isEmpty()) {
        return;
    }

    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    const radius = Math.max(size.x, size.y, size.z) / 2 || 1;
    framedRadius = enclosingRadius(box) || radius;

    // Stage centers the model rather than moving the camera to it, so that
    // orbiting turns the model about itself.
    if (centred !== undefined) {
        group.position.copy(centred);
    } else {
        group.position.sub(center);
    }
    // Where the middle of the box is now: the stage's origin, or where a cut
    // keeps it. The group was at the origin when the box was measured.
    framedCentre.copy(center).add(group.position);

    spotLight.position.set(radius * 2, radius * 4, radius * 2);
    stagePointLight.position.set(-radius * 2, radius, -radius * 2);
    // Part.js leaves this one at the scene origin, i.e. inside the model.
    partPointLight.position.set(0, 0, 0);

    if (place) {
        placeCamera(framedRadius);
    }
    clip(camera.position.distanceTo(controls.target));
    controls.update();
}

/**
 * Near and far enough for the model at 'distance': a hundredth of its size in
 * front, and behind it a hundred times its size or twice as far as it is,
 * whichever is further - a fit from the last object's distance starts wherever
 * that was, and a far plane drawn for the new one alone would hide it until the
 * camera had come in.
 */
function clip(distance: number): void {
    camera.near = framedRadius / 100;
    camera.far = Math.max(framedRadius * 100, (distance + framedRadius) * 2);
    camera.updateProjectionMatrix();
}

/**
 * From 'VIEW_DIRECTION', at Stage's slight elevation, as far back as a fit puts
 * it ('fitDistance' in 'cameraView.ts': every angle of the model in the
 * narrower field), looking at the middle of the model.
 *
 * The canvas is measured first, because a show can arrive before anything has
 * told the camera what shape the canvas has now.
 */
function placeCamera(radius: number): void {
    resizeCanvas();
    const direction = VIEW_DIRECTION.clone().normalize();
    controls.target.copy(framedCentre);
    camera.position.copy(framedCentre).addScaledVector(direction, fitDistance(radius, camera.fov, camera.aspect));
    fittedTo = radius;
}

/**
 * Put the camera back at the opening view, on the model as it is already
 * placed, at once: the view panel's "Reset".
 *
 * Not 'frame()': that centres the model as well, which a show does once and
 * which a second time would do nothing but accumulate rounding.
 */
export function resetView(): void {
    if (content === undefined) {
        return;
    }
    fitting = undefined;
    placeCamera(framedRadius);
    clip(camera.position.distanceTo(controls.target));
    controls.update();
}

/**
 * "Fit": bring the camera, over 'FIT_MILLISECONDS', to where the whole model
 * fits in the view however it is turned (see 'fitDistance'), looking at its
 * middle, and from the same side it is looking from now.
 *
 * The view panel's Fit button, a SpaceMouse's Fit key, and what a show of the
 * whole object after the first one ends with - always for another object, and
 * for the same one again while Auto-fit is on ('showGeometry'). Gradual,
 * because a view that jumps to another size is a view somebody has to find the
 * model in again; and the angle is not touched, so a model turning on its own
 * goes on turning through it. Taking hold of the view - a drag, the wheel, a
 * SpaceMouse, a viewpoint chosen in the panel - stops it where it is.
 */
export function fit(): void {
    if (content === undefined) {
        return;
    }
    fitting = {
        since: performance.now(),
        target: controls.target.clone(),
        distance: camera.position.distanceTo(controls.target),
    };
    // Not fitted until it is there: a resize meanwhile is the fit's to follow.
    fittedTo = undefined;
    invalidate();
}

/** Move a "Fit" on to where it is at 'now', before the controls take their turn; a frame of it is a new picture. */
function stepFit(now: number): void {
    if (fitting === undefined) {
        return;
    }
    if (dragging || pushing) {
        // Started while somebody was moving the view: theirs, as one they
        // took hold of is (see 'dragging').
        fitting = undefined;
        return;
    }
    const along = fitProgress(now - fitting.since);
    const goal = fitDistance(framedRadius, camera.fov, camera.aspect);
    const distance = fitting.distance + (goal - fitting.distance) * along;
    const direction = camera.position.clone().sub(controls.target);
    if (direction.lengthSq() === 0) {
        direction.copy(VIEW_DIRECTION);
    }
    direction.normalize();
    controls.target.lerpVectors(fitting.target, framedCentre, along);
    camera.position.copy(controls.target).addScaledVector(direction, distance);
    clip(distance);
    invalidate();
    if (along >= 1) {
        fitting = undefined;
        fittedTo = framedRadius;
    }
}

/**
 * The 3D view, as the SpaceMouse moves it: only while its tab is the one on
 * screen, and a push is a drag as far as the controls' listeners are concerned.
 * Its Fit key is the view panel's Fit button.
 */
const navigable: Navigable = {
    camera,
    target: controls.target,
    shown: () => onScreen(container),
    fit,
    moving: (moving) => {
        pushing = moving;
        relaying = true;
        try {
            controls.dispatchEvent({ type: moving ? 'start' : 'end' });
        } finally {
            relaying = false;
        }
    },
};
spaceMouse.attach(navigable);

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
    lineMaterial: THREE.Material,
    made: Callouts,
): void {
    const ports = node.ports ?? [];
    if (ports.length === 0) {
        return;
    }

    const frame = transformed(TO_GLTF);
    parent.add(frame);

    // Each interface instance's name, in the middle of the ports it is made of:
    // one name for a bolt pattern of four holes, as the 2D tab's picture writes
    // it, rather than the same name four times. On the node rather than on a
    // port, so whether it shows is worked out from the rows of the instance and
    // of its ports ('refreshInterfaceCallouts').
    groupPorts(node).interfaces.forEach((entry, index) => {
        if (entry.ports.length === 0) {
            return;
        }
        const middle = [0, 1, 2].map(
            (axis) => entry.ports.reduce((sum, port) => sum + ports[port].location[0][axis], 0) / entry.ports.length,
        );
        const { object } = calloutObject('callout-interface', [interfaceLabel(entry.interface)]);
        object.position.set(middle[0], middle[1], middle[2]);
        frame.add(object);
        made.interfaces.push({
            object,
            item: interfaceId(path, index),
            ports: entry.ports.map((port) => portId(path, port)),
        });
    });

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

        // Its name, at the tip of the +Z axis - the end of the triad that says
        // which way the port faces, and where the 2D tab's picture joins a
        // port's name to it. A child of the triad, so the port's own box hides it.
        const name = portLabel(port);
        if (name) {
            const { object } = calloutObject('callout-port', [name]);
            object.position.set(0, 0, size);
            object.visible = labelChoices.portNames;
            axes.add(object);
            made.ports.push(object);
        }

        const sketch = port.sketch ? sketches.get(port.sketch) : undefined;
        if (sketch === undefined) {
            return;
        }
        // Cloned per port, so forty holes drawn with one circle upload one
        // geometry and draw forty instances of it.
        const boundary = transformed(placement(port.location));
        // Its lines too: a boundary drawn as an outline - a sketch of edges
        // alone - is as much the port's as a filled one, and in the model's
        // colour it would read as part of the model.
        const drawn = sketch.clone();
        drawn.traverse((child) => {
            const mesh = child as THREE.Mesh | THREE.Line;
            if ((mesh as THREE.Mesh).isMesh) {
                mesh.material = material;
            } else if ((mesh as THREE.Line).isLine) {
                mesh.material = lineMaterial;
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
function addCallouts(parent: THREE.Group, node: ShowNode, path: number[], made: Callouts): void {
    const said = calloutsOf(node);
    if (said.length === 0) {
        return;
    }
    const frame = transformed(TO_GLTF);
    for (const callout of said) {
        const { object } = calloutObject('callout-metadata', callout.lines, callout.title);
        object.position.set(callout.position[0], callout.position[1], callout.position[2]);
        object.visible = showMetadata;
        frame.add(object);
        made.metadata.push(object);
    }
    parent.add(frame);
    drawnByItem(nodeId(path), frame);
}

/**
 * One component's callout: its name and its price, in the middle of its shape.
 *
 * A child of the shape itself, so the box that hides the component - and the
 * flicker that singles it out - takes its callout with it. Written by
 * 'refreshComponentCallouts', which is what the boxes and the prices arriving
 * call again; a component with nothing to say has its callout hidden.
 *
 * The middle is of the shape's box, measured in the shape's own frame: the
 * whole tree has had its placements composed before this is called, and the
 * box is taken back out of them.
 */
function addComponentCallout(node: ShowNode, drawn: THREE.Object3D, box: THREE.Box3, made: Callouts): void {
    if (box.isEmpty()) {
        return;
    }
    const middle = drawn.worldToLocal(box.getCenter(new THREE.Vector3()));
    const callout = calloutObject('callout-component', []);
    callout.object.position.copy(middle);
    drawn.add(callout.object);
    made.components.push({
        object: callout.object,
        box: callout.box,
        name: componentName(node),
        objectName: node.name ?? undefined,
        holds: false,
    });
}

/**
 * The callout of a node that holds others: its price, in the middle of
 * everything inside it, for an assembly sold assembled (see 'assemblyRows').
 *
 * It has no shape of its own to be a child of, so it hangs from a group of its
 * own under the node, registered under the node's item: the box that hides the
 * sub-assembly hides its price, and the callout's own 'visible' stays
 * 'refreshComponentCallouts''s to set.
 */
function addAssemblyCallout(node: ShowNode, path: number[], into: THREE.Group, box: THREE.Box3, made: Callouts): void {
    if (box.isEmpty()) {
        return;
    }
    const holder = new THREE.Group();
    into.add(holder);
    const callout = calloutObject('callout-component', []);
    callout.object.position.copy(into.worldToLocal(box.getCenter(new THREE.Vector3())));
    holder.add(callout.object);
    drawnByItem(nodeId(path), holder);
    made.components.push({
        object: callout.object,
        box: callout.box,
        name: componentName(node),
        objectName: node.name ?? undefined,
        holds: true,
    });
}

/**
 * Give what a glTF draws the materials this viewer draws everything with, in the
 * colour 'appearance' says - or, for a face primitive that brought a colour of
 * its own, in that.
 *
 * Part.js replaces whatever material the file carries with a plain
 * MeshPhongMaterial, which is what gives every PartCAD model the same look
 * regardless of how it was authored; the colour is the one thing a shape gets a
 * say in, through its properties or, face by face, through the colour of each
 * primitive of its file (see 'keepOwnColors'). The material is still this
 * viewer's either way, from 'geometry's one per colour, so a coloured face is
 * shaded, faded and singled out as every other face is. Lines get one of
 * their own: an edge that bounds no face - the bend lines of a sheet metal drawing
 * - arrives as glTF line segments, and a lit material means nothing to a line.
 *
 * 'replacing' says whether what is being replaced is the file's own material,
 * which nothing else holds and which goes with it, or one of 'geometry's, which
 * every other instance of the shape is still drawn with and must not.
 */
function paint(group: THREE.Object3D, geometry: Geometry, appearance: Appearance, replacing: boolean): void {
    group.traverse((child) => {
        const drawable = child as THREE.Mesh | THREE.Line;
        let material: THREE.Material;
        if ((drawable as THREE.Mesh).isMesh) {
            const own = drawable.userData[OWN_APPEARANCE] as Appearance | undefined;
            const map = ownTextures.get(drawable.geometry);
            material = geometry.faceMaterial(
                primitiveAppearance(own !== undefined && map !== undefined ? { ...own, map } : own, appearance),
            );
        } else if ((drawable as THREE.Line).isLine) {
            material = geometry.lineMaterial(appearance);
        } else {
            return;
        }
        const previous = drawable.material as THREE.Material | THREE.Material[] | undefined;
        drawable.material = material;
        if (replacing) {
            disposeMaterials(previous);
        }
    });
}

/**
 * Every distinct piece of geometry in this tree, parsed once and handed out per use.
 *
 * PartCAD sends the geometry as a table on the root with the nodes naming entries
 * in it (see 'messages.ts'), so this parses the table - not the tree - and a shape
 * the tree holds a hundred times is parsed, and uploaded to the GPU, once.
 *
 * And once across shows, too: what is parsed is a template the cache keeps by
 * digest ('geometryCache.ts'), so a shape this renderer has drawn before, and the
 * host has not had it let go of, is not parsed again - nor even sent again.
 *
 * 'take' is what turns one parsed group into what a node adds to the stage: a
 * clone of the template, for every node that names it. A clone is a fresh set of
 * Object3Ds over the *same* BufferGeometry, which is the whole point - one upload,
 * one material, one instance per node, and each node's own Object3D to switch on
 * and off. The template itself is never on the stage, so it is the same for the
 * next show as it was for this one. Every group handed out ends up under the
 * content group, and 'disposeTree' frees what of it is the show's when the show is
 * replaced; the geometry is the cache's, and stays.
 *
 * One material per colour for all of it, for the same reason: a material per node
 * is a material per node for the renderer to set up, and an assembly of a hundred
 * uncoloured parts is drawn with one. A node is painted in its colour as it is
 * handed out (see 'buildNode') rather than here, because the colour belongs to the
 * node - the same bolt can be stated red in one place and nothing in another - and
 * the geometry is shared between them.
 */
class Geometry {
    /** The templates this show draws, by digest, and the groups it parsed for itself (hand-written base64). */
    private readonly parsed = new Map<string, THREE.Group>();
    private readonly local = new Set<string>();
    /** The face and line materials of every colour this show has drawn in, by 'appearanceKey'. */
    private readonly faces = new Map<string, THREE.MeshPhongMaterial>();
    private readonly lines = new Map<string, THREE.LineBasicMaterial>();
    /** Any other material the show made, to be freed with these. */
    private readonly owned: THREE.Material[] = [];

    /**
     * 'side' is which sides of a face are drawn: both, unless the painter draws a
     * solid (see 'showGeometry').
     */
    constructor(private readonly side: THREE.Side) {}

    /**
     * The material the faces of a shape of this appearance are drawn with.
     *
     * Made the first time a colour is asked for, and only then, so a show makes
     * exactly the materials it draws with - and every one of them ends up on a
     * mesh under the content group, where 'disposeTree' finds it.
     *
     * A see-through colour is drawn transparent at its own opacity, and remembers
     * that opacity in 'userData.alpha' so the Opacity slider can take it as the
     * part's full strength rather than replacing it (see 'setOpacity').
     *
     * A one-sided shape - a wall - is drawn from the front of its faces only,
     * whatever this show draws everything else with: from behind it is not there,
     * which is the whole of what it is for (see 'appearance.ts').
     *
     * A colour drawn with an image is drawn with it, white under it - three
     * multiplies the two - and remembers the colour it is drawn as where an
     * image cannot be in 'userData.flatColor' (see 'painter.ts').
     */
    faceMaterial(appearance: Appearance): THREE.Material {
        const key = appearanceKey(appearance);
        let material = this.faces.get(key);
        if (material === undefined) {
            material = new THREE.MeshPhongMaterial({
                color: appearance.map === undefined ? appearance.color : 0xffffff,
                map: appearance.map ?? null,
                side: appearance.oneSided ? THREE.FrontSide : this.side,
                transparent: appearance.opacity < 1,
                opacity: appearance.opacity,
            });
            material.userData.alpha = appearance.opacity;
            material.userData.flatColor = appearance.color;
            this.faces.set(key, material);
        }
        return material;
    }

    /**
     * The material a line across a shape of this appearance is drawn with.
     *
     * A deeper shade of the face colour ('edgeColor'), so that a line lying on a
     * face - a bend line across the blank it bends - reads against it, and unlit
     * and not tone-mapped so that it is that shade on a light theme and a dark one
     * alike.
     */
    lineMaterial(appearance: Appearance): THREE.Material {
        const key = appearanceKey(appearance);
        let material = this.lines.get(key);
        if (material === undefined) {
            material = new THREE.LineBasicMaterial({
                color: edgeColor(appearance.color),
                toneMapped: false,
                transparent: appearance.opacity < 1,
                opacity: appearance.opacity,
            });
            material.userData.alpha = appearance.opacity;
            this.lines.set(key, material);
        }
        return material;
    }

    /**
     * Parse the table - what of it the cache does not hold parsed already -
     * reporting progress as it goes. Returns what failed to parse.
     *
     * The file's own materials go as a shape is parsed (see 'parseTemplate'), and
     * every node is painted as it is handed out, in its own colour or the
     * default one (see 'paint'), on both sides of every face. A part is a closed
     * solid and would look the same either way, but a sketch and a port's
     * boundary are laminae: drawn front-side only, one whose face winds away from
     * the camera is not drawn at all, and the camera orbits past both sides of
     * it. Nothing says which way a sketch's one face points - the ones in
     * 'examples' happen to point up.
     */
    async load(root: ShowNode, total: number, superseded: () => boolean): Promise<number> {
        let failed = 0;
        let bytes = 0;
        const missing: string[] = [];
        for (const [digest, entry] of Object.entries(root.geometry ?? {})) {
            try {
                if (typeof entry.gltf === 'string') {
                    // Hand-written: parsed for this show alone, painted with its
                    // materials, and freed with it like anything else it drew.
                    const group = await parseGltf(bufferOf(entry.gltf));
                    paint(group, this, DEFAULT_APPEARANCE, true);
                    this.parsed.set(digest, group);
                    this.local.add(digest);
                } else {
                    const group = await templates.parsed(digest, parseTemplate);
                    if (group === undefined) {
                        missing.push(digest);
                    } else {
                        this.parsed.set(digest, group);
                    }
                }
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
        if (missing.length > 0) {
            // Named, not sent, and not here: the host thought this renderer held
            // them. It posts the show again with them; until then they are
            // nodes with nothing to draw.
            geometryMissing({ type: 'geometryMissing', digests: missing });
            failed += missing.length;
        }
        return failed;
    }

    has(digest: string): boolean {
        return this.parsed.has(digest);
    }

    /** What the node naming 'digest' should add to the stage, or undefined. */
    take(digest: string): THREE.Group | undefined {
        return this.parsed.get(digest)?.clone();
    }

    /** The cache's templates this show draws: what must not be freed while it is on the stage. */
    templates(): THREE.Group[] {
        return [...this.parsed].filter(([digest]) => !this.local.has(digest)).map(([, group]) => group);
    }

    /**
     * What this show parsed for itself, and its materials - only reached when a
     * show is dropped. The cache's templates stay: they are the next show's too.
     */
    dispose(): void {
        for (const digest of this.local) {
            const group = this.parsed.get(digest);
            if (group !== undefined) {
                disposeTree(group);
            }
        }
        this.parsed.clear();
        this.local.clear();
        this.disposeMaterials();
    }

    /**
     * Every material this show made, whether or not anything is still drawn with it.
     *
     * 'disposeTree' frees the ones on a mesh of the content group, and that is all
     * of them but one kind: the default material a shape was given as it was
     * parsed, when every node naming it was then painted in a colour of its own.
     * Nothing holds that one, so it is freed here, when the show is replaced.
     * 'dispose()' is idempotent, so a material 'disposeTree' already freed costs
     * nothing.
     */
    disposeMaterials(): void {
        this.faces.forEach((material) => material.dispose());
        this.lines.forEach((material) => material.dispose());
        this.owned.forEach((material) => material.dispose());
        this.faces.clear();
        this.lines.clear();
        this.owned.length = 0;
    }

    /** Free 'material' with the rest of this show's (see 'disposeMaterials'). */
    own(material: THREE.Material): void {
        this.owned.push(material);
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
            const group = await parseGltf(bufferOf(sketch.gltf));
            // The file's materials go; its faces and its lines are given the
            // boundary's per port, in 'addPorts'.
            paint(group, geometry, DEFAULT_APPEARANCE, true);
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
    built: { node: ShowNode; path: number[]; group: THREE.Group; drawn?: THREE.Group }[];
}

/**
 * One node as a group, with its geometry, its children and its ports inside it.
 *
 * The group carries the node's own placement, so the tree's locations compose the
 * way PartCAD states them and the way the BREP form realizes them - nothing is
 * baked into the geometry. Returns null once a newer show has superseded this
 * one, having disposed whatever it had built.
 *
 * 'inherited' is what the node holding this one is drawn as. A node that states a
 * colour of its own is drawn in it, and hands it on to its children in turn (see
 * 'appearance.ts').
 */
async function buildNode(
    node: ShowNode,
    path: number[],
    superseded: () => boolean,
    loaded: Loaded,
    geometry: Geometry,
    inherited: Appearance = DEFAULT_APPEARANCE,
): Promise<THREE.Group | null> {
    const group = transformed(placement(node.location));
    group.name = node.label || node.name || nodeId(path);
    const appearance = appearanceOf(node, inherited);

    // Already parsed: the geometry of every node arrived in one table and was
    // parsed before the tree was walked, so what is left here is to take an
    // instance of it and put it where this node sits.
    let drawn: THREE.Group | undefined;
    if (node.gltfRef !== undefined) {
        drawn = geometry.take(node.gltfRef);
        if (drawn === undefined) {
            // Its entry failed to parse; reported once, where that happened.
            loaded.failed += 1;
        } else {
            // Every instance, the default-coloured ones included: a clone is
            // cloned from the first instance handed out, materials and all, so a
            // bolt cloned after a red one would otherwise come out red too.
            paint(drawn, geometry, appearance, false);
        }
    } else if (node.gltf !== undefined) {
        // A node carrying its geometry outright, which PartCAD no longer sends and
        // a hand-written message still can.
        try {
            drawn = await parseGltf(bufferOf(node.gltf));
            paint(drawn, geometry, appearance, true);
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
        const child = await buildNode(children[index], [...path, index], superseded, loaded, geometry, appearance);
        if (child === null) {
            disposeTree(group);
            return null;
        }
        group.add(child);
    }

    loaded.built.push({ node, path, group, drawn });
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
    //
    // The software renderer orders whole triangles by their depth rather than each
    // pixel, and a long thin triangle on the far side of a solid is drawn over the
    // near side often enough to stripe it. A solid is closed, so its far side is
    // never what is seen: drawn front-side only, it is not drawn at all. A sketch
    // is a lamina that is seen from both sides, and keeps both (see
    // 'Geometry.load').
    const geometry = new Geometry(software && message.kind !== 'sketch' ? THREE.FrontSide : THREE.DoubleSide);
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
    // (PBR Neutral) everything that does not say otherwise. A lit material would
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
    // The same, for a boundary drawn as an outline: the port's blue, unlit, and
    // left alone by the slider.
    const boundaryLineMaterial = new THREE.LineBasicMaterial({ color: PORT_COLOR, toneMapped: false });
    boundaryLineMaterial.userData.annotation = true;
    // Owned by the show's geometry, so that whichever of the two no port turned
    // out to draw with is freed with the rest of the show's materials.
    geometry.own(boundaryMaterial);
    geometry.own(boundaryLineMaterial);
    // Every placement composed once, so that each component's box below is
    // measured where the tree puts it and taken back out of it consistently.
    group.updateMatrixWorld(true);
    // The box of what each node holds, on the stage: its own shape's and its
    // children's, measured before any port is added under it. 'built' lists the
    // children before the node that holds them, so one pass does it.
    const held = new Map<string, THREE.Box3>();
    for (const { node, path, drawn } of loaded.built) {
        const box = drawn !== undefined ? new THREE.Box3().setFromObject(drawn) : new THREE.Box3();
        (node.assembly ?? []).forEach((_child, index) => {
            const inner = held.get([...path, index].join('.'));
            if (inner !== undefined) {
                box.union(inner);
            }
        });
        held.set(path.join('.'), box);
    }
    const made = noCallouts();
    for (const { node, path, group: into, drawn } of loaded.built) {
        const box = held.get(path.join('.')) ?? new THREE.Box3();
        addPorts(into, node, path, size, sketches, boundaryMaterial, boundaryLineMaterial, made);
        addCallouts(into, node, path, made);
        if (isComponent(node)) {
            if (drawn !== undefined) {
                addComponentCallout(node, drawn, box, made);
            }
        } else {
            addAssemblyCallout(node, path, into, box, made);
        }
    }
    refreshComponentCallouts(made);
    refreshInterfaceCallouts(made);

    if (superseded()) {
        disposeTree(group);
        geometry.dispose();
        return;
    }
    // What the cache let go of goes now, unless this show draws it too: the show
    // it replaces is taken off the stage below, before anything is drawn again.
    templates.use(geometry.templates());

    // A cut of the object on screen, or the whole of it after a cut: kept where
    // the object was, rather than centred on what is left of it (see 'frame()').
    const cut = Boolean(message.section);
    const centred =
        message.keepCamera && (cut || shownCut) && content !== undefined ? content.position.clone() : undefined;
    // Nothing on the stage yet: the camera starts at the opening view. Anything
    // after that keeps the camera where it is - its angle above all, which
    // Animate has been turning - and fits it to what arrived, gradually.
    const first = content === undefined;
    if (content !== undefined) {
        scene.remove(content);
        disposeTree(content);
    }
    shownGeometry?.disposeMaterials();
    shownGeometry = geometry;
    content = group;
    callouts = made;
    shownCut = cut;
    scene.add(group);
    // Framed on every shape the show carries, whether or not it is switched on:
    // the camera has to stay where it is when an item is unchecked, and a model
    // that reframed itself on every checkbox would be unusable.
    //
    // On the shapes and not on what is drawn on them: a triad is an 'AxesHelper',
    // which reaches a quarter of the model out along +X, +Y and +Z and nowhere
    // else, so a box that counts them leans toward every port's positive axes -
    // and the ports of everything inside an assembly start out unticked, which
    // is a model centred on something nobody can see. An interface has no shape
    // but its ports, and is framed on those.
    frame(group, geometryBox.isEmpty() ? new THREE.Box3().setFromObject(group) : geometryBox, first, centred);
    // Every show of another object after the first is fitted, over a second,
    // from where the camera is ('fit'); and so is the same one again - an edit
    // saved, an agent's next version of it, which may have grown or shrunk -
    // while Auto-fit is on. With it off, the same object again keeps the camera
    // where it was put, as it did before there was a fit at all - and a fit still
    // on its way from showing another object, less than a second ago, carries on
    // to the new version of it: nobody has put the camera anywhere on that object
    // yet (taking hold of the view would have stopped the fit), and stopping it
    // there would leave a view between the two objects' that nobody chose.
    //
    // Not a cut or the show that takes one away, which keeps the camera still
    // for the reason it keeps the model where it was: the slider is moving
    // through the object, and the view moving under it is two things moving.
    // That includes a fit still on its way from the show before: 'frame' has
    // just pointed it at the cut, so it stops where it is, as it does when
    // somebody takes hold of the view.
    if (centred !== undefined) {
        fitting = undefined;
    } else if (!first && (!message.keepCamera || autoFit)) {
        fit();
    }
    viewListeners.forEach((listener) => listener());
    buildProxies(group);
    invalidate();

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

    // Performance logging (behind config flag)
    const perfDebug = (window as any).partcadConfig?.viewer?.performanceDebug ?? false;
    const nodeTriangleCounts = new Map<string, number>();

    if (!perfDebug) {
        delete (window as any).pcNodeTriangleCounts;
        const statsDisplay = (window as any).pcViewerStats?.statsDisplay;
        if (statsDisplay) {
            statsDisplay.remove();
            (window as any).pcViewerStats.statsDisplay = null;
        }
    }

    // Diagnostic: Scene structure profiling
    if (perfDebug) {
        let totalMeshes = 0;
        const materialCounts = new Map<THREE.Material, number>();
        group.traverse((obj) => {
            if ((obj as THREE.Mesh).isMesh) {
                totalMeshes++;
                const material = (obj as THREE.Mesh).material as THREE.Material | undefined;
                if (material) {
                    materialCounts.set(material, (materialCounts.get(material) ?? 0) + 1);
                }
            }
        });
        const topLevelNodes = loaded.built.length;
        const avgMeshesPerNode = topLevelNodes > 0 ? (totalMeshes / topLevelNodes).toFixed(1) : '0';
        const materialDistribution: Record<string, number> = {};
        let materialIndex = 0;
        for (const [mat, count] of materialCounts) {
            materialDistribution[`Material${materialIndex++}`] = count;
        }
        console.log('[Digital Thread] Scene Structure:', {
            totalMeshes,
            topLevelNodes,
            avgMeshesPerNode,
            materials: materialCounts.size,
            ...materialDistribution,
        });
    }

    if (perfDebug) {
        // Count triangles per node (excluding child node groups)
        for (const { node, path, group: nodeGroup } of loaded.built) {
            let nodeTriangles = 0;
            nodeGroup.children.forEach((child: any) => {
                // Skip groups that represent child nodes (they have their own loaded.built entries)
                if (child.isMesh && child.geometry) {
                    if (child.geometry.index) {
                        nodeTriangles += child.geometry.index.count / 3;
                    } else {
                        nodeTriangles += child.geometry.attributes.position.count / 3;
                    }
                }
            });
            const id = nodeId(path);
            const count = Math.round(nodeTriangles);
            nodeTriangleCounts.set(id, count);
        }
        // Store for access by tree display
        (window as any).pcNodeTriangleCounts = nodeTriangleCounts;

        const stats = {
            name: message.name || '(unnamed)',
            kind: message.kind || 'object',
            package: message.package || '(local)',
            triangleCount: 0,
            vertexCount: 0,
            bytesTransferred: total,
        };
        group.traverse((obj: any) => {
            if (obj.isMesh && obj.geometry) {
                if (obj.geometry.index) {
                    stats.triangleCount += obj.geometry.index.count / 3;
                } else {
                    stats.triangleCount += obj.geometry.attributes.position.count / 3;
                }
                stats.vertexCount += obj.geometry.attributes.position.count;
            }
        });
        const perfLog = {
            part: stats.name,
            type: stats.kind,
            package: stats.package,
            totalTriangles: stats.triangleCount.toFixed(0),
            totalVertices: stats.vertexCount.toFixed(0),
            dataTransferredKB: (stats.bytesTransferred / 1024).toFixed(2),
        };
        console.log('[Digital Thread] Performance Stats:', perfLog);

        // Create on-screen stats display
        if (!(window as any).pcViewerStats) {
            (window as any).pcViewerStats = {
                lastLogTime: performance.now(),
                statsDisplay: null,
                geometryInfo: '',
            };
        }
        if (!(window as any).pcViewerStats.statsDisplay) {
            const div = document.createElement('div');
            div.style.cssText = `
                position: fixed;
                top: 10px;
                right: 10px;
                background: rgba(0, 0, 0, 0.7);
                color: #00ff00;
                font-family: monospace;
                font-size: 12px;
                padding: 10px;
                border-radius: 4px;
                pointer-events: none;
                z-index: 1000;
                white-space: pre;
                line-height: 1.4;
            `;
            document.body.appendChild(div);
            (window as any).pcViewerStats.statsDisplay = div;
        }
        const geometryInfo = `${stats.name} (${stats.kind})\n${stats.triangleCount.toFixed(0)} triangles\n${(stats.bytesTransferred / 1024).toFixed(1)}KB`;
        (window as any).pcViewerStats.geometryInfo = geometryInfo;
        (window as any).pcViewerStats.statsDisplay.textContent = geometryInfo;
    }
}

/**
 * The 3D view as a PNG data URL, for `pc ide state`.
 *
 * Drawn first and read in the same task: a WebGL canvas made without
 * 'preserveDrawingBuffer' -- which this one is, because keeping the buffer costs
 * every frame -- is blank to 'toDataURL' once the frame it drew has been shown.
 * The callouts are DOM over the canvas rather than pixels in it, so they are
 * not in the picture.
 */
export function screenshot(): string {
    const canvas = surface.domElement;
    if (!(canvas instanceof HTMLCanvasElement)) {
        throw new Error('the 3D view is not drawn on a canvas');
    }
    surface.render(scene, camera);
    return canvas.toDataURL('image/png');
}

/**
 * Size the drawing buffer and the camera to the canvas as it is laid out now, and
 * fit the camera again if it has not been moved since it was fitted ('fittedTo').
 * A canvas with no size - its tab hidden - is left as it was.
 */
export function resizeCanvas(): void {
    const width = container.clientWidth;
    const height = container.clientHeight;
    if (width === 0 || height === 0) {
        return;
    }
    surface.setSize(width, height);
    labelRenderer.setSize(width, height);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    if (fittedTo !== undefined) {
        // Fitted again at the angle the turntable has it at now, along the line
        // it looks down: nearer or further, but not turned.
        const length = fitDistance(fittedTo, camera.fov, camera.aspect);
        camera.position.sub(controls.target).setLength(length).add(controls.target);
        clip(length);
    }
    invalidate();
}

/** How the stage relates to PartCAD's frame: glTF's, with the model moved to the middle. */
function stageFrame(): SceneFrame {
    const offset = content?.position ?? new THREE.Vector3();
    return { size: MM_TO_M, yUp: true, offset: [offset.x, offset.y, offset.z] };
}

/** Where the camera is looking from, in PartCAD's frame; undefined with nothing on the stage. */
export function viewpoint(): Viewpoint | undefined {
    if (content === undefined) {
        return undefined;
    }
    return readViewpoint(camera, controls.target, stageFrame());
}

/** Look from where 'viewpoint' says, at what it says, as the view panel asks. */
export function setViewpoint(viewpoint: Viewpoint): void {
    if (content === undefined) {
        return;
    }
    // Put there on purpose, like a drag: a fit on its way stops, and a resize
    // leaves it where it is rather than fitting it again (see 'fittedTo').
    fitting = undefined;
    aimCamera(camera, controls.target, viewpoint, stageFrame());
    fittedTo = undefined;
    // The orbit controls take it from here; their 'change' tells the panel.
    controls.update();
    invalidate();
}

/**
 * What the model on the stage occupies, in PartCAD's frame, or undefined.
 *
 * For an object whose tree says nothing about its size: the view panel's
 * section sliders span this instead. Measured on what is drawn, so it is asked
 * only of a show of the whole object.
 */
export function modelBounds(): Bounds | undefined {
    if (content === undefined || shownCut) {
        return undefined;
    }
    const box = new THREE.Box3().setFromObject(content);
    if (box.isEmpty()) {
        return undefined;
    }
    const frame = stageFrame();
    const corners = [box.min, box.max].map((corner) => fromStage([corner.x, corner.y, corner.z], frame));
    return {
        min: [0, 1, 2].map((axis) => Math.min(corners[0][axis], corners[1][axis])) as Bounds['min'],
        max: [0, 1, 2].map((axis) => Math.max(corners[0][axis], corners[1][axis])) as Bounds['max'],
    };
}

export function setAutoRotate(enabled: boolean): void {
    autoRotate = enabled;
    controls.autoRotate = enabled;
    invalidate();
}

/** Whether a show of the same object again is fitted, as the Auto-fit box says (see 'autoFit'). */
export function setAutoFit(enabled: boolean): void {
    autoFit = enabled;
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
 *
 * A part that states a see-through colour ("#RRGGBBAA") is a part whose full
 * strength is that, and the slider scales it rather than replacing it: at 100% it
 * is as see-through as it says, and at 50% half as opaque again.
 */
export function setOpacity(opacity: number): void {
    if (content === undefined) {
        return;
    }
    const apply = (material: THREE.Material) => {
        if (material.userData.annotation === true) {
            return;
        }
        const alpha = typeof material.userData.alpha === 'number' ? material.userData.alpha : 1;
        material.transparent = true;
        material.opacity = opacity * alpha;
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
    invalidate();
}

function animate(): void {
    const now = performance.now();
    const moved = spaceMouse.drive(navigable, now);
    // The model turning on its own while somebody is turning it by hand is two
    // hands on one wheel; it resumes when the cap is let go.
    controls.autoRotate = autoRotate && !moved;
    if (moved) {
        invalidate();
    }
    stepFit(now);
    controls.update();
    if (flickering !== undefined) {
        // A flicker is a change on every frame it lasts.
        invalidate();
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
    // Nothing moved and nothing changed: the picture on screen is still it.
    const draws = dirty;
    let drawTime = 0;
    if (draws) {
        dirty = false;
        const started = performance.now();
        drawStage();
        labelRenderer.render(scene, camera);
        drawTime = performance.now() - started;
    }
    reportFrameRate(now, draws, drawTime);
}

/**
 * The performance readout, behind 'viewer.performanceDebug': once a second, how
 * many frames were drawn in it and how long one took to draw.
 *
 * Counted on every frame, drawn or not, since a frame that draws nothing is the
 * idle stage this readout has to be able to show: '0 drawn/s', and not the rate
 * of the last second something moved.
 */
function reportFrameRate(now: number, drawn: boolean, drawTime: number): void {
    const perfDebug = (window as any).partcadConfig?.viewer?.performanceDebug ?? false;
    if (!perfDebug) {
        return;
    }
    if (!(window as any).pcViewerStats) {
        (window as any).pcViewerStats = {
            lastLogTime: now,
            statsDisplay: null,
            geometryInfo: '',
        };
    }
    const stats = (window as any).pcViewerStats;
    stats.lastLogTime ??= now;
    stats.drawnFrames = (stats.drawnFrames ?? 0) + (drawn ? 1 : 0);
    stats.drawTime = (stats.drawTime ?? 0) + drawTime;

    const elapsed = now - stats.lastLogTime;
    if (elapsed <= 1000) {
        return;
    }
    const fps = (stats.drawnFrames * 1000) / elapsed;
    const perDraw = stats.drawnFrames > 0 ? stats.drawTime / stats.drawnFrames : 0;
    console.log(`[Digital Thread] Drawn: ${fps.toFixed(1)} frames/s (draw time: ${perDraw.toFixed(2)}ms)`);

    // Update on-screen display with the frame rate and graphics info
    const renderInfo = surface.info?.render ?? { calls: 0, triangles: 0 };
    const memInfo = surface.info?.memory ?? { geometries: 0, textures: 0 };
    if (stats.statsDisplay) {
        const fpsInfo = `\nDrawn: ${fps.toFixed(1)}/s | Draw: ${perDraw.toFixed(1)}ms`;
        const graphicsInfo = `\nDraw Calls: ${renderInfo.calls} | Geometries: ${memInfo.geometries}`;
        stats.statsDisplay.textContent = stats.geometryInfo + fpsInfo + graphicsInfo;
    }
    console.log('[Digital Thread] Graphics Stats:', {
        drawCalls: renderInfo.calls,
        triangles: renderInfo.triangles,
        geometries: memInfo.geometries,
        textures: memInfo.textures,
    });
    stats.lastLogTime = now;
    stats.drawnFrames = 0;
    stats.drawTime = 0;
}

/** The boxes a big model is drawn as while it is being moved, or undefined. */
let proxies: THREE.Group | undefined;

function dropProxies(): void {
    if (proxies !== undefined) {
        disposeBoxes(proxies);
        proxies = undefined;
    }
}

/**
 * On the software renderer, and for a model over the budget: a box per mesh, in
 * place, each in the colour of the part it stands for.
 */
function buildProxies(group: THREE.Group): void {
    dropProxies();
    if (!software || trianglesOf(group) <= SOFTWARE_TRIANGLE_BUDGET) {
        return;
    }
    proxies = boxesOf(group);
    scene.add(proxies);
}

if (software) {
    controls.addEventListener('start', () => {
        if (proxies !== undefined && content !== undefined) {
            content.visible = false;
            proxies.visible = true;
        }
    });
    controls.addEventListener('end', () => {
        if (proxies !== undefined && content !== undefined) {
            content.visible = true;
            proxies.visible = false;
        }
        invalidate();
    });
}

// The canvas, and not the window: the canvas changes size without the window
// doing so - the control pane appears with the first show, a strip of tabs over
// it appears or goes, the view panel comes out or folds away - and a renderer
// that is not told draws the old size stretched over the new one.
// On the next frame rather than in the observer: resizing the canvas from inside
// it is a size change the observer is then told about in the same frame, which
// the browser reports as an error - and 'host.ts' as the panel failing to start.
new ResizeObserver(() => requestAnimationFrame(resizeCanvas)).observe(container);
resizeCanvas();
if (surface.setAnimationLoop !== undefined) {
    surface.setAnimationLoop(animate);
} else {
    const loop = () => {
        animate();
        requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
}
