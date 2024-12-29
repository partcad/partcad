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


  // Handle messages sent from the extension to the webview
  window.addEventListener('message', event => {
    const message = event.data; // The json data that the extension sent
    let config = {};
    if (message.type === 'package' || message.type === 'sketch' || message.type === 'interface' || message.type === 'part' || message.type === 'assembly') {
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
            html += `<tr><td>Type:</td><td>${config['type']}</td></tr></table>`;
            contents.innerHTML = html;
          }
          break;
        }
      case 'sketch':
      case 'interface':
      case 'part':
      case 'assembly':
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
            if (message.type !== 'interface' && !config["type"].startsWith("ai-")) {
              // AI types allow editing the type
              html += `<tr><td>Type:</td><td>${config['type']}</td></tr>`;
            }

            if (config["type"] && config["type"] === "alias") {
              html += `<tr><td>Target:</td><td>${config['target']}</td></tr>`;
              if ('package' in config) {
                html += `<tr><td>Target package:</td><td>${config['package']}</td></tr>`;
              }

            } else if (config["type"] && config["type"].startsWith("ai-")) {
              const types = [
                "ai-build123d",
                "ai-cadquery",
                "ai-openscad",
              ];

              html += `<tr><td>Type:</td><td>`;
              html += `<select id="itemType" class="property-input" name="itemType">`;
              for (const i in types) {
                html += `<option value="itemType" `;
                if (types[i] === config["type"]) {
                  html += "selected";
                }
                html += `>${types[i]}</option>`;
              }
              html += `</select>`;
              html += `</td></tr>`;

              const providers = [
                "google",
                "openai",
                "ollama",
              ];

              html += `<tr><td>Provider:</td><td>`;
              html += `<select id="provider" class="property-input" name="provider">`;
              for (const i in providers) {
                html += `<option value="provider" `;
                if (providers[i] === config["provider"]) {
                  html += "selected";
                }
                html += `>${providers[i]}</option>`;
              }
              html += `</select>`;
              html += `</td></tr>`;

              let model = "";
              if ("model" in config) {
                model = (new String(config["model"])).valueOf();
              }
              html += `<tr><td>Model:</td><td>`;
              html += `<input id="model" class="property-input" name="model" type="text" value="${model}" placeholder="(optional)"/>`;
              html += `</td></tr>`;

              html += `<tr><td valign="top">Description:</td><td>`;
              html += `<textarea id="desc" class="property-input" name="desc">`;
              html += `</textarea>`;
              html += `</td></tr>`;

              let tokens = '';
              if ('tokens' in config) {
                tokens = (new String(config["tokens"])).valueOf();
              }
              html += `<tr><td>Tokens:</td><td>`;
              html += `<input id="tokens" class="property-input" name="tokens" type="text" value="${tokens}" placeholder="(optional)"/>`;
              html += `</td></tr>`;

              if ('top_p' in config) {
                html += `<tr><td>Top_p:</td><td>${config['top_p']}</td></tr>`;
              }

              // @ts-expect-error
              if ('images' in config && config['images'].length > 0) {
                html += `<tr><td>Images:</td><td><ul>`;
                // @ts-expect-error
                for (const i in config['images']) {
                  // @ts-expect-error
                  html += `<li>${config['images'][i]}</li>`;
                }
                html += `</ul></td></tr>`;
              }

              html += `<tr><td colspan=2><button class="regenerate-button">Regenerate</button></td></tr>`;

              html += '<tr><td colspan=2><hr/></td></tr>';

              // The below textarea and button are implementing the 'Change with AI' feature
              html += `<tr><td valign="top">What to change:</td><td>`;
              html += `<textarea id="change" class="property-input" name="change" placeholder="(optional) E.g. add a 3mm through hole">`;
              html += `</textarea>`;
              html += `</td></tr>`;
              html += `<tr><td colspan=2><button class="change-button">Change</button></td></tr>`;
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
                vscode.postMessage({
                  action: 'command',
                  command: message.type === 'part' ? 'partcad.inspectPart' : 'partcad.inspectAssembly',
                  params: [message.obj, inspectorParams],
                });
              });
            }

            const regenerateButton = contents.querySelector('.regenerate-button');
            if (regenerateButton) {
              regenerateButton.addEventListener('click', () => {
                let itemType = document.getElementById('itemType'); // as HTMLSelectElement;
                if (itemType) {
                  // @ts-expect-error
                  config["type"] = itemType.options[itemType.selectedIndex].text;
                }

                let provider = document.getElementById('provider'); // as HTMLSelectElement;
                if (provider) {
                  // @ts-expect-error
                  config["provider"] = provider.options[provider.selectedIndex].text;
                }

                let model = document.getElementById('model'); // as HTMLInputElement;
                if (model && 'provider' in config) {
                  // @ts-expect-error
                  if (model.value && model.value !== "") {
                    // @ts-expect-error
                    config["model"] = model.value;
                  } else {
                    config["model"] = null;
                  }
                }

                let desc = document.getElementById('desc'); // as HTMLInputElement;
                if (desc) {
                  // @ts-expect-error
                  config["desc"] = desc.value;
                }

                let tokens = document.getElementById('tokens'); // as HTMLInputElement;
                if (tokens && 'provider' in config) {
                  // @ts-expect-error
                  if (tokens.value && tokens.value !== "") {
                    try {
                      // @ts-expect-error
                      config["tokens"] = parseInt((new String(tokens.value)).valueOf());
                    } catch (error) {
                      config["tokens"] = null;
                    }
                  } else {
                    config["tokens"] = null;
                  }
                }

                vscode.postMessage({
                  action: 'command',
                  command: message.type === 'part' ? 'partcad.regeneratePartCb' : 'partcad.regenerateAssemblyCb',
                  params: [{ pkg: message.obj.pkg, name: message.obj.name, config }],
                });
              });
            }

            const changeButton = contents.querySelector('.change-button');
            if (changeButton) {
              changeButton.addEventListener('click', () => {
                let itemType = document.getElementById('itemType'); // as HTMLSelectElement;
                if (itemType) {
                  // @ts-expect-error
                  config["type"] = itemType.options[itemType.selectedIndex].text;
                }

                let provider = document.getElementById('provider'); // as HTMLSelectElement;
                if (provider) {
                  // @ts-expect-error
                  config["provider"] = provider.options[provider.selectedIndex].text;
                }

                let model = document.getElementById('model'); // as HTMLInputElement;
                if (model && 'provider' in config) {
                  // @ts-expect-error
                  if (model.value && model.value !== "") {
                    // @ts-expect-error
                    config["model"] = model.value;
                  } else {
                    config["model"] = null;
                  }
                }

                let desc = document.getElementById('desc'); // as HTMLInputElement;
                if (desc) {
                  // @ts-expect-error
                  config["desc"] = desc.value;
                }

                let tokens = document.getElementById('tokens'); // as HTMLInputElement;
                if (tokens && 'provider' in config) {
                  // @ts-expect-error
                  if (tokens.value && tokens.value !== "") {
                    try {
                      // @ts-expect-error
                      config["tokens"] = parseInt((new String(tokens.value)).valueOf());
                    } catch (error) {
                      config["tokens"] = null;
                    }
                  } else {
                    config["tokens"] = null;
                  }

                  let change = document.getElementById('change'); // as HTMLInputElement;
                  if (change) {
                    // @ts-expect-error
                    config["change"] = change.value;
                  }
                }

                vscode.postMessage({
                  action: 'command',
                  command: message.type === 'part' ? 'partcad.changePartCb' : 'partcad.changeAssemblyCb',
                  params: [{ pkg: message.obj.pkg, name: message.obj.name, config }],
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

            if (config["type"].startsWith("ai-")) {
              if ('tokens' in config) {
                let tokens = document.getElementById('tokens'); // as HTMLInputElement;
                if (tokens) {
                  // @ts-expect-error
                  tokens.value = config["tokens"];
                }
              }
            }
          }
          break;
        }
    }
  });

}());
