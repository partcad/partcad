//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// An answer about the object on screen that has to wait for its geometry.
//
// Some of what the 3D view is told about an object is pinned to the object's own
// tree on the stage - the clusters of each material name its nodes and points in
// its frame - and is asked as soon as the panel knows which object it is, which
// can be before the scene has put that object's geometry on the stage: a box
// ticked while a large model is still loading. An answer that arrives then has
// nothing to be pinned to yet. Handed to the scene there, it would be pinned to
// whatever is still on the stage and thrown away with it, and since the show has
// asked already, nothing would ask again.
//
// So the answer is held, for the show it is about, and handed over once that
// show's geometry is on the stage. A newer show forgets it: the request for it
// was dropped by its token, and the next show asks afresh.
//
// Free of three.js, so that it can be tested outside a browser.
//

/** One answer for the show on screen, handed to 'apply' once its geometry is on the stage. */
export class HeldForShow<T> {
    private value: T | undefined;
    private staged = false;

    constructor(private readonly apply: (value: T) => void) {}

    /** Another show has begun: nothing is known about it, and its geometry is not on the stage yet. */
    public reset(): void {
        this.value = undefined;
        this.staged = false;
    }

    /** The show's geometry is on the stage: what arrived for it meanwhile goes on it now. */
    public onStage(): void {
        this.staged = true;
        if (this.value !== undefined) {
            this.apply(this.value);
        }
    }

    /** The answer, for the show on screen: applied now if its geometry is on the stage, else once it is. */
    public arrive(value: T): void {
        this.value = value;
        if (this.staged) {
            this.apply(value);
        }
    }
}
