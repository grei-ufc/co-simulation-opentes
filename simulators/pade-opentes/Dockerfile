ARG PYTHON_VERSION=3.12.11

FROM python:${PYTHON_VERSION}-slim

LABEL maintainer="GREI-UFC"
LABEL description="PADE runtime + agentes para a integracao OpenTES."

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/pade
COPY pyproject.toml setup.py README.md LICENSE ./
COPY pade ./pade
RUN pip install --no-cache-dir /opt/pade

WORKDIR /app
RUN pip install --no-cache-dir \
    mosaik-api-v3==3.0.14 \
    pyzmq==27.1.0 \
    ipython==8.26.0 \
    numpy>=2.0 \
    pandas>=2.0 \
    pyomo>=6.9 \
    py-dss-interface>=2.3.0

# O CPLEX NAO entra na imagem: a licenca academica e pessoal e este repositorio e
# publico. Ele e montado do host em tempo de execucao (ver docker-compose.yaml e
# simulators/market-opentes/README.md). Sem ele, os cenarios de mercado nao
# rodam; os demais cenarios do repositorio nao dependem disso.
ENV MARKET_SOLVER=cplex
ENV MARKET_SOLVER_PATH=/opt/cplex/bin/x86-64_linux/cplex

COPY agents /app/agents

EXPOSE 3000/tcp
EXPOSE 5678/tcp
EXPOSE 8000/tcp
EXPOSE 8001/tcp

CMD ["python3", "agents/pade_star.py"]
