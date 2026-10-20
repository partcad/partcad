#
# PartCAD, 2026
#
# Author: PartCAD (support@partcad.org)
#
# Licensed under Apache License, Version 2.0.
#

import json
import pathlib
import sys

# The tools are scripts rather than an installed package: they run inside a
# build, from a checkout, with nothing installed but their dependencies.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import patch_workbench  # noqa: E402  (the path has to be set up first)

# So that the test modules beside this one can `from conftest import ...`.
#
# Under pytest's default "prepend" import mode this file is already in
# `sys.modules` as `conftest` and the line does nothing. Under `--import-mode
# importlib` -- which is what `pyproject.toml` sets repository-wide, and what
# every `pytest` run that does not pass `-o addopts=` therefore uses -- it is
# imported under a generated name instead, no directory goes on `sys.path`, and
# every module here dies at collection with `ModuleNotFoundError: No module
# named 'conftest'`. Codecov has been recording exactly that against `main`.
sys.modules.setdefault("conftest", sys.modules[__name__])

# Three levels up: this file is <repo>/ide/standalone/tests/conftest.py. The
# component used to sit one level shallower, at <repo>/partcad-ide-standalone/.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
COMPONENT_ROOT = pathlib.Path(__file__).resolve().parents[1]

# The two pieces of the minified workbench `patch_workbench.py` substitutes in,
# exactly as VSCodium 1.140 ships them, with enough around them to run under
# Node: `test_patch_workbench.py` runs the patched code rather than only reading
# it. The editor's own registrations, which name their container with a string
# literal, are here to show that they are not what the patterns match.
WORKBENCH_JS = (
    "var is=s=>s==null,F=(n,s)=>s;class ti{constructor(o,e){this.ctor=o,this.args=e}}class Pd{}"
    "var registry={registerViewContainer:(o,e)=>o};"
    'var ts=registry.registerViewContainer({id:"workbench.panel.testResults",title:F(25042,"Test Results"),'
    'ctorDescriptor:new ti(Pd,["workbench.panel.testResults",{mergeViewWithContainerWhenSingleView:!0}]),'
    "hideIfEmpty:!0,order:3},1);"
    "class Handler{constructor(){this.viewContainersRegistry={get:o=>{},registerViewContainer:(o,e)=>o}}"
    "registerCustomViewContainer(o,e,t,i,n,r){let a=this.viewContainersRegistry.get(o);return a||(a=this."
    "viewContainersRegistry.registerViewContainer({id:o,title:{value:e,original:e},extensionId:n,ctorDescriptor:"
    "new ti(Pd,[o,{mergeViewWithContainerWhenSingleView:!0}]),hideIfEmpty:!0,order:i,icon:t},r)),a}"
    "deregisterCustomViewContainer(o){}}"
    "class Model{constructor(o){this.items=o}findItem(o){return this.items.find(e=>e.id===o)}"
    "createCompositeBarItem(o,e,t,i,n){return{id:o,name:e,order:t,pinned:i,visible:n}}"
    "add(o,e,t,i){let n=this.findItem(o);if(n){let r=!1;return n.name=e,is(t)||(r=n.order!==t,n.order=t),"
    "n.visible||(n.visible=!0,r=!0),r}else{let r=this.createCompositeBarItem(o,e,t,!0,!0);if(is(i))if(is(t))"
    'this.items.push(r);else{let a=0;for(;a<this.items.length&&typeof this.items[a].order=="number"&&'
    "this.items[a].order<t;)a++;this.items.splice(a,0,r)}else{let a=0,c=i;for(;c>0&&a<this.items.length;)"
    "this.items[a++].visible&&c--;this.items.splice(a,0,r)}return!0}}remove(o){}}\n"
)
WORKBENCH_CSS = ".monaco-workbench{color:red}\n/*# sourceMappingURL=workbench.desktop.main.css.map*/\n"


def write_workbench(app_dir, js=WORKBENCH_JS, css=WORKBENCH_CSS):
    """An unpatched workbench under `<app_dir>/out`, with its checksums in `<app_dir>/product.json`."""
    for name, text in ((patch_workbench.WORKBENCH_JS, js), (patch_workbench.WORKBENCH_CSS, css)):
        path = app_dir / "out" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    product_path = app_dir / "product.json"
    product = json.loads(product_path.read_text(encoding="utf-8")) if product_path.is_file() else {}
    product["checksums"] = {
        name: patch_workbench.checksum(app_dir / "out" / name)
        for name in (patch_workbench.WORKBENCH_JS, patch_workbench.WORKBENCH_CSS)
    }
    product_path.write_text(json.dumps(product), encoding="utf-8")
