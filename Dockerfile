# Base image and uv are pinned by digest, so a rebuild gets the same bytes. To update,
# resolve the new tag's index digest from the registry and replace both tag and digest.
FROM python:3.11-slim@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535

# uv installs dependencies from uv.lock (same version as CI's setup-uv pin).
COPY --from=ghcr.io/astral-sh/uv:0.11.32@sha256:df4cae8f3a96d175e2e5f992e597550000edbe78fdc2594d5cd8de1a217f504c /uv /usr/local/bin/uv

WORKDIR /app

# libicu-dev + a compiler are needed once, to build PyICU (required by the
# graph view's followthemoney dependency); the compiler is purged afterwards.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git build-essential pkg-config libicu-dev \
    && rm -rf /var/lib/apt/lists/*

COPY . .

# Dependencies come from uv.lock, hash-checked (--locked fails if the lock is stale).
# The package itself is then installed editable on purpose, without dependencies: the
# docs mount and static files resolve relative to the package root. Keys saved from the
# UI go to $OPENOSINT_HOME/config.env, in the volume.
RUN uv export --locked --no-dev --extra graph --no-emit-project --no-header -o /tmp/requirements.txt \
    && uv export --locked --no-dev --extra graph --no-emit-project --no-header --no-hashes -o /tmp/constraints.txt \
    && uv pip install --system --no-cache --require-hashes -r /tmp/requirements.txt \
    && uv pip install --system --no-cache --no-deps -e . \
    && apt-get purge -y --auto-remove build-essential pkg-config

# Optional OSINT tools (not in uv.lock). Exact versions; the lock export is a constraint,
# so they cannot change any locked package (the build fails instead). sherlock-project is
# also imported as a library, so they share the app's interpreter.
RUN uv pip install --system --no-cache -c /tmp/constraints.txt \
        holehe==1.61 sherlock-project==0.16.2 sublist3r==1.0 \
    && rm /tmp/requirements.txt /tmp/constraints.txt

RUN mkdir -p /app/reports /data

# graph.db and session history live here; mount a volume to persist them.
ENV OPENOSINT_HOME=/data
VOLUME /data

EXPOSE 8080

# --allow-remote is required for a non-loopback bind (GHSA-cqr4-hcfp-m6m4) —
# safe here because the container network boundary is what's actually
# exposed; publish the port only to trusted networks.
# /app/.env stays a symlink into the data volume so a /data/.env from an older
# release keeps loading (and is copied to /data/config.env once). It dangles until
# such a file exists, so the "Loaded .env" line only appears once there really is one.
# Saving keys from the browser needs OPENOSINT_SETUP_TOKEN here: the browser reaches
# the container over the Docker bridge, not loopback.
CMD ["sh", "-c", "ln -sf /data/.env /app/.env && exec openosint web --host 0.0.0.0 --port 8080 --no-browser --allow-remote"]
