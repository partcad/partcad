FROM kicad/kicad:8.0

RUN mkdir -p /dot-partcad
ENV PC_INTERNAL_STATE_DIR=/dot-partcad

RUN mkdir -p /pc
WORKDIR /pc
COPY ../_common/* .
RUN pip3 install --no-cache-dir -r requirements.txt

EXPOSE 5000

CMD ["python3", "pc-container-json-rpc.py"]
