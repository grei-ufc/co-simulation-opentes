#!/usr/bin/env bash
#
# run.sh - ponto de entrada unico do OpenTES: mercado transativo sobre a IEEE 13.
#
#   ./run.sh               console interativo (cli/console.sh)
#   ./run.sh --help        lista os comandos
#   ./run.sh market        co-simulacao completa (o comando do dia a dia)
#
# Os resultados vao para output/market/ (analise por fase, o padrao) ou para
# output/market_por_no/ (MARKET_FASE=0, analise por barra, para comparacao).

set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"   # segue o link de ~/.local/bin/opentes

CASO=simulators/grid-opentes/src/data/13Bus
RESULT=""

usage() {
    cat <<'EOF'
OpenTES - mercado transativo sobre a IEEE 13 barras
(agentes PADE + OpenDSS + OMNeT++, orquestrados pelo Mosaik)

Uso: opentes             console interativo, com menu
     opentes <comando>
     (opentes e um link para este run.sh; sem ele, use ./run.sh na pasta do projeto.
      Para criar: ln -s "$PWD/run.sh" ~/.local/bin/opentes)

Comandos:
  market          Co-simulacao completa, em duas passadas sobre a mesma demanda
                  realizada: 'baseline' (programacao dos prosumidores, sem
                  mecanismo) e 'negociado' (negociacao multiagente e fase de
                  operacao). Grava result_baseline.csv, result_negociado.csv e
                  run.json.
  centralizado    A mesma negociacao, sem agentes nem Mosaik, mais a liquidacao:
                  figuras.npz, dlmp.csv, flexibility.csv, transactions.csv e
                  market_series.csv. Rapido; e o que alimenta as figuras.
  figuras         As figuras de uma execucao, a partir das saidas dos dois
                  comandos acima, em <resultados>/figuras/.
  caso            Regenera o caso IEEE 13 (gen_ieee13_market.py) e as duas
                  matrizes de sensibilidade. So depois de mudar o circuito,
                  as curvas de PV ou a alocacao de armazenamento.

Variaveis mais usadas (todas em docker-compose.yaml):
  CPLEX_HOME            instalacao do CPLEX no host (obrigatoria)
  MARKET_FASE           1 (padrao): tensao e preco sombra por fase; 0: por barra
  MARKET_DISPOSITIVO    independente (padrao, quatro fios) ou equilibrado
  MARKET_REGULADOR      previsao (padrao) ou neutro
  MARKET_CRITERIO       relativo (padrao, MARKET_EPS_REL=1e-3) ou absoluto
  NET_BACKEND           ideal (padrao), lossy ou omnet (rede 6TiSCH)
  NET_TIME_SCALE        fracao do atraso nominal esperada em relogio (0.02 com omnet)
  TISCH_MAC             com omnet: tsch (6TiSCH, padrao) ou wisun (Wi-SUN FAN)
  TISCH_CELLS           fatias por enlace a cada slotframe na 6TiSCH (padrao 2)
  TISCH_RATE_BPS        taxa do Wi-SUN: 50000 (padrao), 150000 ou 300000

Exemplos:
  export CPLEX_HOME=$HOME/IBM/CPLEX_Studio2211/cplex
  opentes centralizado && opentes market && opentes figuras
  MARKET_FASE=0 opentes market
  NET_BACKEND=omnet NET_TIME_SCALE=0.02 opentes market
  NET_BACKEND=omnet NET_TIME_SCALE=0.02 TISCH_MAC=wisun OPENTES_SAIDA=market_wisun_50k opentes market
EOF
}

# Sem argumentos, num terminal interativo, abre o console.
if [ $# -eq 0 ] && [ -t 0 ] && [ -t 1 ]; then
    exec bash cli/console.sh
fi
if [ "${1:-}" = "console" ]; then
    exec bash cli/console.sh
fi

# --- pasta de resultados ----------------------------------------------------
# OPENTES_SAIDA escolhe outra pasta dentro de output/ (o console usa uma pasta
# por configuracao, para uma execucao nao apagar a outra).
if [ -n "${OPENTES_SAIDA:-}" ]; then SAIDA="$OPENTES_SAIDA"
elif [ "${MARKET_FASE:-1}" = "1" ]; then SAIDA=market; else SAIDA=market_por_no; fi
export MOSAIK_OUTPUT_DIR="/app/output/$SAIDA"
export MARKET_RUN_DIR="/app/output/$SAIDA"
mkdir -p "output/$SAIDA"

# Limpeza completa: containers, rede e orfaos. Os simuladores --remote aceitam
# uma unica conexao e morrem depois dela, entao cada passada precisa deles novos.
_cleanup() {
    docker compose down --remove-orphans >/dev/null 2>&1 || true
    docker ps -aq --filter "name=opentes-" | xargs -r docker rm -f >/dev/null 2>&1 || true
}

_exige_cplex() {
    if [ ! -x "${CPLEX_HOME:-/nao-definido}/bin/x86-64_linux/cplex" ]; then
        echo "!! CPLEX nao encontrado. Defina CPLEX_HOME, por exemplo:" >&2
        echo "     export CPLEX_HOME=\$HOME/IBM/CPLEX_Studio2211/cplex" >&2
        echo "   Detalhes em docs/getting-started/installation.md" >&2
        exit 1
    fi
    export CPLEX_HOME
}

# Gera uma matriz de sensibilidade (dV/dP, dV/dQ e as derivacoes do regulador no
# ponto da previsao). $1 = arquivo, $2 = opcao extra do sensitivity.py
_sensibilidade() {
    echo ">> gerando $1"
    docker compose run --rm --no-deps -e GRID_DIR=/app/src/data/13Bus grid \
        python src/simulators/sensitivity.py day $2 \
        --load-csv /app/src/data/13Bus/load_kw.csv \
        --pv-csv /app/src/data/13Bus/pv_kw.csv \
        --out "/app/src/data/13Bus/$1"
}

# A matriz e do circuito, e nao do mecanismo: gera uma vez, e de novo se faltar
# a informacao do regulador (matriz de uma versao anterior).
_garante_sensibilidade() {
    local arq=sensitivity_day.npz opt=""
    if [ "${MARKET_FASE:-1}" = "1" ]; then arq=sensitivity_fase.npz; opt=--por-fase; fi
    if [ ! -f "$CASO/$arq" ] || ! python3 -c "import zipfile,sys; sys.exit('taps.npy' not in zipfile.ZipFile('$CASO/$arq').namelist())" 2>/dev/null; then
        _sensibilidade "$arq" "$opt"
    fi
}

_wait_log() {   # $1 = servico, $2 = padrao do log, $3 = descricao, $4 = segundos
    local i
    echo ">> aguardando $3..."
    for i in $(seq 1 "$4"); do
        if docker compose logs "$1" 2>/dev/null | grep -q "$2"; then return 0; fi
        sleep 1
    done
    echo "!! timeout aguardando $3" >&2
    return 1
}

# Uma passada da co-simulacao. $1 = tag do resultado, $2 = MARKET_NEGOTIATE
_passada() {
    local tag="$1" negocia="$2"
    _cleanup
    # As MESMAS variaveis nas duas chamadas do compose: se mudassem, o compose
    # recriaria o pade bem na hora em que o mosaik conecta.
    export RESULT_TAG="$tag" MARKET_NEGOTIATE="$negocia"
    if [ "${NET_BACKEND:-ideal}" = "omnet" ]; then
        export NET_TRACE="/app/output/$SAIDA/msg_trace.csv"
        docker compose up -d comm
        # A primeira vez compila o OMNeT++ e leva minutos.
        _wait_log comm "6TiSCH. pronto" "o servidor 6TiSCH" 900
    fi
    docker compose up -d grid collector pade
    # Pela linha de log, e nao por TCP: o pade so fica pronto depois do listenTCP
    # de todos os agentes, e os simuladores --remote morrem se forem sondados.
    _wait_log pade "market-mas. pronto" "os agentes PADE" 120
    _wait_log collector "Waiting for connection" "o coletor" 60
    docker compose up --abort-on-container-exit --exit-code-from mosaik mosaik
}

cmd_market() {
    _exige_cplex
    _garante_sensibilidade
    echo ">> passada 'baseline' (programacao dos prosumidores, sem mecanismo)"
    MARKET_OPERATION=0 _passada baseline 0
    echo ">> passada 'negociado' (negociacao multiagente e fase de operacao)"
    _passada negociado 1
    RESULT="output/$SAIDA/"
}

cmd_centralizado() {
    _exige_cplex
    _garante_sensibilidade
    docker compose run --rm --no-deps -w /tmp -e PYTHONPATH=/market pade \
        sh -c "python -m market_opentes.dual --config /grid-data/13Bus/config.json \
               --max-rounds 300 --settle-dir /app/output/$SAIDA \
               --out /app/output/$SAIDA/history.json"
    RESULT="output/$SAIDA/"
}

cmd_figuras() {
    docker compose run --rm --no-deps -v "$PWD/simulators/market-opentes:/market:ro" \
        -v "$PWD/$CASO:/app/src/data/13Bus" \
        -e PYTHONPATH=/market -e MARKET_GRID_DIR=/app/src/data/13Bus -e MPLCONFIGDIR=/tmp \
        mosaik python -m market_opentes.figuras --resultados "/app/output/$SAIDA"
    RESULT="output/$SAIDA/figuras/"
}

cmd_caso() {
    docker compose run --rm --no-deps -w /app grid python src/simulators/gen_ieee13_market.py
    _sensibilidade sensitivity_day.npz ""
    _sensibilidade sensitivity_fase.npz --por-fase
    RESULT="$CASO/"
}

COMMAND="${1:-}"
case "$COMMAND" in
    ""|-h|--help|help) usage; exit 0 ;;
    market|centralizado|figuras|caso) ;;
    *) echo "!! comando desconhecido: '${COMMAND}' (use opentes --help)" >&2; exit 1 ;;
esac

_cleanup
echo ">> [OpenTES] ${COMMAND} (resultados em output/$SAIDA)"
"cmd_${COMMAND}"
_cleanup
# Os conteineres gravam como root; devolve os arquivos a quem rodou o script.
docker run --rm -v "$PWD/output:/o" -v "$PWD/$CASO:/c" opentes/mosaik:local \
    chown -R "$(id -u):$(id -g)" /o /c >/dev/null 2>&1 || true
echo ">> [OpenTES] '${COMMAND}' concluido: ${RESULT}"
