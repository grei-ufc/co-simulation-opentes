FROM python:3.12.11-slim

RUN apt-get update && apt-get install -y \
    build-essential \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# O caso de mercado e as ferramentas que o geram (TTESO). O simulador OpenDSS e o
# do TSRE e vem do submodulo teams/tsre-der-opentes, montado em /tsre/src pelo
# docker-compose.yaml, sem copia: atualizar o TSRE e atualizar o submodulo.
COPY src/ ./src/

ENV PYTHONPATH=/tsre/src
ENV PYTHONUNBUFFERED=1

CMD ["python", "-u", "-m", "simulators.opendss.api_opendss", "--remote", "0.0.0.0:5671"]
