//@ts-check
//
// PartCAD, 2024
//
// Author: Roman Kuzmenko
// Created: 2024-12-28
//
// Licensed under Apache License, Version 2.0.
//


(function () {
  // @ts-expect-error
  const vscode = acquireVsCodeApi();

  /**
   * The value as text rather than as markup.
   *
   * A path, a description or a hash reaches this view from a package's
   * configuration, and a package can be somebody else's: the content security
   * policy above keeps injected markup from running, but nothing else keeps it
   * from wrecking the table it is put in.
   */
  function escapeHtml(value) {
    const div = document.createElement('div');
    div.textContent = value === undefined || value === null ? '' : String(value);
    return div.innerHTML;
  }


  // Handle messages sent from the extension to the webview
  window.addEventListener('message', event => {
    const message = event.data; // The json data that the extension sent
    let config = {};
    if (message.type === 'package' || message.type === 'sketch' || message.type === 'interface' || message.type === 'part' || message.type === 'assembly' || message.type === 'scene' || message.type === 'software') {
      config = message.obj['config'];
    }
    switch (message.type) {
      case 'clear':
        let contents = document.querySelector('.contents');
        if (contents) {
          contents.innerHTML = 'Select the item in the Explorer view above to see details here.';
        }
        break;
      case 'package':
        {
          let contents = document.querySelector('.contents');
          if (contents) {
            let html = `<table class="inspector">`;
            html += `<tr><td>Name:</td><td>${message.obj['name']}</td></tr>`;
            html += `<tr><td>Parent:</td><td>${message.obj['pkg']}</td></tr>`;
            if ('desc' in config) {
              html += `<tr><td>Description:</td><td>${config['desc']}</td></tr>`;
            }
            html += `<tr><td>Type:</td><td>${config['type']}</td></tr>`;
            if (config['type'] === 'git' && 'importUrl' in config) {
              html += `<tr><td>Git:</td><td>${config['importUrl']}</td></tr>`;
            }
            html += `</table>`;
            contents.innerHTML = html;
          }
          break;
        }
      case 'software':
        {
          // Software is a file the package ships and not geometry, so this says
          // what the file is and where it is, and asks for no render: whatever
          // the PartCAD Viewer is showing stays as it is.
          let contents = document.querySelector('.contents');
          if (contents) {
            let html = `<table class="inspector">`;
            html += `<tr><td>Name:</td><td>${escapeHtml(message.obj['name'])}</td></tr>`;
            html += `<tr><td>Package:</td><td>${escapeHtml(message.obj['pkg'])}</td></tr>`;
            html += `<tr><td>Type:</td><td>${escapeHtml(config['type'])}</td></tr>`;
            if ('desc' in config) {
              html += `<tr><td>Description:</td><td>${escapeHtml(config['desc'])}</td></tr>`;
            }
            // 'item_path' is where the file is on disk, which is what the user
            // needs; 'path' is the fallback for a package that declares one
            // without PartCAD having resolved it.
            const filePath = config['item_path'] || config['path'];
            if (filePath) {
              html += `<tr><td>Path:</td><td>${escapeHtml(filePath)}</td></tr>`;
            }
            // Absent for a file the package carries itself, where the revision
            // of the package is what identifies it and no hash is required.
            if (config['fileHash']) {
              html += `<tr><td>Hash:</td><td>${escapeHtml(config['fileHash'])}</td></tr>`;
            }
            html += `</table>`;
            contents.innerHTML = html;
          }
          break;
        }
      case 'sketch':
      case 'interface':
      case 'part':
      case 'assembly':
      // A scene is shown exactly as an assembly is: it takes parameters the
      // same way, and it is inspected in the viewer the same way.
      case 'scene':
        {
          let contents = document.querySelector('.contents');
          let html = '';
          if (contents) {
            let inspectorParams = {};
            html += `<table class="inspector">`;
            html += `<tr><td>Name:</td><td>${message.obj['name']}</td></tr>`;
            html += `<tr><td>Package:</td><td>${message.obj['pkg']}</td></tr>`;
            // if ('desc' in config) {
            //   html += `<tr><td>Description:</td><td>${config['desc']}</td></tr>`;
            // }
            if (message.type !== 'interface') {
              html += `<tr><td>Type:</td><td>${config['type']}</td></tr>`;
            }

            if (config["type"] && config["type"] === "alias") {
              html += `<tr><td>Target:</td><td>${config['target']}</td></tr>`;
              if ('package' in config) {
                html += `<tr><td>Target package:</td><td>${config['package']}</td></tr>`;
              }

            } else {
              html += `<tr><td>Description:</td><td>`;
              html += `<textarea id="desc" class="property-input" name="desc" readonly>`;
              html += `</textarea>`;
              html += `</td></tr>`;
            }


            if (config["parameters"]) {
              html += `<tr><td colspan=2>Parameters:</td></tr>`;
              for (const paramName in config["parameters"]) {
                const param = config["parameters"][paramName];
                if (param["type"] === "array") {
                  /* FIXME(clairbee): Not implemented in VS Code yet */
                  continue;
                }

                html += `<tr><td>${paramName}:</td><td>`;
                let value = '';
                if (message.params && message.params[paramName]) {
                  value = message.params[paramName];
                }
                if ("default" in param) {
                  if (param["type"] === "float") {
                    let num = parseFloat(param["default"]);
                    if (Number.isInteger(num)) {
                      value = num.toFixed(1);
                    } else {
                      value = num.toString();
                    }
                  } else {
                    value = param["default"];
                  }
                }
                if ("enum" in param || param["type"] === "bool") {
                  let options = [];
                  let classes = "param-input";
                  if (param["type"] === "bool") {
                    options = ["false", "true"];
                    value = value ? "true" : "false";
                    classes = "param-input pc-param-bool";
                  } else {
                    options = param["enum"];
                  }
                  html += `<select id="${paramName}" class="${classes}" name="${paramName}">`;
                  for (const i in options) {
                    html += `<option value="${options[i]}" `;
                    if (options[i] === value) {
                      html += "selected";
                    }
                    html += `>${options[i]}</option>`;
                  }
                  html += `</select>`;
                } else {
                  let inputType = 'text';
                  switch (param["type"]) {
                    case 'int':
                    case 'float':
                      break;
                    case 'string':
                  }
                  let extraAttributes = '';
                  if (param["type"] === "int") {
                    inputType = 'number';
                    if (value === '') {
                      value = "0";
                    }
                  } else if (param["type"] === "float") {
                    inputType = 'text';
                    if (value === '') {
                      value = "0.0";
                    }
                    // extraAttributes = 'step="any"';
                    extraAttributes = 'inputmode="decimal" pattern="[0-9]*[.,]?[0-9]*"';
                  }
                  html += `<input id="${paramName}" class="param-input" name="${paramName}" type="${inputType}" ${extraAttributes} value="${value}"/>`;
                }
                html += `</td></tr>`;
              }
              html += `<tr><td colspan=2><button class="update-button">Update</button></td></tr>`;
            }
            html += `</table>`;
            contents.innerHTML = html;

            const allInputs = contents.getElementsByClassName("param-input");
            for (let i = 0; i < allInputs.length; i++) {
              const item = allInputs[i];
              item.addEventListener('change', () => {
                // this works and produces false
                // if (contents) {
                //   contents.innerHTML = item.nodeValue ? item.nodeValue : "false";
                // }

                if ("pc-param-bool" in item.classList) {
                  // @ts-expect-error
                  inspectorParams[item.id] = item.value === "true";
                } else {
                  // @ts-expect-error
                  inspectorParams[item.id] = item.value;
                }
              });
            }

            const updateButton = contents.querySelector('.update-button');
            if (updateButton) {
              updateButton.addEventListener('click', () => {
                var command;
                if (message.type === 'sketch') {
                  command = "partcad.inspectSketch";
                } else if (message.type === 'assembly') {
                  command = "partcad.inspectAssembly";
                } else if (message.type === 'scene') {
                  command = "partcad.inspectScene";
                } else if (message.type === 'interface') {
                  command = "partcad.inspectInterface";
                } else {
                  command = "partcad.inspectPart";
                }
                vscode.postMessage({
                  action: 'command',
                  command: command,
                  params: [message.obj, inspectorParams],
                });
              });
            }

            if ('desc' in config) {
              let desc = document.getElementById('desc'); // as HTMLTextAreaElement;
              if (desc) {
                // @ts-expect-error
                desc.value = config["desc"];
              }
            }
          }
          break;
        }
    }
  });

}());
