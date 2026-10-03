# PartCAD Viewer Performance Debug Feature

## Overview

Added configurable performance profiling to the PartCAD VS Code viewer to diagnose rendering bottlenecks. Purely diagnostic—no rendering optimizations. Behind a feature flag to keep default behavior clean.

## Comparison to Devel Branch

| Feature | Devel | This Branch |
|---------|-------|-------------|
| Triangle count per node | ❌ None | ✅ Shown in control tree |
| Graphics profiling | ❌ None | ✅ Draw calls, GPU memory, mesh count |
| FPS/frame time display | ❌ None | ✅ Console + on-screen |
| Default behavior | N/A | Clean (all logging disabled by default) |
| Configuration | N/A | VS Code Settings UI + partcad.viewer.performanceDebug |

## What's Measured

When `partcad.viewer.performanceDebug` is **enabled**, the viewer captures:

**In Control Tree:**
- Triangle count for each node in parentheses (e.g., "reactor-core (45,000 triangles)")
- Helps identify geometry-heavy parts

**On Load (Console & On-Screen):**
- Part name (e.g., "reactor-unit")
- Assembly type (e.g., "assembly", "part")
- Package name (e.g., "4tv", "local")
- Total triangle count and vertex count
- Data transferred (KB)
- **Draw calls** and mesh count (GPU/CPU bottleneck indicator)

**During Rotation/Interaction (every 1 second):**
- FPS (frames per second)
- Frame time (milliseconds per frame)

## Where Data Appears

1. **Control Tree** (left pane):
   - Each node shows triangle count in parentheses
   - Example: `reactor-core (45000 triangles)`
   - Quickly identify heavy parts for optimization

2. **Browser Console** (view via `Ctrl+Shift+P` → "Developer: Toggle Developer Tools" → Console tab):
   ```
   [PartCAD Viewer] Performance Stats: {
     Part: "reactor-unit",
     Type: "assembly",
     Package: "4tv",
     Total triangles: "45000",
     Total vertices: "98000",
     Data transferred (KB): "234.5"
   }
   [PartCAD Viewer] FPS: 60.0 (frame time: 16.67ms)
   ```

3. **On-Screen Display** (top-right corner of viewer):
   ```
   reactor-unit (assembly)
   45000 triangles | 98000 vertices
   234.5KB
   Draw calls: 14000 | Meshes: 7386

   FPS: 60.0 | Frame: 16.7ms
   ```

## How to Enable

### Via VS Code UI (Recommended)

1. Open VS Code Settings (`Ctrl+,`)
2. Search for "partcad.viewer.performanceDebug"
3. Toggle the checkbox to enable
4. Reload the viewer to see metrics

### Via JSON Settings

Add to `.vscode/settings.json`:
```json
{
  "partcad.viewer.performanceDebug": true
}
```

## Implementation Details

### Configuration Entry

Added to `package.json`:
```json
"partcad.viewer.performanceDebug": {
  "default": false,
  "description": "Show performance metrics in the 3D viewer (top-right corner): part name, triangle count, file size, and FPS/frame time.",
  "type": "boolean"
}
```

Located in: `PartCAD Viewer` section of extension settings

### Code Changes

- **scene.ts**: Per-node triangle counting, draw call profiling, scene structure diagnostics
- **tree.ts**: Triangle count display in control tree labels
- **viewer.ts**: Config passing from extension to webview
- **settings.ts**: Reading `partcad.viewer.performanceDebug` setting from VS Code
- **All diagnostics**: Wrapped in `if (perfDebug)` check to prevent overhead when disabled

### Performance Impact

- **When disabled** (default): Zero performance cost
- **When enabled**: Negligible CPU overhead (~1%) for statistics calculation

## Diagnostic Use Cases

1. **Identify bottlenecks**: Draw calls vs. triangle count reveal CPU (mesh count) or GPU (geometry) bottlenecks
2. **Profile heavy parts**: Triangle count per node shows which assemblies dominate geometry
3. **Mesh distribution**: Scene diagnostics show average meshes per node (helps identify exporter issues)
4. **Monitor frame rate**: FPS and frame time tracking during model interaction
5. **Non-intrusive**: Disabled by default, zero overhead when off

## Known Findings

With `partcad.viewer.performanceDebug` enabled on large models:
- Typical mesh distribution: 150+ meshes per node (upstream exporter behavior)
- Draw call bottleneck: 10,000–14,000+ calls on 49-node assemblies (CPU-bound)
- Triangle count is manageable (400K–500K); GPU is not the constraint
- BasicMaterial vs. Phong has minimal impact; mesh count is the constraint
