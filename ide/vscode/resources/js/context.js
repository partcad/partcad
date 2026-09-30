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
    switch (message.type) {
      case 'stats':
        {
          const version = document.querySelector('.version');
          if (version) {
            version.innerHTML = message.version;
          }
          const path = document.querySelector('.path');
          if (path) {
            path.innerHTML = message.stats.path;
          }
          const packages = document.querySelector('.num-packages');
          if (packages) {
            let value1 = message.stats.packages;
            let value2 = message.stats.packages_instantiated;
            packages.innerHTML = `${value1}&nbsp;(${value2})`;
          }
          const sketches = document.querySelector('.num-sketches');
          if (sketches) {
            let value1 = message.stats.sketches;
            let value2 = message.stats.sketches_instantiated;
            sketches.innerHTML = `${value1}&nbsp;(${value2})`;
          }
          const interfaces = document.querySelector('.num-interfaces');
          if (interfaces) {
            let value1 = message.stats.interfaces;
            let value2 = message.stats.interfaces_instantiated;
            interfaces.innerHTML = `${value1}&nbsp;(${value2})`;
          }
          const parts = document.querySelector('.num-parts');
          if (parts) {
            let value1 = message.stats.parts;
            let value2 = message.stats.parts_instantiated;
            parts.innerHTML = `${value1}&nbsp;(${value2})`;
          }
          const assemblies = document.querySelector('.num-assemblies');
          if (assemblies) {
            let value1 = message.stats.assemblies;
            let value2 = message.stats.assemblies_instantiated;
            assemblies.innerHTML = `${value1}&nbsp;(${value2})`;
          }
          const size = document.querySelector('.num-memory');
          if (size) {
            let value = message.stats.size;
            let suffix = ' B';
            if (value > 1024) {
              value /= 1024;
              if (value < 1024) {
                suffix = ' KB';
              } else {
                value /= 1024;
                suffix = ' MB';
              }
            }
            value = value.toFixed(2);
            size.innerHTML = value.toString() + suffix;
          }
          break;
        }

    }
  });

}());
