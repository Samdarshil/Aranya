# STATUS: written but not built in the authoring sandbox (no network
# access there to pull the base image or pip install). Standard shape —
# verify with `docker build` on a machine with network access.

FROM python:3.12-slim

# OpenCV needs these system libs to import correctly on slim images.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 libsm6 libxext6 libxrender1 libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend

EXPOSE 8000
CMD ["uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
