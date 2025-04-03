FROM ghcr.io/partcad/partcad-devcontainer:0.7.132

USER vscode
RUN /home/vscode/miniforge3/bin/conda create --yes --name pc-env python=3.12 pip

USER root
RUN mkdir -p /dot-partcad
ENV PC_INTERNAL_STATE_DIR=/dot-partcad
RUN mkdir -p /pc
WORKDIR /pc
COPY _common/requirements.txt ./

USER vscode
RUN /home/vscode/miniforge3/bin/conda run -n pc-env pip install --no-cache-dir -r requirements.txt

USER root
COPY _common/pc-container-json-rpc.py ./
RUN chown -R vscode:vscode /dot-partcad /pc

EXPOSE 5000

USER vscode
CMD ["/home/vscode/miniforge3/bin/conda", "run", "-n", "pc-env", "python", "pc-container-json-rpc.py"]
