FROM python:3.13-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    DISPLAY=:99 \
    VNC_GEOM=1280x800x24 \
    NOVNC_PORT=8080 \
    VNC_PORT=5900

RUN apt-get update && apt-get install -y --no-install-recommends \
    tk tcl xvfb x11vnc novnc websockify \
    openbox \
    ca-certificates \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r /app/requirements.txt

COPY . /app


COPY docker/start.sh /usr/local/bin/start.sh
RUN chmod +x /usr/local/bin/start.sh

EXPOSE 8080 5900
ENTRYPOINT ["/usr/local/bin/start.sh"]
CMD ["python", "main.py"]