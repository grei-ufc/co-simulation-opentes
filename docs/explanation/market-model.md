# O modelo de mercado

Esta página responde três perguntas sem que seja preciso ler o código: **qual é
o modelo matemático, onde ele está implementado e em que ele difere da
formulação de origem.** Os resultados ficam em [Resultados](../results.md).

## De onde vem a formulação

O mecanismo é o da tese de doutorado de Lucas Silveira Melo (*Modelo de
simulação computacional multidomínio para análise de redes elétricas
inteligentes com aplicação em transações econômicas de energia*, UFC, 2022,
capítulo 6), que por sua vez adapta o controle transativo com restrições de
rede de Hu et al. (2017). A tese o aplica à MVLV75, uma rede de média e baixa
tensão sintética em que **todas as barras são trifásicas e equilibradas**: lá,
uma tensão e um preço sombra por barra bastam.

Este trabalho parte dessa formulação e a leva à IEEE 13 barras, que tem barras
mono, bi e trifásicas e é **desequilibrada** de propósito. A MVLV75 é a
inspiração e a base de comparação da formulação; nenhum resultado dela é usado
aqui. A mudança central é que a análise passa a ser **por fase**: o operador vigia
a tensão de cada fase, e o preço sombra é calculado por fase.

## Os papéis

| Sigla | Papel | Na IEEE 13 | Onde está |
|---|---|---:|---|
| AP | Agente Prosumidor: programa o próprio armazenamento e compra energia | 10 | `market_agents.ProsumerAgent` |
| AC | Agente Concentrador: agrega os prosumidores e aciona os dispositivos sob ele | 1 | `market_agents.ConcentratorAgent` |
| AD | Agente DSO: detém o modelo da rede e as restrições operacionais | 1 | `market_agents.DSOAgent` |
| AM | Agente Mercado: coordena a descoberta do preço sombra | 1 | `market_agents.MarketAgent` |
| | Solver: resolve os modelos fora do reactor do Twisted | 1 | `market_agents.SolverAgent` |

A tese põe um concentrador por transformador de distribuição. A IEEE 13 tem um
transformador só, então há um concentrador, que representa a cabeceira do
alimentador. Os modelos de otimização ficam em
`simulators/market-opentes/market_opentes/optimization.py`; os agentes, em
`simulators/pade-opentes/agents/market_agents.py`.

## Os modelos de otimização

### Agente Prosumidor (Eq. 6.1 a 6.9)

Minimiza o custo operacional esperado em dois estágios: no primeiro, quanto
contratar no mercado bilateral de preço fixo e como programar o armazenamento; no
segundo, os lances no mercado de tempo real, por cenário.

```
min  Σ_t Φ_bl · APP_bl(t) · Δt  +  Σ_z Σ_t π(z) · Φ_tr(z,t) · APP_tr(z,t) · Δt
```

Sujeito ao balanço energético, à impossibilidade de vender o que foi comprado no
bilateral e à operação do armazenamento (exclusão entre carga e descarga,
limites de potência e memória do estado de carga). O modelo do prosumidor é
**econômico e não enxerga fase**: a proposta dele é uma série por dispositivo.

### Agente Concentrador (Eq. 6.25 e 6.26)

```
min  Σ_t Σ_l C_k · (ACP_init(t,l) − ACP_result(t,l))²  +  Σ_t Σ_l λ(t,l) · ACP_result(t,l)
sujeito a   Σ_t ACP_result(t,l) · Δt  ≥  D · Σ_t ACP_init(t,l) · Δt
```

### Agente DSO (Eq. 6.27 a 6.29)

```
min  Σ_t Σ_l [ a · (ADP_init − ADP_result)² + b · (ADP̄_init − ADP̄_result)² ]  −  Σ_t Σ_l λ(t,l) · ADP_result(t,l)
sujeito a   Σ_l (ADP_result + ADP̄_result)  ≤  ADP_trans_max(t)
            U_min  ≤  U_0(t,r) + ΔU(t,r)  ≤  U_max          para cada linha r
```

O sinal de λ é positivo no concentrador e negativo no DSO. Isso é da formulação.

### Decomposição dual (Eq. 6.24 e 6.30)

A restrição de acoplamento `ACP_result = ADP_result` é relaxada por multiplicador
de Lagrange, e o agente de mercado atualiza o preço sombra por subgradiente:

```
λ(t,l) ← λ(t,l) + α · ( ACP_result(t,l) − ADP_result(t,l) )
```

até o critério de parada.

**O critério de parada é relativo ao tamanho dos dispositivos.** A negociação
termina quando, em toda variável de armazenamento e em todo intervalo, o
desacordo entre concentrador e DSO fica abaixo de uma fração da potência máxima
do próprio dispositivo (por porta, Pmax/|F|):

```
max |ACP_result − ADP_result| / Pmax  ≤  ε_rel        (MARKET_EPS_REL = 1e-3)
```

O critério da tese, `|Δλ| ≤ ε`, continua disponível com `MARKET_CRITERIO=absoluto`.
Como `Δλ = α · (ACP − ADP)`, ele limita o desacordo a ε/α kW, o mesmo valor
absoluto para uma bateria de 2 kW ou de 800 kW. Com α = 0,6 e ε = 10⁻³, são
1,7 W: cerca de 0,1% da potência na rede da tese, de bancos de 2 kW, e 0,001% ou
menos na IEEE 13, de bancos de 150 a 800 kW, um rigor que não muda a solução e
custa rodadas.
Com ε_rel = 10⁻³, o rigor da IEEE 13 passa a ser o mesmo que o ε absoluto dava
na rede da tese, e as rodadas caem de 82 para 48 por barra, de 66 para 42 por
fase e de 108 para 63 com o inversor de três fios, sem mudar nenhuma contagem
de tensão no fluxo não linear.

### A restrição de tensão (Eq. 6.15 a 6.17)

A tensão é linearizada em torno do ponto de operação da previsão:
`ΔU = −S · (p + q)`, com `S = ∂V/∂P`. A tese obtinha `S` do Jacobiano do
pandapower; aqui ela é medida por perturbação no próprio OpenDSS
(`grid-opentes/src/simulators/sensitivity.py`), o que dispensa um segundo
simulador e vale para rede desequilibrada.

## A análise por fase

### Por que a média não serve

Na IEEE 13 o modelo por barra precisa resumir as fases numa só tensão, e a
escolha natural é a média. A média esconde violação: a negociação feita sobre ela
deixa a média dentro da faixa e a fase B acima de 1,03 pu (ver
[Resultados](../results.md)).

A causa é física. Injetar 1 kW só na fase A da barra 671 sobe a fase A em 51 µpu,
**baixa a fase B em 71 µpu** e sobe a C em 39 (média do dia). O efeito sobre a
fase vizinha é do mesmo tamanho do efeito próprio, e metade dos termos cruzados
é negativa: a impedância mútua da linha tem ângulo de cerca de 73°, e projetada
na direção da tensão da fase B, que está a −120°, fica quase oposta a ela. Uma
injeção equilibrada na 671 move a fase B em 4,4 µpu/kW, enquanto o modelo da
média enxerga 9,2. O DSO superestimava em duas a três vezes a eficácia do
armazenamento justamente na fase que viola.

### A formulação

O índice l das Eq. 6.18 a 6.30 passa a ser o par (barra, fase). É a adaptação que
o próprio artigo-base indica para rede desequilibrada: introduzir o preço sombra
em cada fase (Hu et al., 2017, seção V).

| | por barra (`MARKET_FASE=0`) | por fase (padrão) |
|---|---|---|
| linha da restrição de tensão | barra (média das fases) | (barra, fase): 32 na IEEE 13 |
| variável e preço sombra | um por barra | um por porta (barra, fase): 22 |
| matriz de sensibilidade | `sensitivity_day.npz` | `sensitivity_fase.npz` |

Uma **porta** é cada fase em que o dispositivo de uma barra pode injetar: as
fases em que a carga daquela barra está ligada, cada uma como carga monofásica
fase-neutro `Port_<barra>_<fase>` no circuito. Quatro regras completam o modelo:

1. **Cada porta tem limite Pmax/|F|**, sendo |F| o número de fases do
   dispositivo, e o dispositivo tem **um estado de carga só**, a soma das portas.
2. **A proposta do prosumidor continua escalar.** O concentrador a reparte
   igualmente entre as portas do dispositivo e redistribui a partir daí, que é o
   papel que a tese lhe dá: agregar os prosumidores e acionar os dispositivos
   sob ele.
3. **Os pesos Ck, a e b são multiplicados por |F|.** Sem isso a penalidade de
   desviar o dispositivo inteiro cairia para Ck/|F|.
4. **O passo α é multiplicado por |F| em cada porta**, porque o resíduo de cada
   porta é 1/|F| do resíduo do dispositivo.

Com as regras 3 e 4, numa rede equilibrada a formulação por fase reproduz a por
barra rodada a rodada, com λ igual nas três fases e igual ao λ da barra
(verificado numa rede de teste equilibrada: mesmo número de rodadas e mesma
trajetória de λ, desde que as duas usem a mesma matriz). A formulação por barra
da referência é, portanto, um caso particular desta.

### O inversor: quatro fios ou três fios

`MARKET_DISPOSITIVO` diz como o armazenamento injeta nas fases, e corresponde aos
dois tipos de inversor de baterias:

| | `independente` (padrão) | `equilibrado` |
|---|---|---|
| inversor | trifásico a **quatro fios**, com controle por fase | trifásico a **três fios**, equilibrado |
| correntes | I_A ≠ I_B ≠ I_C, cada fase despachada separadamente | iguais nas três fases |
| variável e preço sombra | por porta (barra, fase) | por barra |
| o DSO vigia | cada fase | cada fase |

**O que o modo `independente` representa.** Cada porta é um elemento
fase-neutro, então a corrente de cada fase é independente e volta pelo neutro,
que existe em todos os trechos da IEEE 13 (alimentador a quatro fios,
multiaterrado). O estado de carga compartilhado é o barramento CC comum, por onde
um inversor de quatro braços transfere potência de uma fase para outra: absorver
na fase B e injetar na A para baixar a B é uma decisão que o modelo toma, e que
um inversor equilibrado não consegue tomar. O limite Pmax/|F| por fase é o teto
por fase que os equipamentos comerciais desse tipo declaram.

**O que ele não representa.** Só potência ativa por fase: o reativo segue a
hipótese ΔQ = 0 da tese. Não há perdas de conversão, dinâmica de controle do
inversor nem limite de corrente de neutro além do que o próprio fluxo de
potência do OpenDSS impõe. São simplificações de modelo quase estático, com
passo de 15 minutos, e não ausências da topologia.

**O modo `equilibrado`** reparte a potência do dispositivo igualmente entre as
portas, e a coluna da matriz é a média das colunas das fases. Ele aproxima o
inversor de três fios por injeção igual em estrela; um inversor de três fios real
não tem caminho de sequência zero, o que difere disso apenas quando as tensões
das fases estão desequilibradas. Nas barras mono e bifásicas (611, 645, 652, 646
e 692) um inversor trifásico não se liga, e os dois modos coincidem.

### Custo de comunicação

O CFP de cada rodada carrega λ por porta: na IEEE 13, 22 séries em vez de 10. O
CFP ao DSO passa de 10,9 para 24,2 kB por rodada, e a resposta do concentrador de
11,2 para 24,4 kB.

Na rede 6TiSCH isso pesa: as mensagens dos ciclos 2 e 3 têm de 20 a 34 kB, e o
ciclo 3 gasta de 474 a 541 s de rede por rodada, acima do orçamento de 300 s em
todas elas (ver [Resultados](../results.md#sobre-a-rede-6tisch)). Para caber, a
mensagem precisa ser comprimida, ou só a parte que mudou ser enviada.

## O regulador de tensão

O circuito tem um banco de três reguladores monofásicos com derivações
independentes. O mercado decide com a tensão do **ponto de operação da
previsão**, que o regulador alcança ajustando as derivações; se o regulador
continuasse livre para reagir ao despacho do armazenamento, os dois controladores
disputariam a mesma variável, e parte da correção do mercado seria desfeita.

Por isso o sequenciamento é o da operação real: a matriz de sensibilidade é
calculada com o regulador livre no ponto da previsão, e as derivações resultantes
são gravadas com ela. Na co-simulação, o DSO aplica essas derivações a cada
passo, por uma entidade Mosaik `Regulador` ligada a cada regulador do OpenDSS
(`MARKET_REGULADOR=previsao`, o padrão). O regulador ajusta pela previsão; o
mercado decide depois, com a derivação como condição de contorno.

## A fase de operação

A programação do dia seguinte é calculada contra uma previsão. A cada 15 minutos,
com a demanda realizada (a previsão perturbada em até ±10%, o mecanismo da tese),
o DSO confere se o desvio viola alguma restrição. Primeiro tenta corrigir só com o
armazenamento de rede, que despacha diretamente; o leilão de tempo real, a mesma
decomposição dual sobre um período, liquida em toda janela. O ponto de operação
realizado é resolvido pelo OpenDSS, e não extrapolado pelo modelo linear.

## O despacho e a comunicação

Fechada a negociação, a programação precisa **chegar** a quem a executa. A cadeia
é a da tese, por FIPA-Subscribe: o DSO publica aos concentradores, cada
concentrador aciona o armazenamento de rede sob ele e repassa a parte de cada
prosumidor, e as confirmações sobem até o agente de mercado, que só então encerra
o passo do Mosaik.

Dois cuidados que só aparecem com entrega não instantânea, e que valem para
qualquer rede:

- O `FipaContractNetProtocol` do PADE supõe entrega imediata: com atraso, os
  contadores internos e o conjunto efetivamente recebido divergem. Os agentes
  fazem contabilidade própria, por remetente e por número de rodada.
- O FIPA não define retransmissão. Cada ciclo tem timeout com reenvio só aos
  faltantes, e uma política explícita para quem nunca responde: entra com
  programação nula.
- O PADE sobrescreve a mensagem guardada de todo comportamento a cada mensagem
  recebida e, 2 s depois da partida, manda todo iniciador enviar a mensagem
  guardada. Se a negociação começa antes disso, um iniciador reenvia a última
  mensagem recebida para si mesmo: o DSO respondia a um CFP falso, a proposta
  da rodada não chegava ao mercado e a rodada esperava o timeout inteiro, e as
  assinaturas do despacho nunca saíam. Os agentes do mercado lançam os
  comportamentos uma vez, antes de anunciar que estão prontos, e um iniciador
  não envia mensagem que veio de outro agente.

## λ não está em unidade monetária

No ótimo do concentrador, `2 Ck (x − x_init) + λ = 0`, então λ tem unidade de `Ck`
vezes potência. Com o `Ck = 1` adimensional da tese, λ é numericamente um desvio
de potência, e a tese o lê como **variável de controle**, não como preço. Para
virar preço, `Ck` precisa ser calibrado em moeda (`MARKET_CK_EUR`, em
EUR/(kW²·h)). Sem calibração, as colunas de preço do `dlmp.csv` saem com o sufixo
`_signal`.

## Desvios em relação à implementação original

| Original | Aqui | Motivo |
|---|---|---|
| PySP para o modelo estocástico | forma extensiva em Pyomo | PySP saiu do Pyomo 6; com 9 cenários não há o que decompor |
| parada pela variação absoluta de λ | desacordo relativo à potência do dispositivo | o mesmo rigor em dispositivos de qualquer porte |
| `J⁻¹₂₁` do pandapower | `∂V/∂P` por perturbação no OpenDSS | um simulador só, e vale para rede desequilibrada |
| uma tensão e um λ por barra | por (barra, fase) | a IEEE 13 é desequilibrada |
| restrição de corrente por matriz de incidência | carregamento do transformador | é a Eq. 6.13 e a que tem limite conhecido |
| conteúdo das mensagens em `pickle` | JSON | o tamanho serializado alimenta o modelo de rede |
| um simulador Mosaik por agente | um para todos | escala e menos sockets |
| sem retransmissão | timeout com reenvio aos faltantes | o FIPA supõe entrega |
| regulador livre durante o despacho | derivações da previsão | os dois controladores disputariam a tensão |
| estado de carga final livre | estado final ≥ inicial (`MARKET_TERMINAL_SOC`) | sem isso as baterias despejam a energia no último intervalo |
| limites de tensão exatos | recuo de 1 mpu (`MARKET_V_BACKOFF`) | o otimizador cola no limite e o erro da linearização vira violação |

## Limitações conhecidas

- **Erro de linearização.** O despacho por fase move potências grandes e
  desequilibradas, e o erro do modelo linear chega a 9 mpu no pior ponto, contra a
  margem de 1 mpu. É ele que deixa os poucos pontos abaixo de 0,97 pu que sobram
  no fluxo não linear. Relinearizar em torno do ponto negociado é a extensão
  natural.
- **Representação das fases do caso.** A conversão do IEEE 13 para o mercado usa
  uma carga por barra, equilibrada entre as fases dela, e liga o PV1 em triângulo
  B-C (fisicamente ele é estrela B e C). Com as cargas e os PV nas fases físicas o
  desequilíbrio é bem maior, e o armazenamento atual não basta: ver
  [O caso IEEE 13](ieee13-case.md).
- **O reativo é consequência, não decisão.** Com `MARKET_STORAGE_PF` o reativo
  acompanha o ativo pelo fator de potência; despachar reativo como serviço seria
  controle Volt/Var, fora do escopo desta camada.

## Referências

- MELO, L. S. *Modelo de simulação computacional multidomínio para análise de
  redes elétricas inteligentes com aplicação em transações econômicas de
  energia.* Tese (Doutorado), UFC, 2022.
- HU, J. et al. Application of network-constrained transactive control to
  electric vehicle charging for secure grid operation. *IEEE Transactions on
  Sustainable Energy*, v. 8, n. 2, p. 505-515, 2017.
- LIU, Y.; LI, J.; WU, L. Distribution system restructuring: distribution LMP
  via unbalanced ACOPF. *IEEE Transactions on Smart Grid*, v. 9, n. 5,
  p. 4038-4048, 2018.
- CHEN, J.; GUO, Y.; WU, W. Optimal dispatch scheme for DSO and prosumers by
  implementing three-phase distribution locational marginal prices. *IET
  Generation, Transmission & Distribution*, 2020.
