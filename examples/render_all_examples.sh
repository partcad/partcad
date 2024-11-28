#!/bin/sh

for i in *; do
    if [ -f "$i/partcad.yaml" ]; then
        echo "Rendering $i..."
        (cd "$i" && pc render)
    fi
done
