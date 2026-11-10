# Instalação

## Requisitos

- **Docker** e **Docker Compose**. Cada simulador roda no seu contêiner, e nada
  além disso é instalado no host.
- **IBM CPLEX**, o solver dos modelos de otimização. A licença acadêmica é
  pessoal (gratuita pelo IBM Academic Initiative), então ele não está no
  repositório nem nas imagens: é montado do host em tempo de execução.
- **Python 3.12 e [uv](https://github.com/astral-sh/uv)**, só para o ambiente
  local opcional (ver abaixo) e para esta documentação.

## Obter e construir

```bash
git clone https://github.com/grei-ufc/co-simulation-opentes
cd co-simulation-opentes
docker compose build        # uma vez, ou depois de mudar um Dockerfile
```

O primeiro `build` compila o OMNeT++ e leva alguns minutos. São construídas
quatro imagens: `opentes/comm`, `opentes/grid`, `opentes/pade` e
`opentes/mosaik` (esta última serve também ao coletor e às figuras). Os
serviços estão em [Serviços Docker](../reference/docker-services.md).

## Apontar o CPLEX

```bash
export CPLEX_HOME=$HOME/IBM/CPLEX_Studio2211/cplex
```

O `run.sh` confere se `$CPLEX_HOME/bin/x86-64_linux/cplex` existe antes de
qualquer comando que otimize, e para com uma mensagem se não existir. O console
guarda esse caminho na configuração, então dentro dele basta informá-lo uma vez.

## O comando `opentes` (opcional)

Para chamar a plataforma de qualquer pasta:

```bash
ln -s "$PWD/run.sh" ~/.local/bin/opentes
```

Depois disso, `opentes` abre o console e `opentes market` roda a co-simulação.
O `run.sh` segue o link e sempre trabalha na pasta do repositório.

## Conferir

```bash
./run.sh
```

Sem argumentos, num terminal, o `run.sh` abre o console, que mostra o estado do
ambiente (Docker, imagens, CPLEX, matrizes do caso). Se tudo estiver marcado
como pronto, siga para a [Primeira Simulação](first-simulation.md).

## Ambiente Python local (opcional)

```bash
uv sync
```

Cria um `.venv` com o PADE e o grid como dependências editáveis, útil para o
autocomplete da IDE e para rodar scripts fora dos contêineres. A co-simulação em
si roda nos contêineres: o OMNeT++ é C++, e o OpenDSS da imagem é o caminho
testado.
