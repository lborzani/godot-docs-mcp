FROM python:3.13-slim AS build
ARG GODOT_DOCS_BRANCH=stable
ENV GODOT_DOCS_BRANCH=${GODOT_DOCS_BRANCH}
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY server.py .
RUN python3 server.py --build

FROM python:3.13-slim
ARG GODOT_DOCS_BRANCH=stable
ENV GODOT_DOCS_BRANCH=${GODOT_DOCS_BRANCH} PYTHONUNBUFFERED=1
WORKDIR /app
COPY server.py .
COPY --from=build /app/data/index.db data/index.db
USER nobody
EXPOSE 8765
HEALTHCHECK CMD python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8765/health')"
CMD ["python3", "server.py", "--http"]
