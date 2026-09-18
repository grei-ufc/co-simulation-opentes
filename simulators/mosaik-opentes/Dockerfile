ARG PYTHON_VERSION=3.12.11

FROM python:${PYTHON_VERSION}-slim

LABEL maintainer="GREI-UFC"
LABEL description="Mosaik engine + cenarios + collectors da integracao OpenTES."

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV MOSAIK_SCENARIO=scenarios/star.py

WORKDIR /app

RUN pip install --no-cache-dir \
    setuptools==69.5.1 \
    mosaik==3.5.0 \
    mosaik-api-v3==3.0.14 \
    mosaik-api==3.0.6 \
    mosaik-csv==2.0.1 \
    pandas>=2.3.2 \
    matplotlib>=3.10.0 \
    pyzmq==27.1.0

COPY . /app/

CMD ["sh", "-c", "python -u \"$MOSAIK_SCENARIO\""]
