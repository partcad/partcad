FROM ghcr.io/partcad/partcad-devcontainer:0.7.118

RUN mkdir -p /dot-partcad
ENV PC_INTERNAL_STATE_DIR=/dot-partcad

RUN mkdir -p /pc
WORKDIR /pc
COPY _common/* ./

RUN \
  curl -L "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh" -o /tmp/miniforge3.sh \
  && chmod +x /tmp/miniforge3.sh \
  && bash /tmp/miniforge3.sh -b \
  && rm /tmp/miniforge3.sh

RUN \
  /home/kicad/miniforge3/bin/conda create --yes --name pc-env python=3.12 pip \
  && /home/kicad/miniforge3/bin/conda run -n pc-env pip install --no-cache-dir -r requirements.txt

EXPOSE 5000

CMD ["/home/kicad/miniforge3/bin/conda", "run", "-n", "pc-env", "python", "pc-container-json-rpc.py"]
