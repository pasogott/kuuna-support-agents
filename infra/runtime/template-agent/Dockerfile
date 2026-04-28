ARG BASE_IMAGE=python:3.12-slim-bookworm
FROM ${BASE_IMAGE}

ARG KUUNA_TEMPLATE_KEY=unknown
ARG KUUNA_TEMPLATE_VERSION_ID=unknown

LABEL kuuna.template.key="${KUUNA_TEMPLATE_KEY}"
LABEL kuuna.template_version.id="${KUUNA_TEMPLATE_VERSION_ID}"

ENV PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir httpx

WORKDIR /opt/kuuna

COPY client_entrypoint.py /opt/kuuna/client_entrypoint.py

ENTRYPOINT ["python", "/opt/kuuna/client_entrypoint.py"]
