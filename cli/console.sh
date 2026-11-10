#!/usr/bin/env bash
#
# Console interativo do OpenTES. Abre com `opentes` ou `./run.sh` (sem
# argumentos), ou com `opentes console`.
#
# Tudo o que ele executa passa pelo proprio run.sh, com as variaveis da
# configuracao escolhida; a saida completa de cada execucao vai para um log em
# output/console/, e na tela fica so o andamento. As escolhas ficam salvas em
# .opentes.env, na raiz do repositorio, e valem para a proxima sessao.

set -uo pipefail
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
cd "$RAIZ"
CONF="$RAIZ/.opentes.env"
LOGS="$RAIZ/output/console"
CASO="simulators/grid-opentes/src/data/13Bus"

# --------------------------------------------------------------------------
# Cores
# --------------------------------------------------------------------------
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ] && [ "$(tput colors 2>/dev/null || echo 0)" -ge 8 ]; then
    VERDE=$'\e[38;5;64m'; VERDE_CLARO=$'\e[38;5;76m'; CINZA=$'\e[38;5;245m'
    AMARELO=$'\e[38;5;178m'; VERMELHO=$'\e[38;5;160m'; CIANO=$'\e[38;5;37m'
    NEGRITO=$'\e[1m'; NORMAL=$'\e[0m'
else
    VERDE=""; VERDE_CLARO=""; CINZA=""; AMARELO=""; VERMELHO=""; CIANO=""
    NEGRITO=""; NORMAL=""
fi
OK="${VERDE_CLARO}●${NORMAL}"; ALERTA="${AMARELO}●${NORMAL}"; FALHA="${VERMELHO}●${NORMAL}"

largura() { tput cols 2>/dev/null || echo 80; }
linha() { printf '%s%s%s\n' "$CINZA" "$(printf '─%.0s' $(seq 1 "${1:-66}"))" "$NORMAL"; }
titulo() { printf '\n %s%s%s\n' "$NEGRITO$VERDE" "$1" "$NORMAL"; linha 66; }
# printf conta bytes; com acentos o alinhamento precisa contar caracteres.
pad() { printf '%s%*s' "$1" $(( $2 > ${#1} ? $2 - ${#1} : 0 )) ""; }
item() { printf '   %s%-3s%s %s %s%s%s\n' "$VERDE_CLARO" "$1" "$NORMAL" "$(pad "$2" 28)" "$CINZA" "${3:-}" "$NORMAL"; }
campo() { printf '   %s %s\n' "$(pad "$1" 22)" "$2"; }
nota() { printf ' %s%s%s\n' "$CINZA" "$1" "$NORMAL"; }
pausa() { printf '\n %sEnter para voltar ao menu%s ' "$CINZA" "$NORMAL"; read -r _ || true; }

# --------------------------------------------------------------------------
# Configuracao: valores padrao, leitura e gravacao de .opentes.env
# --------------------------------------------------------------------------
CHAVES=(MARKET_FASE MARKET_DISPOSITIVO MARKET_REGULADOR NET_BACKEND NET_TIME_SCALE
        NET_DROP_PROBABILITY TISCH_MAC TISCH_CELLS TISCH_RATE_BPS MARKET_CRITERIO
        MARKET_EPS_REL MARKET_EPS MARKET_SCENARIOS CPLEX_HOME)

padroes() {
    MARKET_FASE=1; MARKET_DISPOSITIVO=independente; MARKET_REGULADOR=previsao
    NET_BACKEND=ideal; NET_TIME_SCALE=1.0; NET_DROP_PROBABILITY=0.0
    # rede de radio do OMNeT++: TSCH (6TiSCH) com 2 fatias por enlace, como na
    # referencia, ou Wi-SUN FAN a 50 kbps
    TISCH_MAC=tsch; TISCH_CELLS=2; TISCH_RATE_BPS=50000
    MARKET_CRITERIO=relativo; MARKET_EPS_REL=1e-3; MARKET_EPS=1e-3
    MARKET_SCENARIOS=1
    CPLEX_HOME="${CPLEX_HOME:-}"
    if [ -z "$CPLEX_HOME" ]; then
        local c
        for c in "$HOME"/IBM/CPLEX_Studio*/cplex /opt/ibm/ILOG/CPLEX_Studio*/cplex; do
            [ -x "$c/bin/x86-64_linux/cplex" ] && CPLEX_HOME="$c" && break
        done
    fi
}

carregar() {
    padroes
    [ -f "$CONF" ] || return 0
    local chave valor k
    while IFS='=' read -r chave valor; do
        for k in "${CHAVES[@]}"; do
            [ "$chave" = "$k" ] && printf -v "$k" '%s' "$valor"
        done
    done < "$CONF"
}

salvar() {
    local k
    {
        echo "# Configuracao do console do OpenTES (cli/console.sh). Pode apagar."
        for k in "${CHAVES[@]}"; do echo "$k=${!k}"; done
    } > "$CONF"
}

exportar() {
    local k
    for k in "${CHAVES[@]}"; do export "${k?}"; done
    export OPENTES_SAIDA
    OPENTES_SAIDA="$(saida)"
}

# Uma pasta de resultados por configuracao, para uma execucao nao apagar a outra.
saida() {
    local s=market
    [ "$MARKET_FASE" = "0" ] && s=market_por_no
    [ "$MARKET_FASE" = "1" ] && [ "$MARKET_DISPOSITIVO" = "equilibrado" ] && s="${s}_equilibrado"
    if [ "$NET_BACKEND" = "omnet" ]; then
        if [ "$TISCH_MAC" = "wisun" ]; then
            s="${s}_wisun_$(( TISCH_RATE_BPS / 1000 ))k"
        else
            s="${s}_omnet"
            [ "$TISCH_CELLS" != "2" ] && s="${s}_c${TISCH_CELLS}"
        fi
    fi
    [ "$NET_BACKEND" = "lossy" ] && s="${s}_perda"
    echo "$s"
}

desc_formulacao() { [ "$MARKET_FASE" = "1" ] && echo "por fase" || echo "por barra"; }
desc_inversor() {
    [ "$MARKET_FASE" = "0" ] && { echo "carga equilibrada por barra"; return; }
    [ "$MARKET_DISPOSITIVO" = "equilibrado" ] && echo "três fios" || echo "quatro fios"
}
desc_rede() {
    case "$NET_BACKEND" in
        ideal) echo "ideal" ;;
        lossy) echo "com perda ($(awk "BEGIN{printf \"%g\", $NET_DROP_PROBABILITY*100}")%)" ;;
        omnet) if [ "$TISCH_MAC" = "wisun" ]; then
                   echo "Wi-SUN FAN (OMNeT++), $(( TISCH_RATE_BPS / 1000 )) kbps"
               else
                   echo "6TiSCH (OMNeT++), $TISCH_CELLS fatia(s) por enlace"
               fi ;;
        *) echo "$NET_BACKEND" ;;
    esac
}
desc_criterio() {
    [ "$MARKET_CRITERIO" = "relativo" ] && echo "relativo, ε = $MARKET_EPS_REL da potência" \
        || echo "absoluto, |Δλ| ≤ $MARKET_EPS"
}

# --------------------------------------------------------------------------
# Abertura e estado
# --------------------------------------------------------------------------
logo() {
    local margem=$(( ($(largura) - 60) / 2 ))
    if [ "$margem" -ge 0 ] && [ -f cli/logo.txt ]; then
        printf '\n'
        # verde da marca (#144A02), clareado no topo para aparecer em fundo escuro
        local i=0 n cor l
        n=$(wc -l < cli/logo.txt)
        while IFS= read -r l; do
            if [ -z "$VERDE" ]; then cor=""
            elif [ "${COLORTERM:-}" = truecolor ] || [ "${COLORTERM:-}" = 24bit ]; then
                cor=$(printf '\e[38;2;%d;%d;%dm' $((120 - 80 * i / n)) $((200 - 100 * i / n)) $((40 - 30 * i / n)))
            elif [ $((2 * i)) -lt "$n" ]; then cor=$'\e[38;5;70m'
            else cor=$'\e[38;5;64m'; fi
            printf '%*s%s%s%s\n' "$margem" "" "$cor" "$l" "$NORMAL"
            i=$((i + 1))
        done < cli/logo.txt
    fi
    local sub="Mercado transativo por fase · IEEE 13 barras"
    local sub2="PADE · Mosaik · OpenDSS · OMNeT++    GREI · UFC"
    printf '\n%*s%s%s%s\n' $(( ($(largura) - ${#sub}) / 2 )) "" "$NEGRITO" "$sub" "$NORMAL"
    printf '%*s%s%s%s\n' $(( ($(largura) - ${#sub2}) / 2 )) "" "$CINZA" "$sub2" "$NORMAL"
}

cabecalho() {
    printf '\n %s▮▮▮ OpenTES%s %s· mercado transativo por fase · IEEE 13 barras%s\n' \
        "$NEGRITO$VERDE" "$NORMAL" "$CINZA" "$NORMAL"
}

DOCKER_OK=0
estado() {
    titulo "Ambiente"
    if docker info >/dev/null 2>&1; then
        DOCKER_OK=1
        printf '   %s Docker em execução\n' "$OK"
    else
        DOCKER_OK=0
        printf '   %s Docker não responde: inicie o serviço do Docker\n' "$FALHA"
    fi
    if [ "$DOCKER_OK" = 1 ]; then
        local faltam=() img
        for img in pade grid mosaik comm; do
            docker image inspect "opentes/$img:local" >/dev/null 2>&1 || faltam+=("$img")
        done
        if [ ${#faltam[@]} -eq 0 ]; then
            printf '   %s Imagens construídas (pade, grid, mosaik, comm)\n' "$OK"
        else
            printf '   %s Faltam imagens: %s %s(menu b)%s\n' "$ALERTA" "${faltam[*]}" "$CINZA" "$NORMAL"
        fi
    fi
    if [ -n "$CPLEX_HOME" ] && [ -x "$CPLEX_HOME/bin/x86-64_linux/cplex" ]; then
        printf '   %s CPLEX em %s\n' "$OK" "${CPLEX_HOME/#$HOME/\~}"
    else
        printf '   %s CPLEX não encontrado %s(configurar, opção 8)%s\n' "$FALHA" "$CINZA" "$NORMAL"
    fi
    local mat=sensitivity_fase.npz
    [ "$MARKET_FASE" = "0" ] && mat=sensitivity_day.npz
    if [ -f "$CASO/$mat" ]; then
        printf '   %s Caso IEEE 13 pronto %s(%s)%s\n' "$OK" "$CINZA" "$mat" "$NORMAL"
    else
        printf '   %s Matriz %s ausente: é gerada na primeira execução\n' "$ALERTA" "$mat"
    fi
}

configuracao_resumo() {
    titulo "Configuração atual"
    campo "Formulação" "$NEGRITO$(desc_formulacao)$NORMAL"
    campo "Inversor" "$(desc_inversor)"
    campo "Regulador" "$([ "$MARKET_REGULADOR" = previsao ] && echo "derivações pela previsão" || echo "neutro")"
    campo "Rede entre agentes" "$(desc_rede)"
    campo "Critério de parada" "$(desc_criterio)"
    campo "Cenários" "$([ "$MARKET_SCENARIOS" = 1 ] && echo "1, determinístico" || echo "$MARKET_SCENARIOS por incerteza (9 combinados)")"
    campo "Resultados em" "${CIANO}output/$(saida)/$NORMAL"
}

# Resumo dos resultados de uma pasta; usa o python3 do host so com a biblioteca padrao.
resumo_resultados() {
    local pasta="output/$1"
    command -v python3 >/dev/null 2>&1 || { nota "python3 ausente: resumo indisponível"; return; }
    [ -d "$pasta" ] || { nota "Ainda não há resultados em $pasta/"; return; }
    python3 - "$pasta" "$VERDE_CLARO" "$NORMAL" "$CINZA" <<'PY'
import csv, json, re, sys
from pathlib import Path
p, cor, normal, cinza = Path(sys.argv[1]), *sys.argv[2:5]
def mostra(rotulo, valor): print(f"   {rotulo:<22} {valor}")
run = p / "run.json"
if run.exists():
    r = json.loads(run.read_text())
    mostra("Negociação", f"{cor}{r['rounds']} rodadas{normal}, "
           + ("convergiu" if r["converged"] else "NÃO convergiu")
           + f", {r['retransmissions']} retransmissões")
    c3 = [h.get("cycle3_net_s") for h in r.get("history", []) if h.get("cycle3_net_s")]
    if c3:
        mostra("Rede, ciclo 3", f"{min(c3):.0f} a {max(c3):.0f} s por rodada "
               f"(orçamento 300 s), {sum(c3)/3600:.1f} h no total")
hist = p / "history.json"
if hist.exists() and not run.exists():
    h = json.loads(hist.read_text())
    mostra("Negociação centralizada", f"{cor}{len(h)} rodadas{normal}")
fl = p / "flexibility.csv"
if fl.exists():
    e = sum(float(x["energy_shifted_kwh"]) for x in csv.DictReader(open(fl)))
    mostra("Energia deslocada", f"{e:,.0f} kWh".replace(",", "."))
res = p / "result_negociado.csv"
if res.exists():
    linhas = list(csv.reader(open(res)))
    cab, dados = linhas[0], [l for l in linhas[1:] if l]
    sub = {"sourcebus", "650", "rg60"}
    alto = baixo = fora = n = 0
    vmin, vmax = 9.0, 0.0
    for i, h in enumerate(cab[1:], start=1):
        m = re.search(r"Bus-([^-]+)-V([123])_pu", h)
        if not m:
            continue
        col = [float(l[i]) for l in dados]
        if max(col) < 0.5:
            continue
        fora += sum(1 for v in col if v < 0.95 or v > 1.05); n += len(col)
        if m.group(1) in sub:
            continue
        alto += sum(1 for v in col if v > 1.03 + 1e-9)
        baixo += sum(1 for v in col if v < 0.97 - 1e-9)
        vmin, vmax = min(vmin, min(col)), max(vmax, max(col))
    mostra("Tensão por fase", f"{cor}{alto}{normal} acima de 1,03 pu · {cor}{baixo}{normal} abaixo de 0,97 pu")
    mostra("Faixa A da ANSI", f"{cor}{fora}{normal} de {n} leituras fora · de {vmin:.4f} a {vmax:.4f} pu")
fig = p / "figuras"
if fig.exists():
    mostra("Figuras", f"{len(list(fig.glob('*.png')))} em {fig}/")
PY
}

# --------------------------------------------------------------------------
# Execucao
# --------------------------------------------------------------------------
ULTIMO=""

# O que esta acontecendo agora, em uma linha. $1 = comando, $2 = log do run.sh.
# Na co-simulacao, a rodada e a hora da operacao vem do log do conteiner do PADE;
# na centralizada, da tabela de rodadas que o dual.py imprime.
andamento() {
    local etapa
    etapa=$(grep -a '^>>' "$2" 2>/dev/null | tail -n 1 | sed "s/^>> *//; s/\[OpenTES\] *//; s/ (resultados em .*//")
    case "$etapa" in
        "passada 'baseline'"*) etapa="linha de base · prosumidores sem mecanismo" ;;
        "passada 'negociado'"*) etapa="passada negociada · subindo os agentes" ;;
    esac
    # o que o Mosaik disse depois da ultima linha ">>" do run.sh
    local depois
    depois=$(awk '/^>>/ { b = ""; next } { b = b "\n" $0 } END { print b }' "$2" 2>/dev/null)
    case "$depois" in
        *"Simulation finished"*) echo "gravando os resultados"; return ;;
        *"Starting simulation"*)
            if grep -aq "passada 'negociado'" "$2"; then etapa="passada negociada · simulando o dia"
            else etapa="linha de base · simulando o dia"; fi ;;
    esac
    local fonte=""
    if [ "$1" = market ]; then
        fonte=$(docker logs --tail 80 opentes-pade 2>&1)
    elif [ "$1" = centralizado ]; then
        fonte=$(tail -n 40 "$2" 2>/dev/null)
    fi
    local agora
    agora=$(printf '%s\n' "$fonte" | sed 's/\x1b\[[0-9;]*m//g' | awk '
        /negociacao encerrada:/ { sub(/.*--> negociacao encerrada: /, ""); u = "operação do dia · acordo: " $0; next }
        /rodada [0-9]+: .*de Pmax/ {
            match($0, /rodada [0-9]+/); r = substr($0, RSTART + 7, RLENGTH - 7)
            match($0, /\([0-9.e+-]+ de Pmax/); d = substr($0, RSTART + 1, RLENGTH - 9)
            u = "negociação · rodada " r " · desacordo " d " de Pmax"; next }
        /^ +[0-9]+ +[0-9.e+-]+ +[0-9.]+ +[0-9.e+-]+ / { u = "negociação · rodada " $1 " · desacordo " $4 " de Pmax"; next }
        /^convergiu em|^NAO convergiu/ { u = $0; next }
        /t=[0-9]+: / {
            match($0, /t=[0-9]+/); t = substr($0, RSTART + 2, RLENGTH - 2) * 15
            u = sprintf("operação · %02d:%02d do dia", int(t / 60), t % 60); next }
        /abrindo a negociacao/ { u = "negociação · abrindo" }
        END { print u }')
    [ -n "$agora" ] && echo "$agora" || echo "${etapa:-preparando}"
}

# $1 = comando do run.sh; o resto, descricao. Mostra o andamento e o resumo.
executar() {
    local cmd=$1; shift
    local desc="$*"
    if [ "$DOCKER_OK" != 1 ]; then printf '\n %s!! O Docker não responde.%s\n' "$VERMELHO" "$NORMAL"; return 1; fi
    if [ "$cmd" != "caso" ] && [ "$cmd" != "figuras" ] && [ ! -x "${CPLEX_HOME}/bin/x86-64_linux/cplex" ]; then
        printf '\n %s!! CPLEX não encontrado. Configure o caminho (configurar, opção 8).%s\n' "$VERMELHO" "$NORMAL"
        return 1
    fi
    exportar
    mkdir -p "$LOGS"
    local log; log="$LOGS/$(date +%Y%m%d-%H%M%S)-${cmd}-$(saida).log"
    ULTIMO_LOG="$log"
    printf '\n %s▶ %s%s %s(%s)%s\n' "$NEGRITO$VERDE" "$desc" "$NORMAL" "$CINZA" "output/$(saida)/" "$NORMAL"
    ./run.sh "$cmd" > "$log" 2>&1 &
    local pid=$! inicio=$SECONDS quadro=0 n=0 texto="preparando" anterior=""
    local giro=(⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏)
    trap 'kill "$pid" 2>/dev/null; printf "\n %sinterrompido; limpando os contêineres...%s\n" "$AMARELO" "$NORMAL"; docker compose down --remove-orphans >/dev/null 2>&1' INT
    while kill -0 "$pid" 2>/dev/null; do
        # o andamento e lido a cada segundo; a animacao gira a cada 0,2 s
        [ $((n % 5)) -eq 0 ] && texto=$(andamento "$cmd" "$log")
        n=$((n + 1))
        local t=$(( SECONDS - inicio ))
        if [ -t 1 ]; then
            printf '\r   %s%s%s %02d:%02d  %s\e[K' "$VERDE_CLARO" "${giro[quadro]}" "$NORMAL" \
                $((t / 60)) $((t % 60)) "${texto:0:$(( $(largura) - 16 ))}"
            quadro=$(( (quadro + 1) % ${#giro[@]} ))
        elif [ "$texto" != "$anterior" ]; then
            printf '   %02d:%02d  %s\n' $((t / 60)) $((t % 60)) "$texto"
            anterior=$texto
        fi
        sleep 0.2
    done
    wait "$pid"; local st=$?
    trap - INT
    local t=$(( SECONDS - inicio ))
    [ -t 1 ] && printf '\r\e[K'
    if [ "$st" -eq 0 ]; then
        printf '   %s✔ concluído em %02d:%02d%s\n' "$VERDE_CLARO" $((t / 60)) $((t % 60)) "$NORMAL"
        if [ "$cmd" != "caso" ]; then titulo "Resultados"; resumo_resultados "$(saida)"; fi
    else
        printf '   %s✘ falhou após %02d:%02d (código %d)%s\n' "$VERMELHO" $((t / 60)) $((t % 60)) "$st" "$NORMAL"
        nota "Últimas linhas do log:"
        tail -n 12 "$log" | sed 's/^/     /'
    fi
    nota "Log completo: ${log#$RAIZ/}"
    return "$st"
}

acao() {
    case "$1" in
        1) executar market "Co-simulação completa" ;;
        2) executar centralizado "Negociação centralizada" ;;
        3) executar figuras "Figuras" ;;
        4) executar centralizado "Fluxo completo: negociação centralizada" \
               && executar market "Fluxo completo: co-simulação" \
               && executar figuras "Fluxo completo: figuras" ;;
        5) executar caso "Regenerar o caso IEEE 13 e as matrizes" ;;
    esac
}

# --------------------------------------------------------------------------
# Configurar
# --------------------------------------------------------------------------
perguntar() {   # $1 = pergunta, $2 = valor atual; devolve em RESPOSTA
    printf '   %s [%s]: ' "$1" "$2"; read -r RESPOSTA || RESPOSTA=""
    [ -z "$RESPOSTA" ] && RESPOSTA="$2"
}

# Inteiro dentro de [min, max]; senao, fica o valor atual.
inteiro_em() {   # $1 = texto, $2 = min, $3 = max, $4 = atual
    case "$1" in ''|*[!0-9]*) echo "$4"; return ;; esac
    if [ "$1" -ge "$2" ] && [ "$1" -le "$3" ]; then echo "$1"; else echo "$4"; fi
}

escolher_rede() {
    titulo "Rede entre os agentes"
    item 1 "Ideal" "entrega imediata, sem perda"
    item 2 "6TiSCH (OMNeT++)" "a rede da tese: TSCH, fatias reservadas por enlace"
    item 3 "Wi-SUN FAN (OMNeT++)" "mesmo rádio, acesso por disputa, sem fatias"
    item 4 "Com perda" "canal de 50 kbps com perda sorteada por mensagem"
    printf '\n %srede ›%s ' "$VERDE_CLARO" "$NORMAL"; read -r r || return
    case "$r" in
        1) NET_BACKEND=ideal; NET_TIME_SCALE=1.0 ;;
        2) NET_BACKEND=omnet; NET_TIME_SCALE=0.02; TISCH_MAC=tsch
           nota "Cada fatia leva um quadro de 127 bytes a cada slotframe de 4,04 s. A tese"
           nota "não informa o número; 2 é a calibração com os tempos dela. Menos fatias,"
           nota "execução mais longa: com 2, cerca de 18 min; com 1, o dobro; com 20, 3 min."
           perguntar "Fatias por enlace, de 1 a 20" "$TISCH_CELLS"
           TISCH_CELLS=$(inteiro_em "$RESPOSTA" 1 20 "$TISCH_CELLS") ;;
        3) NET_BACKEND=omnet; NET_TIME_SCALE=0.02; TISCH_MAC=wisun
           nota "50 kbps é o mesmo rádio da tese; taxas maiores encurtam o alcance"
           nota "(menos enlaces, mais saltos)."
           perguntar "Taxa em kbps: 50, 150 ou 300" "$(( TISCH_RATE_BPS / 1000 ))"
           case "$RESPOSTA" in 50|150|300) TISCH_RATE_BPS=$(( RESPOSTA * 1000 )) ;; esac ;;
        4) NET_BACKEND=lossy; NET_TIME_SCALE=0.02
           perguntar "Perda por mensagem, em %" "$(awk "BEGIN{printf \"%g\", $NET_DROP_PROBABILITY*100}")"
           NET_DROP_PROBABILITY=$(awk "BEGIN{printf \"%g\", $RESPOSTA/100}") ;;
    esac
}

configurar() {
    while true; do
        clear; cabecalho
        titulo "Configurar"
        item 1 "Formulação" "$(desc_formulacao)"
        item 2 "Inversor" "$(desc_inversor)"
        item 3 "Regulador" "$([ "$MARKET_REGULADOR" = previsao ] && echo "derivações pela previsão" || echo "neutro")"
        item 4 "Rede entre agentes" "$(desc_rede)"
        item 5 "Critério de parada" "$MARKET_CRITERIO"
        item 6 "Tolerância" "$([ "$MARKET_CRITERIO" = relativo ] && echo "ε_rel = $MARKET_EPS_REL" || echo "ε = $MARKET_EPS")"
        item 7 "Cenários do prosumidor" "$MARKET_SCENARIOS"
        item 8 "Caminho do CPLEX" "${CPLEX_HOME:-não definido}"
        item p "Restaurar os padrões"
        item v "Voltar"
        printf '\n %sAs escolhas ficam salvas em .opentes.env%s\n' "$CINZA" "$NORMAL"
        printf '\n %sopção ›%s ' "$VERDE_CLARO" "$NORMAL"; read -r op || return
        case "$op" in
            1) [ "$MARKET_FASE" = 1 ] && MARKET_FASE=0 || MARKET_FASE=1 ;;
            2) if [ "$MARKET_FASE" = 1 ]; then
                   [ "$MARKET_DISPOSITIVO" = independente ] && MARKET_DISPOSITIVO=equilibrado || MARKET_DISPOSITIVO=independente
               fi ;;
            3) [ "$MARKET_REGULADOR" = previsao ] && MARKET_REGULADOR=neutro || MARKET_REGULADOR=previsao ;;
            4) escolher_rede ;;
            5) [ "$MARKET_CRITERIO" = relativo ] && MARKET_CRITERIO=absoluto || MARKET_CRITERIO=relativo ;;
            6) if [ "$MARKET_CRITERIO" = relativo ]; then
                   perguntar "Desacordo máximo, em fração da potência" "$MARKET_EPS_REL"; MARKET_EPS_REL=$RESPOSTA
               else
                   perguntar "Variação máxima de λ" "$MARKET_EPS"; MARKET_EPS=$RESPOSTA
               fi ;;
            7) [ "$MARKET_SCENARIOS" = 1 ] && MARKET_SCENARIOS=3 || MARKET_SCENARIOS=1 ;;
            8) perguntar "Pasta cplex (a que contém bin/)" "${CPLEX_HOME:-}"; CPLEX_HOME="${RESPOSTA/#\~/$HOME}" ;;
            p|P) local c=$CPLEX_HOME; padroes; CPLEX_HOME=$c ;;
            v|V|q|Q|"") return ;;
        esac
        salvar
    done
}

# --------------------------------------------------------------------------
# Ambiente
# --------------------------------------------------------------------------
reiniciar() {
    printf '\n %sDerrubando contêineres e a rede do OpenTES...%s\n' "$CINZA" "$NORMAL"
    docker compose down --remove-orphans 2>&1 | sed 's/^/   /' | tail -n 4
    docker ps -aq --filter "name=opentes-" | xargs -r docker rm -f >/dev/null 2>&1
    printf '   %s✔ ambiente limpo%s\n' "$VERDE_CLARO" "$NORMAL"
}

reconstruir() {
    mkdir -p "$LOGS"
    local log; log="$LOGS/$(date +%Y%m%d-%H%M%S)-build.log"
    printf '\n %s▶ Construindo as imagens%s %s(a primeira vez compila o OMNeT++ e leva minutos)%s\n' \
        "$NEGRITO$VERDE" "$NORMAL" "$CINZA" "$NORMAL"
    docker compose build 2>&1 | tee "$log" | grep --line-buffered -E "Built|ERROR|error" | sed 's/^/   /'
    nota "Log completo: ${log#$RAIZ/}"
}

ver_log() {
    local log="${ULTIMO_LOG:-}"
    [ -z "$log" ] && log=$(ls -t "$LOGS"/*.log 2>/dev/null | head -n 1)
    [ -z "$log" ] && { nota "Nenhum log ainda."; return; }
    if command -v less >/dev/null 2>&1; then less -R +G "$log"; else tail -n 60 "$log"; fi
}

abrir_figuras() {
    local pasta="output/$(saida)/figuras"
    [ -d "$pasta" ] || { nota "Ainda não há figuras em $pasta/ (opção 3)."; return; }
    titulo "Figuras em $pasta/"
    ls "$pasta" | sed 's/^/   /'
    command -v xdg-open >/dev/null 2>&1 && xdg-open "$pasta" >/dev/null 2>&1 &
}

documentacao() {
    titulo "Documentação"
    local url=https://grei-ufc.github.io/co-simulation-opentes/
    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$url" >/dev/null 2>&1 &
        nota "Abrindo $url no navegador."
    fi
    nota "As páginas estão em docs/. Para o site local, com mudanças ainda não publicadas:"
    printf '     %suv run --only-group docs mkdocs serve%s\n' "$CIANO" "$NORMAL"
}

ajuda() {
    titulo "Atalhos de linha de comando"
    local c
    for c in "opentes|este console" "opentes market|co-simulação completa" \
             "opentes centralizado|negociação sem agentes" "opentes figuras|figuras da última execução" \
             "opentes caso|regenera o caso IEEE 13" "opentes --help|todos os comandos e variáveis" \
             "MARKET_FASE=0 opentes market|qualquer variável vale na frente"; do
        printf '   %s%s%s %s\n' "$CIANO" "$(pad "${c%%|*}" 31)" "$NORMAL" "${c#*|}"
    done
    if ! command -v opentes >/dev/null 2>&1; then
        printf '\n %s!! O comando opentes ainda não está instalado nesta máquina. Para instalar:%s\n' "$AMARELO" "$NORMAL"
        printf '     %sln -s "%s/run.sh" ~/.local/bin/opentes%s\n' "$CIANO" "$RAIZ" "$NORMAL"
        nota "Até lá, ./run.sh na pasta do projeto faz o mesmo."
    fi
    nota "O console só chama o opentes (o run.sh) com a configuração escolhida."
}

# --------------------------------------------------------------------------
# Menu principal
# --------------------------------------------------------------------------
menu() {
    titulo "Executar"
    item 1 "Co-simulação completa" "agentes, rede elétrica e operação · 1 a 40 min"
    item 2 "Negociação centralizada" "sem agentes, com liquidação · ~1 min"
    item 3 "Figuras" "a partir dos resultados · segundos"
    item 4 "Fluxo completo" "2, depois 1, depois 3"
    item 5 "Regenerar o caso IEEE 13" "só depois de mudar o circuito"
    titulo "Ajustar e acompanhar"
    item c "Configurar" "formulação, inversor, rede, critério..."
    item r "Refazer o último comando" "${ULTIMO:+opção $ULTIMO}"
    item s "Resultados" "resumo da configuração atual"
    item l "Log da última execução"
    item f "Abrir as figuras"
    item d "Documentação"
    titulo "Manutenção"
    item b "Construir as imagens" "docker compose build"
    item x "Reiniciar o ambiente" "derruba contêineres presos"
    item h "Atalhos de linha de comando"
    item q "Sair"
}

principal() {
    carregar
    clear
    logo
    estado
    configuracao_resumo
    while true; do
        menu
        printf '\n %sopção ›%s ' "$VERDE_CLARO" "$NORMAL"
        read -r op || { printf '\n'; break; }
        case "$op" in
            1|2|3|4|5) ULTIMO=$op; acao "$op"; pausa ;;
            r|R) if [ -n "$ULTIMO" ]; then acao "$ULTIMO"; else nota "Nada executado ainda nesta sessão."; fi; pausa ;;
            c|C) configurar ;;
            s|S) titulo "Resultados em output/$(saida)/"; resumo_resultados "$(saida)"; pausa ;;
            l|L) ver_log ;;
            f|F) abrir_figuras; pausa ;;
            d|D) documentacao; pausa ;;
            b|B) reconstruir; pausa ;;
            x|X) reiniciar; pausa ;;
            h|H) ajuda; pausa ;;
            q|Q|sair|exit) printf '\n %sAté a próxima.%s\n\n' "$VERDE" "$NORMAL"; break ;;
            "") ;;
            *) nota "Opção desconhecida: $op" ;;
        esac
        clear; cabecalho; estado; configuracao_resumo
    done
}

principal
