FROM kicad/kicad:8.0

USER root
RUN \
  apt-get update \
  && apt-get install --yes --no-install-recommends \
  curl=7.88.1-10+deb12u8 \
  && rm -rf /var/lib/apt/lists/*

USER kicad
RUN \
  curl -L "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh" -o /tmp/miniforge3.sh \
  && chmod +x /tmp/miniforge3.sh \
  && bash /tmp/miniforge3.sh -b \
  && rm /tmp/miniforge3.sh \
  \
  && /home/kicad/miniforge3/bin/conda create --yes --name pc-env python=3.12 pip

USER root
RUN mkdir -p /dot-partcad
ENV PC_INTERNAL_STATE_DIR=/dot-partcad
RUN mkdir -p /pc
WORKDIR /pc
COPY _common/requirements.txt ./

USER kicad
RUN /home/kicad/miniforge3/bin/conda run -n pc-env pip install --no-cache-dir -r requirements.txt

USER root
COPY _common/pc-container-json-rpc.py ./
RUN chown -R kicad:kicad /dot-partcad /pc

EXPOSE 5000

USER kicad
CMD ["/home/kicad/miniforge3/bin/conda", "run", "-n", "pc-env", "python", "pc-container-json-rpc.py"]
