# Integração OpenTES

Como os simuladores dos times TTESO, TSCC e TSRE foram reunidos no repositório
agregador `co-simulation-opentes`, **o que foi alterado em cada componente para
que funcionassem juntos, e por quê**.

Descreve o estado ATUAL do código, não o histórico de tentativas. Para a leitura
das saídas, ver [`RESULTADOS.md`](RESULTADOS.md); para a formulação do mercado,
[`MERCADO.md`](MERCADO.md); para o mapa geral, [`GUIA.md`](GUIA.md).

Premissa que guiou as escolhas: manter os simuladores fiéis aos repositórios de
origem. As mudanças servem para permitir a execução integrada, padronizar
Docker e Python, evitar conflito de portas e organizar as saídas.

## Objetivo

O fluxo alvo da integração é:

```text
PADE -> Mosaik -> OMNeT++ -> Mosaik -> PADE -> Mosaik -> OpenDSS
```

Dois benchmarks convivem no repositório, com propósitos diferentes:

| Benchmark | Cenário | Para quê |
|---|---|---|
| **IEEE 13 Barras** | `integrated`, `ieee13` | validar a plataforma de ponta a ponta, com controle Volt/Var local |
| **Rede de 75 barras** | `market` | exercitar a camada de mercado transativo, com negociação multiagente |

## Estrutura

A integração é organizada em **containers funcionais** (nomes refletem a
função, não o time de origem):

- `simulators/comm-opentes`: rede de comunicação (OMNeT++ + bridge ZMQ).
- `simulators/pade-opentes`: runtime PADE (Python 3.12) + agentes.
- `simulators/mosaik-opentes`: engine Mosaik + `scenarios/` + `collectors/`.
- `simulators/grid-opentes`: rede elétrica (OpenDSS + DERs): IEEE 13 Barras
  e a rede de 75 barras do mercado.
- `simulators/market-opentes`: modelos de otimização do mercado transativo
  (prosumidor, concentrador, DSO), decomposição dual e figuras. Fica fora dos
  agentes de propósito, para poder rodar sem subir a co-simulação inteira.

Proveniência: o conteúdo vem dos repos dos times — TSCC (comunicação) foi
fragmentado em `comm-opentes` (OMNeT++) + agentes em `pade-opentes` + cenário e
collectors em `mosaik-opentes`; TTESO contribuiu com a lib PADE (`pade-opentes`);
TSRE virou `grid-opentes`. O registro por componente está na seção
"Alterações por componente", adiante.

## Decisões Técnicas

- O repositório raiz é o agregador; os `.git` internos dos repos importados
  foram removidos para o agregador versionar a base integrada.
- Topologia de **4 containers funcionais** (`comm`, `pade`, `mosaik`, `grid`),
  um Dockerfile por container.
- Os collectors vivem em `mosaik-opentes/collectors/`: `comm_collector.py`
  (telemetria de rede via `mosaik_api_v3`) e `elec_collector.py` (dados elétricos
  com timestamp, `mosaik_api` legado, roda como container remoto).
- O controle do TSRE foi trazido para os **agentes PADE**. Na aplicação do
  IEEE 13 **não há bateria**: o atuador é o **inversor fotovoltaico**, com
  controle **Volt/Var** (o agente recebe a tensão e calcula P e Q). O ganho é
  configurável (`Q_MAX_PCT`, `V_DEADBAND`) e o padrão é **suave**, porque ganho
  alto + vários inversores + atraso/perda da rede desestabiliza (ver Resultados).
- O `mosaik_driver.py` do PADE (classe `MosaikCon`) é a ponte oficial PADE↔Mosaik
  (atualizada para Mosaik 3).
- Mosaik padronizado em `3.5.0`; `py-dss-interface>=2.3.0` (wheels Linux,
  dispensa compilar a engine OpenDSS).
- Portas internas dos PADE publicadas deslocadas no host (ex.: `15678`) para
  evitar conflito com os simuladores do `grid`.
- Hosts/portas dos componentes são parametrizados por variáveis de ambiente
  (ex.: `PADE_HOST`, `OMNET_HOST`), sem editar os cenários.

O registro detalhado, componente por componente, está na próxima seção.

## Alterações por componente

Registro técnico do que mudou em cada peça e do motivo. É a parte que
responde "por que este arquivo está diferente do repositório de origem?".

### 1. Topologia: 4 containers funcionais

A integracao foi organizada em quatro containers, um por dominio (nomes refletem
a FUNCAO, nao o time):

```text
- comm-opentes   -> rede de comunicacao (OMNeT++ + bridge ZMQ)
- pade-opentes   -> agentes PADE (Python 3.12)
- mosaik-opentes -> orquestrador Mosaik + cenarios + collectors
- grid-opentes   -> rede eletrica IEEE 13 (OpenDSS via py-dss-interface)
```

Motivo: alinhar a dockerizacao aos dominios da co-simulacao. O TSCC original
juntava PADE+OMNeT+++Mosaik em um repo so; ele foi fragmentado nesses tres
destinos. O grid-opentes corresponde ao conteudo do TSRE (antes chamado
tsre-der-opentes).

Cada container tem UM Dockerfile ativo:
```text
- comm-opentes/Dockerfile   (base omnetpp/omnetpp:u22.04-6.0 + cppzmq)
- pade-opentes/Dockerfile   (python:3.12.11-slim + instala a lib PADE)
- mosaik-opentes/Dockerfile (python:3.12.11-slim + mosaik 3.5.0)
- grid-opentes/Dockerfile   (python:3.12.11-slim + requirements do TSRE)
```

O docker-compose.yaml da raiz e o ponto oficial de execucao; o script
run.sh e a forma recomendada de rodar (ver secao 7).

### 2. Collectors no Mosaik (saidos do TSRE/TSCC)

Os dois coletores vivem agora em mosaik-opentes/collectors/:

```text
- comm_collector.py -> telemetria da rede de comunicacao (pacotes, latencia,
  jitter, mensagens). Era o collector do TSCC.
- elec_collector.py -> dados eletricos com timestamp (tensoes, P/Q). Era o
  collector do TSRE (grid).
```

Motivo: registrar resultados e papel do ambiente Mosaik (o orquestrador), nao
dos simuladores de rede ou eletrico. O elec_collector roda como container remoto
(service elec-collector, porta 5673), preservando o formato original do TSRE.

### 3. Controle do TSRE migrado para o PADE: Volt/Var no inversor PV

Objetivo do projeto: trazer o controle para dentro dos agentes PADE. Na aplicacao
do IEEE 13 NAO ha bateria — o atuador e o proprio inversor fotovoltaico, com
controle Volt/Var.

```text
- O agente (pade-opentes/agents/agent_example_1_mosaik_updated.py, evolucao da
  dupla de agentes do first.py do TSCC) foi generalizado para N pares
  medidor/controlador. Para cada PV:
    AgenteA_i  -> mede a tensao da barra do PV_i e publica a medicao na rede
                  OMNeT++ (mensagem FIPA-ACL marcada com a barra).
    AgenteB_i  -> recebe a tensao da SUA barra (ja atrasada pela rede) e aplica
                  Volt/Var: P (ativa) = solar disponivel; Q (reativa) = f(V),
                  respeitando S = sqrt(P^2 + Q^2) <= kVA do inversor.
- Os parametros do Volt/Var sao configuraveis (Q_MAX_PCT, V_DEADBAND via env).
  O padrao e SUAVE (Q_MAX_PCT=0.05, V_DEADBAND=0.02).
```

Motivo do ganho suave: com os 5 inversores fazendo Volt/Var ao mesmo tempo,
somado ao atraso/perda da rede de comunicacao, um ganho agressivo (padrao IEEE
1547, 44% do kVA) faz o reativo SOBRE-INJETAR e DESESTABILIZA a rede (tensao
chegou a ~1,12 pu). Reduzindo o ganho, o controle regula de forma estavel. Esse
acoplamento (qualidade da comunicacao limita a agressividade segura do controle)
e um resultado central do benchmark.

### 4. Rede eletrica IEEE 13 + 5 PVs (do TSRE) e correcoes para Linux

Os arquivos do IEEE 13 com PV vieram do TSRE (grei-ufc/tsre-der-opentes, branch
paulo-victor): dados em grid-opentes/src/data/13Bus e o cenario de referencia.
Duas correcoes foram necessarias para rodar no Linux (o TSRE foi desenvolvido no
Windows):

```text
- grid-opentes/src/simulators/gen_pv_loadshapes.py: gera o arquivo
  ieee13_shape_pv_5min.dss (Loadshapes/Tshapes) a partir dos CSVs de
  irradiancia/temperatura. O ieee13_pv.dss referencia essas curvas (Daily/
  TDaily) mas o pv_creator nao as gerava -> sem elas, o OpenDSS nao cria os
  PVSystems (get_detected_pvsystems retornava vazio).
- run_ieee13_cosim_*.dss: "Redirect Loadshape.dss" corrigido para
  "LoadShape.dss" (case-sensitive no Linux; o redirect falho abortava a criacao
  dos PVs).
```

Apos isso, o bloco eletrico isolado (cenario ieee13) reproduz EXATAMENTE os
valores do TSRE (pico P_dc ~3024,6 / P_ac ~2854,2 / P_meas ~1902,7 kW).

### 5. Cenario integrado causal (mosaik-opentes/scenarios/first.py)

Evolucao do first.py do TSCC (que ja unia PADE+OMNeT+++Mosaik), agora fechando o
laco com o OpenDSS. Co-simula os 5 PVs e fecha o ciclo causal:

```text
OpenDSS resolve a tensao -> AgenteA_i mede e envia pela OMNeT++ (atraso/jitter/
perda) -> AgenteB_i decide P e Q (Volt/Var) -> PVSystem_i injeta -> OpenDSS
recalcula -> (proximo passo).
```

Para o Mosaik aceitar o laco, a leitura Bus->medidor e time_shifted (o medidor
reporta o ultimo estado resolvido), o que tambem quebra o ciclo algebrico
DSS->PADE->PVSystem->DSS.

O cenario roda duas vezes (CONTROL_ENABLED=0 baseline e =1 Volt/Var) e grava em
output/integrated/ com sufixo por execucao.

Outros cenarios em mosaik-opentes/scenarios/: star.py (comunicacao isolada) e
ieee13_smart_pv.py (rede eletrica isolada) — bancadas de teste de cada bloco.

### 6. Modelo de comunicacao (comm-opentes/omnetpp.ini)

```text
- drop_probability = 0.15  -> probabilidade de perda por pacote. E um PARAMETRO
  DE MODELO da qualidade do canal (herdado do TSCC), nao uma saida da
  co-simulacao; deve ser calibrado conforme a rede real da aplicacao.
- jitter_mean = 0.05       -> atraso estocastico medio (s).
- bandwidth_bps = 50000    -> banda do enlace.
- seed-set = 0 / seed-0-mt = 1 -> semente fixa, para reprodutibilidade entre
  execucoes (a ordem assincrona das mensagens ainda introduz pequena variacao).
```

Motivo da semente: deixar o experimento comparavel/reprodutivel sem deixar de ser
estocastico ao longo do tempo. (Discussao sobre o modelo de perda — fenomenologico
hoje, mecanistico/INET no futuro — em docs/INTEGRACAO.md.)

### 7. Execucao: run.sh

Script unico de execucao (./run.sh <comando>; ./run.sh --help lista tudo):

```text
cenarios     : integrated | ieee13 | star
experimentos : 48h | loss-sweep [tags...] | loss-multiseed
```

Antes eram 4 scripts (run_opentes.sh, run_48h.sh, run_loss_sweep.sh,
run_loss_multiseed.sh) que duplicavam a mesma logica (o cleanup() era identico
byte a byte nos 4). Foram unificados: os comandos agora compartilham os mesmos
internals e diferem so em parametros. O run.sh:

```text
- faz limpeza COMPLETA do Docker antes/depois (down de todos os profiles + rm
  de orfaos + rm da rede). Motivo: containers de profile nao sao removidos pelo
  "docker compose down" simples e seguram a rede, causando "network not found".
- no integrated, sobe os deps e ESPERA o comm (OMNeT++) compilar (probe ZMQ
  resiliente na porta 5555) antes de rodar o Mosaik. Motivo: evitar o race em
  que o Mosaik tenta conectar ao elec-collector antes de ele ligar.
- no ieee13 (que nao tem comm), sobe os deps e espera pelo LOG do
  elec-collector. Motivo: o mesmo race — o depends_on do compose so garante
  que o container iniciou, nao que o app esta ouvindo.
- nunca sonda as portas dos simuladores --remote do grid: eles aceitam UMA
  conexao Mosaik e encerram; um probe TCP mata o simulador (verificado: o
  container sai logo apos o connect). Por isso a prontidao deles e detectada
  por log, nunca por socket.
- restaura o omnetpp.ini (drop/seed/sim-time-limit) via trap, mesmo se
  interrompido no meio.
```

### 8. Saidas organizadas por cenario (output/)

```text
output/integrated/  -> result_{baseline,volt_var}.csv, comm_trace_{...}.csv,
                       dashboard_integrated.png (8 quadros), e duas figuras
                       dedicadas (plot_comparacao.py): comparacao_volt_var.png
                       (controle atuando x nao) e analise_comunicacao.png
                       (latencia/jitter/integridade/pacotes acumulados)
output/ieee13/      -> result_run_ieee13_cosim_pv_5min.csv, ieee13_dashboard.png
output/star/        -> results.csv, grafico_trafego.png
```

A explicacao detalhada de cada arquivo esta em docs/RESULTADOS.md. A pasta
output/ e ignorada pelo git (sao produtos de simulacao).

### 9. Padroes e dependencias

```text
- Mosaik padronizado em 3.5.0 (mesma versao do TSRE).
- py-dss-interface >= 2.3.0 (wheels manylinux: roda o OpenDSS no Linux sem
  compilar a engine).
- Portas internas dos PADE publicadas deslocadas no host (ex.: 15678) para
  evitar conflito com simuladores do grid.
```

### 10. Camada de mercado transativo (SiMTES)

```text
Porte do mercado transativo da tese de Lucas S. Melo (2022) e do repositorio
market-simulation para este stack. Formulacao, correspondencia com as equacoes
da tese, desvios e limitacoes conhecidas: docs/MERCADO.md.
```

```text
Novos:
  simulators/market-opentes/          pacote com os modelos de otimizacao
                                            (prosumidor, concentrador, DSO), a
                                            decomposicao dual, a fase de
                                            operacao e as figuras
  grid-opentes/src/simulators/
    gen_market_grid.py                      converte o force.json da tese para
                                            OpenDSS (rede MVLV75)
    sensitivity.py                          matriz dV/dP por perturbacao, em
                                            lugar do Jacobiano do pandapower
    data/MVLV75/                            circuito gerado
  pade-opentes/agents/market_agents.py      os 4 agentes FIPA + solver
  pade-opentes/agents/network_link.py       camada de rede (sucessor do
                                            pade.simul do ns-3)
  mosaik-opentes/scenarios/market.py        cenario da co-simulacao
  docs/MERCADO.md                           formulacao e desvios
```

```text
Alterados:
  grid-opentes/src/simulators/api_opendss.py
    - o modelo Load passa a aceitar P_kw/Q_kvar como ENTRADA. Antes a carga so
      obedecia a LoadShape interna do circuito e nenhum agente conseguia
      injetar demanda na rede.
    - get_data de Load corrigido para carga trifasica: get_power devolve tupla
      por fase, e o codigo dividia a tupla por 1000. O IEEE 13 nunca exercitou
      esse caminho porque suas cargas sao monofasicas.
  pade-opentes/Dockerfile
    - numpy, pandas e pyomo na imagem. O CPLEX NAO entra: licenca academica e
      pessoal, montado do host por volume (${CPLEX_HOME} -> /opt/cplex).
  docker-compose.yaml
    - servicos pade-market e mosaik-market, no profile 'market'.
```

```text
Regressao: os cenarios star, ieee13 e integrated continuam funcionando. O
ieee13 reproduz os mesmos P_dc/P_ac/P_meas de referencia do TSRE.
```


### 11. Mercado: fase de operação, rede 6TiSCH e reativo

Continuação do item 10, com as quatro frentes que fecharam a camada de mercado.
Cada uma trouxe uma correção de fundo, e não só código novo.

**Fase de operação dentro dos agentes.** A correção a cada 15 minutos passou a
rodar nos próprios agentes, acionada pelo passo do Mosaik. O ponto de operação
era estimado extrapolando a programação pela matriz de sensibilidade, o que
desviava até 7,2e-3 pu do fluxo real; agora o `SolverAgent` **resolve o fluxo de
potência**, como a tese faz.

```text
market_agents.py    start_operation, _op_cycle2, _op_cycle3 e os dois niveis
                    de intervencao (armazenamento de rede, depois leilao)
```

Os 96 pontos de operação são resolvidos **uma vez, no arranque e na thread
principal**: o `py-dss-interface` não é seguro para uso concorrente e derrubava o
processo com `std::bad_alloc` quando chamado do pool de threads do Twisted.

**Rede LPWA 6TiSCH.** A rede de comunicação da tese foi reconstruída no OMNeT++,
com erro de pacote por distância (Pister-Hack), roteamento multi-salto e atraso
vindo do slotframe do TSCH.

```text
comm-opentes/Tisch.cc, Tisch.ned    servidor de rotas, configuracao `-c tisch`
comm-opentes/nodes_xy.csv           coordenadas dos 77 agentes (Apendice B)
comm-opentes/adjacency.txt          matriz de adjacencia (Apendice C)
pade-opentes/agents/network_link.py backend `omnet`, cliente ZMQ
```

Serve rotas em vez de participar do passo do Mosaik porque a negociação inteira
acontece dentro de um passo, com o relógio da co-simulação parado. A adjacência é
**lida do arquivo**, e não regenerada: regenerar exige supor o orçamento de
enlace do rádio, e a suposição natural produzia uma rede duas vezes e meia mais
densa que a publicada.

**Sensibilidade ao reativo.** O `sensitivity.py` passou a calcular também
`dV/dQ`. A hipótese `dQ = 0` da formulação vale enquanto o dispositivo não mexer
em reativo; com fator de potência constante, ignorá-la leva de 5 para 117 pontos
de tensão violados.

**Alinhamento com a tese.** Quatro ajustes vindos da revisão de cobertura do
capítulo 6:

```text
operation.py         demanda realizada por perturbacao de +/-10% (mecanismo da
                     tese) em vez de um dia alternativo do reservatorio
market_agents.py     o ciclo 2 passou a existir COMO TRAFEGO: antes o agente de
                     mercado lia a programacao direto da memoria do concentrador
market_agents.py     retransmissao no ciclo 2, e MAX_RETRIES de 3 para 10
optimization.py      MARKET_TRAFO_KVA, para reproduzir os 250 kVA uniformes
market_opentes/loading.py    verificacao de carregamento termico dos condutores
```

**Chaves de configuração acrescentadas** no `docker-compose.yaml`, todas com
padrão que reproduz o comportamento da tese:

```text
MARKET_V_BACKOFF       margem na restricao de tensao (2e-3)
MARKET_MAX_ROUNDS      teto de rodadas (60); acompanha o backoff
MARKET_REALIZED_MODE   `perturb` (tese) ou `day` (caso severo)
MARKET_STORAGE_PF      fator de potencia do armazenamento; `none` = tese
MARKET_IGNORE_DQ       chave de EXPERIMENTO, nao de operacao
NET_BACKEND            ideal, lossy ou omnet
NET_MESSAGE_SIZE       `real` ou `thesis`
```

Regressão: `star`, `ieee13` e `integrated` continuam funcionando.

### 12. Redes de teste próprias: BT16 e BT38

**Por que existem.** A rede da tese não exibe sobretensão. Os alimentadores têm
de 60 a 180 m com cabo de 15 mm², e o fotovoltaico instalado é 0,37 do carregado:
ao meio-dia há exportação líquida, mas espalhada por cinco alimentadores curtos,
o que dá cerca de 0,006 pu de elevação. A restrição superior nunca fica ativa, e
metade do mecanismo de mercado fica sem ser exercitada. Estudar o preço nos dois
extremos da faixa exige uma rede em que os dois extremos ocorram.

`src/simulators/gen_test_grid.py` projeta a rede a partir de parâmetros e emite
tudo o que a camada de mercado consome, para que a rede seja autocontida:

```text
<REDE>/Master.dss + _LineCodes/_Lines/_Transformers/_Loads.dss   circuito
<REDE>/force.json            topologia, no formato que config.load_case lê
<REDE>/config.json           alocação de dispositivos por barra
<REDE>/load_kw.csv, pv_kw.csv, spot_price.csv, scenario_pool.npz   perfis
```

As FORMAS das curvas vêm do SimBench, reaproveitadas dos perfis já no projeto e
normalizadas pelo próprio máximo; o DIMENSIONAMENTO por barra é deste trabalho.
Condutor: cabo multiplexado de alumínio, 70 mm² no tronco e 35 mm² no ramal, com
valores de tabela de concessionária. Transformadores pela NBR 5440.

**Os alimentadores são ramificados, e não cadeias.** Cada um é uma árvore: um
tronco em 70 mm² saindo do transformador e ramais em 35 mm² pendurados nele, com
sub-ramais onde a rede é mais densa. A primeira versão deste gerador produzia uma
cadeia única, e isso não é só um desenho pobre. Numa cadeia, a impedância até a
barra k é a soma de k vãos iguais e a tensão cai de forma monótona; numa árvore,
duas barras à mesma distância elétrica ficam em ramos distintos e só sentem a
injeção uma da outra pelo trecho comum do caminho. É o que dá sentido a `∂V/∂P`
ser uma MATRIZ cheia, e não uma diagonal dominante, e portanto ao preço ter de
ser resolvido por barra. O nível de ramificação de cada trecho vai gravado no
`force.json`, porque é ele que decide o calibre do cabo.

A geração vai nas barras mais distantes do transformador, medidas pelo
comprimento do CAMINHO. Numa árvore isso deixa de coincidir com a ordem de
criação das barras, e é a distância que importa: quanto maior a impedância
acumulada, maior a elevação que a mesma injeção provoca.

**BT16, rede de bancada.** Dois alimentadores iguais, tronco de 4 barras com três
ramais, 8 barras de carga e 480 m de rede secundária cada, em 45 kVA. Serve para
iterar sobre o mecanismo: cada rodada da decomposição leva 0,3 s, contra 2,3 s na
MVLV75. Cada barra representa um AGRUPAMENTO de unidades consumidoras, e não uma
casa, que é como a rede secundária costuma ser modelada. A sobretensão e a
subtensão ocorrem no MESMO alimentador, em horários diferentes.

**BT38, rede final.** Quatro transformadores num tronco de média tensão, com
caráter distinto entre eles:

```text
                     kVA  tronco/ramais  rede    PV/carga  papel
T1 urbano denso       75      3 + 3       270 m    0,12    carga alta, nao exporta
T2 suburbano          45      5 + 4       495 m    0,44    o alimentador neutro
T3 condominio solar   45      6 + 5       660 m    0,72    a sobretensao
T4 ponta rural        30      8 + 4       900 m    0,24    a subtensao
```

A penetração DESIGUAL entre alimentadores é o ponto do projeto. No fluxo do dia
sem armazenamento, a sobretensão fica no condomínio solar T3, das 08:45 às 10:45
e das 11:45 às 13:30; a subtensão fica na ponta rural T4, das 10:45 às 11:45 e
das 14:45 às 22:15, e à noite em T2 e T3. Os dois extremos ocorrem em
alimentadores diferentes e em horários diferentes; nenhum intervalo tem os dois ao
mesmo tempo. O preço sombra ainda assume os dois sinais no mesmo intervalo, em 52
de 96 na decomposição centralizada, porque o armazenamento acopla os intervalos
entre si: às 09:45, T3 recebe -8,51 e T4 +0,18. A razão global de PV sobre carga
fica em 0,39 no pico e 0,41 em energia, na faixa da rede da tese (0,37). O que
produz a sobretensão não é a razão global, é como ela se distribui, e a coluna
PV/carga acima mostra a diferença. T3 gera em TODAS as onze barras, e
as mais distantes ficam a 420 m do transformador pelo caminho, que é onde a mesma
injeção provoca a maior elevação. A tese tem 0,37 espalhado por igual, e por isso
não vê sobretensão nenhuma.

Medido em duas condições. Primeiro na decomposição dual centralizada
(`market_opentes.dual`), sobre o modelo linearizado e a demanda prevista:

```text
rede    V base            violacoes base   V negociado       rodadas   s/rodada
BT16    0,9538 a 1,0489   (57, 87)         0,9710 a 1,0290      39       0,3
BT38    0,9391 a 1,0527   (414, 124)       0,9710 a 1,0290      42       1,1
```

Depois na co-simulação completa (`./run.sh market`), com os agentes reais, o
fluxo de potência não linear do OpenDSS e a demanda REALIZADA, que difere da
programada. As contagens são de pares (barra, intervalo):

```text
rede    barras BT  pontos   V baseline        viol.      V negociado       viol.
BT16       18       1.728   0,9359 a 1,0562   (37, 137)  0,9708 a 1,0290   (0, 0)
BT38       42       4.032   0,9216 a 1,0649   (406, 128) 0,9697 a 1,0290   (1, 0)
```

Na BT16 os dois tipos de violação vão a zero no fluxo completo. Na BT38 a
sobretensão vai a zero e sobra 1 par de subtensão: n46, o fim do alimentador
rural, às 19:30, a 0,96970 pu. A fase de operação atuou nessa janela e previu
0,97100 depois da correção, mas avalia a tensão pelo mesmo modelo linear da
negociação (`voltage_at`). O erro de linearização, que ali chega a 1,3 mpu, fica
invisível para ela.

Por alimentador, na BT38, a sobretensão de T3 e a subtensão de T4 são corrigidas
na mesma execução, em horários diferentes:

```text
alimentador   caso        V min    V max    <0,97   >1,03
T1 urbano     baseline    0,9655   1,0012       4       0
              negociado   0,9710   1,0010       0       0
T2 suburbano  baseline    0,9375   1,0312      38       2
              negociado   0,9707   1,0290       0       0
T3 solar      baseline    0,9438   1,0649     132     126
              negociado   0,9701   1,0290       0       0
T4 rural      baseline    0,9216   1,0157     232       0
              negociado   0,9697   1,0100       1       0
```

A negociação da co-simulação convergiu em 32 rodadas na BT38, contra 29 na BT16.

Na decomposição centralizada a BT38 converge em 42 rodadas, contra 39 da BT16,
com o mesmo critério |Δλ| ≤ 1e-4. Conferida no fluxo não linear, com a demanda
programada, a programação negociada da BT38 deixa 3 leituras por fase abaixo de
0,97 em 13.248, e nenhuma acima de 1,03.

**Como rodar.** A rede vem de `MARKET_NETWORK`, resolvida pelo `run.sh`:

```bash
MARKET_NETWORK=BT38 ./run.sh market
```

Diferença entre os casos: a MVLV75 guarda `config.json` e perfis no pacote do
mercado, e as redes geradas guardam tudo ao lado do circuito. O `run.sh` aponta
`MARKET_CONFIG` e `MARKET_DATA_DIR` conforme a escolha, e gera a sensibilidade
`dV/dP` e `dV/dQ` da rede na primeira execução. Os resultados vão para
`output/market_<REDE>/`, para não sobrescreverem os da rede da tese.

**Diagrama.** `src/simulators/plot_grid.py` desenha o unifilar a partir do
`force.json` e do `config.json`, com a mesma convenção da figura de referência:
azul para o armazenamento do prosumidor, vermelho para o da rede. É gerado por
código, e não à mão, para acompanhar a rede quando ela for redimensionada.

```bash
python src/simulators/plot_grid.py src/data/BT38     # -> src/data/BT38/diagrama.png
```



## Ambiente Python

Na raiz do repositório:

```bash
uv sync
```

Validação básica:

```bash
uv run python -c "import pade, mosaik, mosaik_api, mosaik_api_v3, zmq, py_dss_interface; print('ok')"
```

O OMNeT++ não é instalado no ambiente Python local; ele é tratado pelo
container do TSCC.

## Docker

Build (uma vez): `docker compose build`. A execução recomendada é pelo
`run.sh` (faz limpeza completa e espera os simuladores ficarem prontos):

```bash
./run.sh integrated   # co-simulação completa (baseline + Volt/Var)
./run.sh market       # mercado transativo (exige CPLEX no host)
./run.sh ieee13       # rede elétrica isolada (validação)
./run.sh star         # comunicação isolada
```

O cenário `market` exige o **CPLEX**, montado do host por volume via
`${CPLEX_HOME}`. A licença é acadêmica e pessoal, então ele não entra na imagem
nem no repositório.

Artefatos como `results.csv`, `grafico_trafego.png`, `sim_exec`, `out/` e
saídas do OpenDSS são produtos de simulação e estão no `.gitignore`.

## Resultados

### Co-simulação integrada (cenário `integrated`, IEEE 13 Barras)

A co-simulação completa (`./run.sh integrated`) fecha o laço causal
sobre o IEEE 13 Barras, sem bateria. Reproduz o estado do trabalho do TSRE
(Paulo Victor) — os **5 inversores fotovoltaicos injetando** — porém agora
**co-simulados e controlados**: cada inversor tem seu par de agentes PADE
(medidor + controlador) e a tensão da sua barra trafega pela rede OMNeT++:

```
OpenDSS Bus_i.V → AgenteA_i (mede) → OMNeT++ (atraso/jitter/perda) → AgenteB_i (Volt/Var)
                                                                          │ P=solar, Q=f(V)
OpenDSS ← PVSystem PV_i (P_des, Q_des) ←──────────────────────────────────┘   (i = 1..5)
```

- **P (ativa)** = potência solar disponível (cadeia irradiância → PV panel).
- **Q (reativa)** = função da tensão recebida **pela rede de comunicação**,
  respeitando `S = √(P² + Q²) ≤ kVA` do inversor.
- Ganho do Volt/Var **suave** (`Q_MAX_PCT = 0,05`, faixa morta `±0,02`): com 5
  inversores + atraso/perda da rede, ganho alto **desestabiliza** (ver observações).

O experimento roda **duas vezes** e compara — sem controle (baseline) e com
controle (Volt/Var). A perda de pacotes é **parâmetro de modelo da rede**
(`drop_probability = 0,15` herdado do TSCC), com **semente fixa** para
reprodutibilidade.

**Telemetria da rede de comunicação (OMNeT++):**

| Métrica | Valor |
|---|---|
| Pacotes enviados | 730 (5 medidores × 1 dia) |
| Pacotes perdidos | 136 (**18,6%**) |
| Latência | 32–451 ms (média 81 ms) |
| Jitter | média 53 ms |

**Efeito do controle Volt/Var nas 5 barras dos PVs (desvio-padrão e mínimo da tensão p.u.):**

| Barra (PV) | Desvio base → Volt/Var | Mínima base → Volt/Var |
|---|---:|---:|
| 652 (PV5) | 0,0338 → **0,0273 (−19%)** | 0,9205 → **0,9382** |
| 634 (PV3) | 0,0245 → **0,0210 (−14%)** | 0,9450 → **0,9557** |
| 632 (PV2) | 0,0121 → **0,0107 (−12%)** | 0,9673 → 0,9714 |
| 645 (PV4) | 0,0247 → 0,0242 (−2%) | 0,9665 → 0,9680 |
| 646 (PV1) | 0,0290 → 0,0285 (−1%) | 0,9648 → 0,9662 |
| **Média** | 0,0248 → **0,0224 (−10%)** | — |

Reativo total dos 5 inversores: médio 84 kvar, máximo 320 kvar. Geração FV
agregada (Σ P_meas): pico ≈ 4,5 MW.

### Observações — baseline × Volt/Var

- **Suporte de tensão (o ganho principal).** A rede tende à **subtensão** (várias
  barras abaixo de 0,95 pu no baseline). O Volt/Var **injeta reativo e eleva as
  barras mais críticas**: a mínima do Bus 652 sobe de 0,920 → 0,938 pu e a do
  Bus 634 de 0,945 → 0,956 pu. O desvio-padrão da tensão cai em média 10% (até
  19% na barra mais afetada), **sem introduzir sobretensão** (máximos preservados).
- **Estabilidade exige controle suave.** Com ganho agressivo (`Q_MAX_PCT = 0,44`,
  padrão do IEEE 1547) os **5 inversores simultâneos + atraso/perda da rede**
  sobre-injetam reativo e **desestabilizam** (tensão chegou a 1,12 pu, reativo a
  ~5,7 Mvar). Reduzindo o ganho para 5% o sistema regula de forma estável. **Esse
  é um achado central do benchmark:** a qualidade da comunicação limita a
  agressividade segura do controle distribuído.
- **A perda de pacotes é um parâmetro do modelo, não um resultado.** O
  `drop_probability` representa a confiabilidade do canal real e deve ser
  **calibrado com a aplicação**. Aqui usamos o valor do TSCC (15%, ~18,6% medido)
  com semente fixa. Mesmo assim, a ordem assíncrona das mensagens faz os valores
  exatos variarem um pouco entre execuções — o efeito qualitativo se mantém.
- **STATCOM à noite.** Com a solar nula (P = 0), toda a capacidade do inversor
  vira reativa; o PV opera como compensador e continua dando suporte de tensão.

### A perda de pacotes é parâmetro, não resultado

O `drop_probability = 0,15` (modelo do TSCC) é **fenomenológico**: a cada pacote
sorteia-se a perda com 15% de chance. Isso reproduz o *efeito estatístico* da
perda, mas **não modela a causa** — na realidade um pacote se perde por
congestionamento, colisão, ruído, timeout ou enlace saturado. Ou seja, a perda
real **emerge** das condições da rede; ela é uma **saída**, não uma entrada.

Nesta rede curta do IEEE 13, com pouquíssimas mensagens, a perda física real
seria ~0%; os 15% aqui funcionam como **teste de estresse / análise de
sensibilidade** (varrer 0%, 5%, 15%… e medir o impacto no controle).

Quando o projeto for para ambientes pesados (**transações econômicas**, muitos
agentes, mercados P2P), o caminho é migrar do modelo fenomenológico para o
**mecanístico** — o OMNeT++ tem o framework **INET**, que modela TCP/IP,
enlaces, filas e protocolos. Aí o **próprio tráfego** da co-simulação gera
congestionamento e a **perda/latência emerge** dele: a pergunta deixa de ser
"qual probabilidade eu ponho?" e passa a ser "esta rede aguenta o volume de
mensagens do mercado sem degradar o controle?". A telemetria atual
(`packets_*`, `latencies_out`, `jitters_out`) já registra essas grandezas; o
passo seguinte é **correlacionar** o evento de rede com o efeito na aplicação
(um lance perdido causou descasamento no mercado? um setpoint atrasado causou
violação de tensão?).

**O que cada arquivo de `output/integrated/` apresenta** (detalhado em
[`RESULTADOS.md`](RESULTADOS.md)):

| Arquivo | O que contém | Para quê |
|---|---|---|
| `result_baseline.csv` | Trajetórias elétricas **sem** controle: tensão das fases de **todas as barras**, `P_ref` (=solar) e `Q_ref` (=0) dos 5 controladores, `P_meas`/`Q_meas` dos 5 PVs e `P_dc` dos 5 painéis. | Linha de base (5 inversores só injetam a solar). |
| `result_volt_var.csv` | As mesmas grandezas **com** controle Volt/Var (agora `Q_ref` ≠ 0). | Caso controlado. |
| `comm_trace_baseline.csv` | Rastro da **rede de comunicação** na execução baseline: a mensagem FIPA com a tensão (`val_out`) e a telemetria do OMNeT++ (`packets_sent/received/dropped`, `latencies_out`, `jitters_out`, `packet_sizes_out`). | Comprova que a tensão trafegou pela rede e mede o atraso. |
| `comm_trace_volt_var.csv` | Idem para a execução com Volt/Var. | Mesma telemetria, caso controlado. |
| `dashboard_integrated.png` | Painel visual de 8 quadros, unindo os dois domínios: (1) irradiância solar 5 PVs, (2) temperatura dos módulos, (3) geração FV agregada, (4) tensões p.u. nas 13 barras, (5) integridade de pacotes (pizza entregues×dropados), (6) latência exata, (7) jitter distribuído, (8) efeito do Volt/Var nas 5 barras PV. | Resumo da co-simulação para apresentação. |
| `comparacao_volt_var.png` | Figura dedicada do controle **atuando × não atuando**: tensão de cada barra PV (baseline vs Volt/Var), σ e mínima por barra, e o ganho resumido em p.u. | Mostrar com clareza o efeito do controle. |
| `analise_comunicacao.png` | Caracterização da rede: histogramas de **latência** e **jitter**, **integridade** dos pacotes (pizza) e pacotes **acumulados** (enviados/entregues/dropados). | Descrever a qualidade do canal. |

Cada linha dos `result_*.csv` é um passo de 5 min (288 = 1 dia); cada linha dos
`comm_trace_*.csv` é a telemetria daquele passo. As colunas `Bus-<nó>-V*_pu` são
as tensões por fase (as fases inexistentes de trechos monofásicos ficam ~0 e são
ignoradas no cálculo).

Gere o painel após rodar o cenário:

```bash
docker compose run --rm --no-deps -e MOSAIK_OUTPUT_DIR=/app/output/integrated \
  mosaik python plot_integrated.py     # -> output/integrated/dashboard_integrated.png
docker compose run --rm --no-deps -e MOSAIK_OUTPUT_DIR=/app/output/integrated \
  mosaik python plot_comparacao.py     # -> comparacao_volt_var.png + analise_comunicacao.png
```

### Validação do bloco elétrico (cenário `ieee13`, isolado)

O cenário elétrico puro (`./run.sh ieee13`, IEEE 13 + 5 PVs) reproduz
**exatamente** os valores do trabalho do TSRE (Paulo Victor, branch
`paulo-victor`), confirmando que a integração não alterou a física:

| Grandeza (máximo no dia) | Nosso | Referência TSRE |
|---|---:|---:|
| P_dc (painel) | 3024,6 kW | 3024,6 kW |
| P_ac (inversor) | 2854,2 kW | 2854,2 kW |
| P_meas (injeção OpenDSS) | 1902,7 kW | 1902,7 kW |

Tensões do IEEE 13 coerentes: barra 650 (fonte) = 1,000 pu; barras trifásicas
0,91–1,05 pu; fases de trechos monofásicos (ex.: 611 A/B) em 0,0 (corretas).

### Como reproduzir

```bash
./run.sh integrated   # roda baseline + Volt/Var; saídas em output/integrated/
./run.sh ieee13       # bloco elétrico isolado (validação vs Paulo Victor)
```

Para estudar o impacto da **perda de pacotes** no controle, aumente
`**.node_0.drop_probability` no `simulators/comm-opentes/omnetpp.ini`
(ex.: `0.15` = 15%) e compare as tensões resultantes.
