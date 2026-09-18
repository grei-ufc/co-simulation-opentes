# Mercado transativo: formulação, correspondência com a tese e desvios

Documento de referência da camada de mercado (`simulators/market-opentes`
e `pade-opentes/agents/market_agents.py`). Ele existe para responder três
perguntas sem que ninguém precise ler o código: **qual é o modelo matemático,
onde ele está implementado, e no que a nossa implementação difere da original.**

Fonte: MELO, Lucas Silveira. *Modelo de simulação computacional multidomínio
para análise de redes elétricas inteligentes com aplicação em transações
econômicas de energia*. Tese de doutorado, UFC, 2022. Capítulo 6.
Implementação de referência: repositório `market-simulation` (GREI-UFC).

---

## 1. Os quatro papéis

| Sigla | Papel | Quantidade | Onde está |
|---|---|---:|---|
| AP | Agente Prosumidor | 25 (os nós com armazenamento) | `market_agents.ProsumerAgent` |
| AC | Agente Concentrador | 5 (um por transformador) | `market_agents.ConcentratorAgent` |
| AD | Agente DSO | 1 | `market_agents.DSOAgent` |
| AM | Agente Mercado | 1 | `market_agents.MarketAgent` |
| — | Solver | 1 | `market_agents.SolverAgent` |

O AP programa os seus recursos e responde aos leilões. O AC agrega os
prosumidores de um transformador e despacha o armazenamento de rede sob ele. O
AD detém o modelo da rede e as restrições operacionais. O AM coordena a
descoberta do preço sombra. O solver existe para que os modelos Pyomo rodem fora
do reactor do Twisted, e é o mesmo papel do `solver_agent.py` original.

## 2. Modelos de otimização

### 2.1 Agente Prosumidor (Eq. 6.1 a 6.9)

Minimiza o custo operacional esperado, decidindo em dois estágios: no primeiro,
quanto contratar no mercado bilateral e como programar o armazenamento; no
segundo, os lances no mercado de tempo real, por cenário.

```
min  Σ_t Φ_bl · APP_bl(t) · Δt  +  Σ_z Σ_t π(z) · Φ_tr(z,t) · APP_tr(z,t) · Δt
```

Sujeito ao balanço energético (6.3), à impossibilidade de venda da energia
comprada no bilateral (6.4 e 6.5) e à operação do armazenamento (6.6 a 6.9):
exclusão entre carga e descarga por variáveis binárias, limites de potência e
memória do estado de carga.

Implementação: `market_opentes/optimization.py::solve_prosumer`.

### 2.2 Agente Concentrador (Eq. 6.25 e 6.26)

```
min  Σ_t Σ_l C_k · (ACP_init(t,l) − ACP_result(t,l))²  +  Σ_t Σ_l λ_ω(t,l) · ACP_result(t,l)
sujeito a   Σ_t ACP_result(t,l) · Δt  ≥  D_l · Σ_t ACP_init(t,l) · Δt
```

Implementação: `market_opentes/optimization.py::solve_concentrator`.

### 2.3 Agente DSO (Eq. 6.27 a 6.29)

```
min  Σ_t Σ_l [ a · (ADP_init − ADP_result)² + b · (ADP̄_init − ADP̄_result)² ]
     −  Σ_t Σ_l λ_ω(t,l) · ADP_result(t,l)
sujeito a   Σ_l (ADP_result + ADP̄_result)  ≤  ADP_trans_max(t)
            U_min  ≤  U_0(t,l) + ΔU(t,l)  ≤  U_max
```

Implementação: `market_opentes/optimization.py::solve_dso`.

**O sinal de λ é assimétrico de propósito**: positivo no concentrador (6.25),
negativo no DSO (6.27). Isso é da formulação, não erro de implementação, e o
código original faz o mesmo.

### 2.4 Sensibilidade de tensão (Eq. 6.15 a 6.17)

A restrição de tensão é linearizada em torno do ponto de operação, considerando
apenas potência ativa (ΔQ = 0; ver a seção 5.5 sobre quando essa hipótese vale):

```
ΔU(t,l) = J⁻¹₂₁ · ( ADP_result + ADP̄_result )
```

O trabalho original obtinha `J⁻¹₂₁` do pandapower, porque o MyGrid resolve o
fluxo por varredura direta-inversa e não produz Jacobiano. **Aqui a mesma
grandeza é obtida por perturbação no próprio OpenDSS**, o que elimina o segundo
simulador: `grid-opentes/src/simulators/sensitivity.py`.

Validação: a matriz numérica bate com `J⁻¹₂₁` do pandapower com erro relativo
mediano de 0,04% e máximo de 0,86%; a previsão de ΔV para uma mesma variação
difere em 1,9e-5 pu.

### 2.5 Decomposição dual (Eq. 6.24 e 6.30)

A restrição de acoplamento `ACP_result = ADP_result` é relaxada por multiplicador
de Lagrange, e o AM atualiza o preço sombra por subgradiente:

```
λ_ω+1(t,l) = λ_ω(t,l) + α_ω · ( ACP_result(t,l) − ADP_result(t,l) )
```

Critério de parada da tese: `|λ_ω − λ_ω+1| ≤ ε`. Ele é um resíduo primal
escalado pelo passo, e por isso o mesmo ε significa coisas diferentes sob passos
diferentes. Medido nas condições da tese com 9 cenários, ele dispara na rodada 9
com ε = 1e-1 e exige mais de 150 rodadas com ε = 1e-4, que é o valor do código
original; a tese reporta 8 rodadas, o que situa o ε efetivo dela na ordem de
1e-1, com resíduo primal ainda em 0,17 kW. Ele também **não é confiável sob passo
decrescente**:
medido, o passo decrescente declarou convergência em 45 rodadas com resíduo
primal de 0,0222 kW, cinco vezes pior que o passo constante em 60 rodadas
(0,0041 kW). O teste disparou pela queda do passo, não pelo acordo entre as
partes. Os dois resíduos são reportados lado a lado; compare pelo primal.

Implementação: `market_opentes/dual.py` (centralizada) e
`market_agents.MarketAgent` (distribuída, sobre FIPA).

## 3. Desvios em relação à implementação original

Cada item aqui é uma decisão consciente, não uma omissão.

| # | Original | Aqui | Motivo |
|---|---|---|---|
| 1 | PySP para o modelo estocástico | Forma extensiva em Pyomo | PySP foi removido do Pyomo 6. Com 9 cenários não há o que decompor: a forma extensiva é um único MIQP. O número de cenários virou parâmetro (1 = determinístico). |
| 2 | `J⁻¹₂₁` do pandapower | `∂V/∂P` por perturbação no OpenDSS | Elimina o segundo simulador de rede e vale para rede desbalanceada. |
| 3 | pandapower e MyGrid, dois modelos da mesma rede | Um modelo em OpenDSS | Ver seção 4. |
| 4 | Trafos de 250 kVA uniformes | 45/75/112,5 kVA do `force.json` | Os 250 kVA eram resíduo do std type `0.25 MVA 10/0.4 kV`. Com eles a restrição de carregamento nunca atua. |
| 5 | Restrição de corrente em todos os ramos por matriz de incidência | Carregamento por transformador | É a formulação da Eq. 6.13 e é a que tem limite conhecido. |
| 6 | Conteúdo das mensagens em `pickle` + `literal_eval` | JSON | O `pickle` sobre ACL é frágil, e o tamanho serializado alimenta o modelo de rede. |
| 7 | Um simulador Mosaik por agente (75 sockets) | Um simulador para todos | Escala e reduz o número de containers. |
| 8 | Sem retransmissão | Timeout com reenvio aos faltantes | Ver seção 5. |
| 9 | Direção da restrição de balanço decidida por `value()` sobre variáveis | Decidida pelo parâmetro de demanda líquida | O original lia o valor inicial de uma variável de decisão (zero na construção), o que na prática já era a demanda sem armazenamento. Agora é explícito. |
| 10 | Fase de operação com leilão em tempo real | Implementada em `operation.py`, fora do escopo principal | Escopo do TCC travado na fase de programação. |

## 4. A divergência entre os dois modelos de rede do trabalho original

O `market-simulation` descreve a mesma rede de duas formas incompatíveis:

| | pandapower (usado pelo AD) | MyGrid (usado pela co-simulação) |
|---|---|---|
| Transformador | 250 kVA, vk = 4%, vkr = 1,2% | 225 kVA, impedância 0,01 + 0,2j |
| Cargas | trifásicas equilibradas | monofásicas, na fase do campo `phase` |
| Linhas | std types do pandapower | modelo de condutor (Carson) |

Se a impedância do MyGrid for pu na base do trafo, o que não foi possível
confirmar porque o pacote `mygrid` não está no repositório, a reatância que os
agentes enxergavam é cerca de cinco vezes a do modelo com que o DSO calculava as
restrições. Unificar em OpenDSS resolve isso, e é uma das contribuições do
trabalho.

## 5. O que a camada de comunicação revelou

Dois problemas que só aparecem quando a entrega deixa de ser instantânea:

1. **O `FipaContractNetProtocol` do PADE supõe entrega imediata.** Os contadores
   internos (`received_qty` contra `cfp_qty`) e o conjunto efetivamente agregado
   divergem com atraso: o ciclo 1 fechava com 19 das 25 programações **sem
   nenhuma perda de pacote**. Os agentes passaram a fazer contabilidade própria,
   por remetente e por número de rodada.

2. **O FIPA não define retransmissão.** Uma rodada tem cerca de 24 mensagens, e a
   probabilidade de perder ao menos uma a 5% é de 71%. Os ciclos 1 e 4 ganharam
   timeout com reenvio apenas aos faltantes, e uma política explícita para quem
   nunca responde: entra com programação nula, isto é, perde a remuneração pelo
   ajuste e a rede perde o recurso dele.

## 5.0 A rede LPWA 6TiSCH da tese

A subseção 6.1.5 especifica a rede com precisão suficiente para ser reproduzida:
IEEE 802.15.4g modo 1 na banda ISM dos EUA, 50 kbps, 16 canais, TSCH com salto de
canal, slotframe de 101 timeslots executado em 4,04 s, quadro máximo de 127 bytes.
O RSSI vem do modelo de Friis menos uma uniforme de 0 a 40 dB (Pister-Hack, LE et
al. 2009, que é a abordagem do Simulador 6TiSCH de MUNICIO et al. 2019), a
conversão para PER é a Tabela 7 da tese, de Prando et al. (2019), com nível de
sensibilidade de −106,37 dBm, e existe enlace entre dois agentes sempre que o PER
fica abaixo de 0,5. As coordenadas dos 77 agentes são as do Apêndice B.

Implementação: `comm-opentes/Tisch.cc`, configuração `-c tisch` do `omnetpp.ini`,
coordenadas em `comm-opentes/nodes_xy.csv`, adjacência em
`comm-opentes/adjacency.txt`, figura em `market_opentes/plot_tisch.py`.

**A adjacência é dado, não reconstrução.** Numa primeira versão ela era gerada a
partir das coordenadas pelo limiar de PER, o que parece fiel mas exige um dado
que a tese não publica: o orçamento de enlace do rádio. A suposição natural de
0 dBm, que é o padrão do Simulador 6TiSCH, produziu **1.466 enlaces** contra os
**578** da matriz publicada, ou seja, um alcance cerca de 12 dB mais folgado. A
diferença é sistemática e não ruído de sorteio. Como a matriz existe no Apêndice C
e no `adj_array.txt` da implementação de referência, ela passou a ser lida do
arquivo, e o modelo de propagação responde apenas pelo PER de cada enlace que
existe. As coordenadas transcritas do Apêndice B, essas sim, conferem exatamente
com o `bus_xy.txt` original.

**O que muda em relação à tese.** Ela roda o Simulador 6TiSCH fora do laço,
extrai PER e atraso e alimenta o ns-3 com esses números. Aqui o caminho é
percorrido salto a salto em tempo de evento do OMNeT++, então o atraso sai da
própria simulação. O roteamento é Dijkstra sobre ETX = 1/(1−PER), que minimiza o
número esperado de transmissões, e não o número de saltos: minimizar saltos
escolheria enlaces longos e ruins.

**Topologia:** 578 enlaces, PER médio de 0,0138 nos viáveis, **3,18 saltos** em
média e nenhum par sem rota.

**Um parâmetro é calibrado, e isso está declarado.** O número de cells alocados
por enlace por slotframe é o que mais mexe no tempo de entrega, e a tese não o
informa. Com 1 cell, a configuração mínima do 6TiSCH, os tempos vão de 6 a 140 s;
com 2 cells ficam entre 6 e 74 s, dentro dos 10 a 90 s que a tese reporta. O
padrão é 2, registrado como calibração e não como previsão do modelo.

| Mensagem | Aqui, com 2 cells | Tese |
|---|---|---|
| 100 B | mediana 6,3 s | 10 a 90 s para 100 a 1500 B |
| 1000 B | mediana 49,2 s | |
| 1250 B | mediana 61,4 s | |
| 1500 B | mediana 73,7 s, p90 88,5 s | |

**O limiar de PER da tese é generoso para mensagens multi-quadro.** A regra admite
enlace sempre que o PER fica abaixo de 0,5, e a Tabela 7 tem degrau em 0,4. Um
enlace admitido com PER 0,4 por quadro, já com as três retentativas do MAC, perde
0,4⁴ = 2,6% dos quadros. Uma mensagem de 100 bytes é um quadro e perde 2,6%; uma
de 1250 bytes são dez quadros, e perder qualquer um perde o datagrama: 22,8%
previstos, 27,5% medidos no enlace 5-36.

A consequência é operacional: com três retransmissões a negociação **aborta na
primeira rodada**, porque o concentrador `trafo_5_35` fica atrás desse enlace. O
padrão de `MAX_RETRIES` subiu para 10, e com ele a negociação converge em 34
rodadas com 57 mensagens perdidas em 2.823 e 43 retransmissões.

Esse efeito só aparece com a topologia publicada. Com a rede densa demais da
primeira versão, os enlaces marginais nunca eram o caminho mais barato e o
problema não se manifestava.

## 5.1 O tamanho das mensagens no modelo de rede original

O `market-simulation` informa ao simulador de rede um tamanho de mensagem
**arbitrário**: `set_message_length(100)` para os CFP e
`set_message_length(np.random.randint(1000, 1500))` para as propostas
(`market_agent.py`, linhas 66, 79, 256 e 269). O conteúdo real de um CFP de
rodada, com o vetor de preço sombra de 25 nós por 96 intervalos mais as
programações, é de **35.663 bytes** em JSON.

**Onde isso importa, e onde não importa.** A análise de comunicação da tese
(subseção 6.2.3.1) é da FASE DE OPERAÇÃO, em que a mensagem carrega um único
intervalo. Medido: o CFP de operação desta implementação tem 1.004 bytes, dentro
dos 1000 a 1500 declarados. Para a fase que a tese mede, portanto, os tamanhos
declarados estão certos e os 10 a 90 s dela se sustentam.

O problema é usar os mesmos valores na programação do dia seguinte, cujo CFP
carrega 96 intervalos: 27.275 bytes só no vetor de preço sombra e nas
programações, e 35.663 bytes na mensagem completa. A tese não reporta comunicação
para essa fase, então o descompasso fica latente no código e não aparece nos
resultados dela. A implementação nova usa o tamanho serializado real
(`_set_content` anota `message.message_length`).

Com a rede 6TiSCH da seção 5.0 no laço, a diferença deixa de ser retórica. A
mesma negociação, rodada duas vezes sobre a mesma rede, mudando apenas o tamanho
informado (`NET_MESSAGE_SIZE=thesis` contra `real`):

| | tamanhos da tese | tamanhos reais |
|---|---:|---:|
| tráfego total | 2,62 MB | 82,01 MB |
| atraso p90 por mensagem | 77,2 s | 3.216,4 s |
| atraso máximo | 96,4 s | 6.574,9 s |
| tempo de rede da negociação | 3,7 h | 6,1 dias |
| rodadas até convergir | 28 | 28 |
| mensagens perdidas | 1 em 2.301 | 1 em 2.305 |

**Ressalva de procedência:** esta tabela foi medida sobre a topologia REGENERADA,
antes de a matriz do Apêndice C passar a ser lida do arquivo. Os valores
absolutos são otimistas.

**Refeita sobre a topologia publicada, a conclusão muda de natureza.** Não é que
a negociação demore mais: ela **não completa**. O agente de mercado tem um único
vizinho, o nó 0, e o nó 0 alcança o nó 5 por um enlace de PER 0,400, o pior dos
oito que ele tem. Os dois não compartilham vizinho nenhum, então não há desvio. O
concentrador `trafo_5_35` fica preso à espinha dorsal por esse único enlace
marginal, e com o conteúdo real das mensagens ele se torna incomunicável:

| Mensagem | Quadros | Perda no enlace 0-5 |
|---|---:|---:|
| CFP da tese, 100 B | 1 | 2,56% |
| Proposta da tese, 1250 B | 10 | 22,84% |
| Proposta real, 27.275 B | 215 | 99,62% |
| CFP real, 35.663 B | 281 | 99,93% |

O limite de projeto que sai disso, para esse enlace:

| Perda de datagrama tolerada | Tamanho máximo da mensagem |
|---|---:|
| 5% | 251 bytes |
| 10% | 516 bytes |
| 25% | 1.409 bytes |
| 50% | 3.394 bytes |

O CFP precisaria encolher de 35,7 kB para cerca de 500 bytes, um fator de 70,
para trafegar com confiabilidade. É o argumento quantitativo para a redução de
mensagem registrada abaixo como extensão.

Antes de abortar, a execução mediu 598 mensagens e 3,46 MB, com 18 perdas, das
quais 11 são as onze tentativas para o concentrador 5. Uma única rodada do ciclo 3
gastou **54,5 minutos de tempo de rede**, contra uma fatia de 5 minutos.

O tempo de rede é o caminho crítico: as mensagens de uma rodada viajam em
paralelo, então a rodada custa o maior atraso dela, e as rodadas é que são
sequenciais.

Três leituras. Primeira, o número de rodadas não muda: a rede altera o tempo, não
o ponto de convergência, o que é o esperado e serve de verificação. Segunda, com
os tamanhos declarados a programação do dia seguinte cabe no tempo disponível,
que é de horas. Terceira, com o conteúdo real das mensagens ela não cabe: 6,1
dias para programar um dia.

O alvo dessa comparação é preciso: ela diz que os tamanhos declarados não valem
para a programação do dia seguinte, e **não** que a análise de comunicação da
tese esteja subestimada, porque aquela análise é da fase de operação, onde os
mesmos valores estão corretos. Ver `REVISAO_TESE.md`, seção 3.2.

Isso não é defeito da formulação de mercado, e sim do que ela precisa transmitir.
O CFP carrega o preço sombra de 25 nós por 96 intervalos a cada rodada. Reduzir
esse vetor, enviando só o que mudou ou só a parte do nó destinatário, é a
extensão natural e fica registrada como tal.

## 5.2 Os dispositivos do prosumidor que não entram na demanda

O `config.json` aloca seis tipos de dispositivo. Apenas três chegam à rede, e
isso é uma característica da implementação de referência, não uma omissão nossa:
no `Prosumer.step` do `prosumer.py` original, as contribuições de
`freely_control_gen`, `shiftable_load` e `buffering_device` estão **comentadas**
(linhas 591, 603 e 609). Os dispositivos são instanciados, recebem `step()` e o
resultado é descartado.

| Dispositivo | Nós | Entra na demanda? |
|---|---:|---|
| `user_action_device` | 68 | sim, é a carga base |
| `stochastic_gen` | 34 | sim, é a geração PV |
| `storage_device` | 25 | sim, é a flexibilidade negociada |
| `dso_storage_device` | 23 | sim, despachado pelo DSO |
| `shiftable_load` | 68 | **não**, inerte no código original |
| `buffering_device` | 54 | **não**, inerte no código original |
| `freely_control_gen` | 3 | **não**, inerte no código original |

Implementar os três inertes afastaria o caso da tese em vez de aproximá-lo dela.
Fica registrado como extensão possível, não como pendência de fidelidade.

## 5.3 A liquidação e o preço locacional

A tese propõe dois ambientes de contratação (subseção 6.1.1): um mercado futuro
bilateral, de preço fixo, em que o prosumidor só pode comprar, e um mercado spot
de tempo real, em que pode comprar e vender. O agente de mercado grava as
transações num `transactions_data.hdf5`.

Duas observações sobre o registro original. **O preço do bilateral não é
gravado**: `save_transactions_data` é chamado sem `value_um`, então o campo fica
no default `-1.0`. E **o spot é registrado ao preço spot puro**, sem qualquer
adicional vindo da negociação.

Sobre o DLMP a tese é explícita (subseção 6.1.4.4): *"Este trabalho não entrará no
mérito da questão de como tratar os valores encontrados para λ(t,l) como valores
financeiros reais. Os valores de preços encontrados serão interpretados apenas
como uma variável de controle"*. A Figura 45 mostra λ como "preço adicional", sem
unidade monetária e sem aplicação a transação nenhuma.

### λ não está em unidade monetária

Isso não é detalhe de implementação. No ótimo do concentrador, derivando
`Ck (x − x_init)² + λ x` em relação a `x`:

```
2 Ck (x − x_init) + λ = 0    =>    λ = 2 Ck (x_init − x)
```

ou seja, **λ tem unidade de `Ck` vezes potência**. Com o `Ck = 1` adimensional da
tese, λ é numericamente um desvio de potência, não um preço. Para virar preço, o
peso da função objetivo precisa ser calibrado em moeda, `Ck` em EUR/(kW²·h), e aí

```
DLMP(t,l) = preço_spot(t) + λ(t,l) / Δt × 1000     [EUR/MWh]
```

`market_opentes/settlement.py` expõe essa calibração em `MARKET_CK_EUR`. Sem ela,
o DLMP é reportado com a conversão aplicada sobre o `Ck = 1`, e deve ser lido como
**sinal**, na mesma condição em que a tese o lê. O aviso vai no cabeçalho do CSV,
para que ninguém cite o número como preço sem saber disso.

Saídas: `transactions.csv` (energia e custo por prosumidor nos dois mercados),
`dlmp.csv` (preço por nó e por intervalo, com o adicional separado do spot) e
`flexibility.csv` (quanto cada prosumidor deslocou e a que preço), gerados por
`python -m market_opentes.dual --settle-dir data`. A figura `dlmp.png` é o
equivalente 2D da Figura 45 da tese.

### O mercado bilateral não cumpre função na formulação da tese

Medido, variando só o que a formulação permite variar:

| Configuração | Bilateral | Spot | Custo total |
|---|---:|---:|---:|
| 1 cenário, neutro ao risco | 3,1 kWh (1,5%) | 211,1 kWh | 4,24 EUR |
| 9 cenários, neutro ao risco | 2,5 kWh (1,3%) | 188,4 kWh | 4,28 EUR |
| 9 cenários + multa por desvio (20 EUR/MWh) | 2,8 kWh (1,4%) | 195,8 kWh | 4,27 EUR |
| 9 cenários + aversão ao risco (CVaR, β = 0,5) | **7,8 kWh (3,8%)** | 195,6 kWh | 4,79 EUR |

A tese apresenta os dois ambientes como uma escolha entre segurança e risco
(subseção 6.1.1: contratar no bilateral "sem maiores riscos financeiros" ou
"correr um pouco mais de risco" no spot). A formulação não realiza essa escolha:
as Equações 6.1 a 6.9 minimizam **custo esperado**, sem termo de aversão, e o
mercado de tempo real não tem limite de quantidade. Sob neutralidade ao risco, a
decisão entre um preço fixo e um preço variável é uma comparação de esperanças, e
o bilateral só entra nos intervalos em que o spot esperado passa de 38 EUR/MWh.

A multa por desvio, que o texto da tese descreve mas as equações não têm, **não
resolve**: comprar mais no bilateral reduz o nível do spot, não a dispersão dele
entre cenários, então a multa é indiferente à escolha entre os mercados. Isso foi
medido, não deduzido.

O que dá papel próprio ao contrato de preço fixo é aversão ao risco. Com um termo
de CVaR, a participação do bilateral quase triplica e o custo sobe 12%, que é o
prêmio pago pela proteção. As três extensões estão implementadas e desligadas por
padrão (`MARKET_DEVIATION_PENALTY`, `MARKET_CVAR_BETA`, `MARKET_CVAR_ALPHA`): o
default reproduz a tese.

## 5.4 O despacho da programação acordada

Fechada a negociação, a programação precisa **chegar** a quem a executa. No
original isso é feito por FIPA-Subscribe (`DSOPublisherProtocol`,
`BESSPublisherProtocol`, `ProsumerSubscriberProtocol`), e uma versão anterior
desta implementação simplesmente aplicava o resultado da otimização do DSO sem
ato comunicativo nenhum. Além de infiel à arquitetura, isso subestimava o tráfego
que a análise de comunicação mede.

A cadeia implementada segue a da tese:

```
prosumidores  --assinam-->  concentrador  --assina-->  DSO
                                                        |
         acordo fechado, o DSO publica a programação ---+
                                                        v
concentrador aciona o armazenamento de REDE sob o seu transformador
concentrador publica a parte de cada prosumidor
prosumidores confirmam --> concentrador confirma --> DSO confirma --> mercado encerra
```

Com isso o **Agente Concentrador passa a ter o papel que a tese lhe dá**: acionar
os dispositivos de armazenamento diretamente controláveis sob o seu
transformador. O DSO decide, o concentrador despacha. Antes o DSO otimizava o
armazenamento de rede e o resultado era aplicado sem passar por ninguém.

O agente de mercado só encerra o passo do Mosaik quando o despacho é confirmado,
com timeout, pelo mesmo motivo dos ciclos de negociação.

### Quanto isso pesa no tráfego

Medido numa negociação de 28 rodadas, com a telemetria da camada de rede, antes
da reestruturação dos três ciclos e da troca da topologia:

| Etapa | Mensagens | Bytes |
|---|---:|---:|
| Assinatura (arranque) | 60 | desprezível |
| Negociação (28 rodadas) | 2127 | 79,80 MB |
| **Despacho** | **127** | **2,04 MB** |
| Total | 2320 | 82,16 MB |

Com o ciclo 2 existindo de fato e a topologia do Apêndice C, a mesma negociação
passou a 34 rodadas e 2.823 mensagens, das quais 57 perdidas e 43 retransmitidas.
As proporções entre as etapas não mudam.

A etapa acrescenta 8,1% das mensagens e 2,5% dos bytes. Não muda a ordem de
grandeza, mas é o que faltava para a contagem de mensagens corresponder à
arquitetura descrita, e é indispensável no cenário com perda: uma confirmação
perdida agora tem consequência, e o timeout de despacho existe por isso.

## 5.5 O reativo do armazenamento e a hipótese ΔQ = 0

A Eq. 6.16 lineariza a tensão apenas em potência ativa. Isso é exato enquanto o
dispositivo despachado não mexer em reativo, e a tese diz isso explicitamente. A
pergunta que fica é o que acontece quando ele mexe, já que um inversor comum
opera com fator de potência constante e faz o reativo acompanhar o ativo.

A resposta exigiu obter também `∂V/∂Q`, pelo mesmo método de perturbação já usado
para `∂V/∂P` (`sensitivity.py`). Na MVLV75 a razão entre as duas, na diagonal, é
de 0,457: cada kvar move a tensão pouco menos da metade do que move um kW.

Como a mesma variável de decisão move as duas potências quando o fator de
potência é fixo, o efeito cabe numa única matriz efetiva,

```
S_efetiva = ∂V/∂P + tan(φ) · ∂V/∂Q
```

e o resto do modelo do DSO permanece idêntico. Com `MARKET_STORAGE_PF=none`, que
é o padrão, tan(φ) é zero e a matriz é exatamente a da tese.

**Medição.** Três configurações no fluxo de potência não linear completo. O par
que importa é o segundo contra o terceiro: mesmo sistema físico, modelo cego
contra modelo ciente. Comparar o primeiro com os outros compararia dois sistemas
diferentes, e não diria nada sobre a hipótese.

| Dispositivo | Modelo | Faixa de tensão | Abaixo de 0,97 pu |
|---|---|---|---:|
| sem reativo | ΔQ = 0 (a tese) | 0,96955 a 1,02718 pu | 4 |
| fp 0,9 | ΔQ = 0 | 0,96493 a 1,03588 pu | 117 |
| fp 0,9 | com ∂V/∂Q | 0,96956 a 1,02751 pu | 5 |

Ignorar o reativo custa 117 violações em vez de 5, e leva a tensão a estourar o
limite superior, o que não ocorre em nenhuma das outras duas configurações. Com o
termo incluído, o desempenho volta ao do caso da tese.

O reativo entra nos dois lados ao mesmo tempo: na restrição do DSO e na injeção
que vai para o OpenDSS. Ligar só um lado seria pior que ignorar nos dois, porque
o modelo passaria a resolver a restrição contra uma rede que se comporta de outro
jeito. A chave `MARKET_IGNORE_DQ` desfaz esse pareamento e existe apenas para
produzir a linha do meio da tabela; não é opção de operação.

**O que isto NÃO é.** O reativo aqui é consequência do fator de potência do
dispositivo, não variável de decisão. Despachar reativo como serviço, dentro da
capacidade do inversor, daria ao DSO uma segunda alavanca de tensão, mais barata
que deslocar energia. Isso é controle Volt/Var e fica registrado como extensão,
fora do escopo desta camada.

## 6. Limitações conhecidas
- **A restrição de estado de carga terminal é NOSSA, não da tese.** A Eq. 6.9 não
  a tem, e sem ela o modelo despeja a energia da bateria no último intervalo,
  porque ela não vale nada na função objetivo. Está ligada por padrão
  (`MARKET_TERMINAL_SOC=1`); desligá-la reproduz o comportamento do original.
- **A restrição de tensão precisa de margem contra o próprio erro.** O
  otimizador cola a solução no limite, e o erro da linearização (1e-4 a 6e-4 pu)
  vira violação no fluxo de potência completo: sem margem, a negociação promete
  0,9700 pu e o OpenDSS entrega 0,96924, com 104 pontos violados. Com
  `V_BACKOFF = 1e-3` aplicado aos limites dentro do modelo, o fluxo não linear
  fica em 0,97020 pu e nenhuma violação. Isso NÃO existe na tese, que usa a mesma
  restrição linearizada sem recuo; só aparece quando a restrição passa a atuar de
  fato. Na operação, com o ponto de operação vindo do fluxo de potência, o
  resíduo medido é maior: 1,5e-3 pu com margem de 1e-3, e 4,5e-4 pu com margem de
  2e-3, que é o padrão atual (`MARKET_V_BACKOFF`). Aumentar mais troca resíduo
  por custo de programação com retorno decrescente.
- **A fase de operação resolve o fluxo de potência uma vez, no arranque.** Os 96
  pontos de operação dependem só da demanda realizada, não das variáveis de
  decisão, então não há o que recalcular por rodada. A alternativa, resolver sob
  demanda dentro do `handle_request` do solver, derruba o processo com
  `std::bad_alloc`: o `py_dss_interface` não é seguro para uso concorrente e o
  `handle_request` roda no pool de threads do Twisted.
- **A hipótese ΔQ = 0 da Eq. 6.16 é condicional, não geral.** Ela vale enquanto o
  dispositivo despachado não mexer em reativo, que é a premissa da tese. Se ele
  mantiver fator de potência constante, como faz um inversor comum, o erro da
  previsão de tensão sobe de 2,6e-5 para 1,0e-3 pu, quarenta vezes, e o efeito no
  fluxo não linear completo é de 5 para 117 pontos violados, com a tensão máxima
  estourando o limite superior em 1,03588 pu. Ver seção 5.5.
- **O critério `|Δλ| ≤ ε` é um resíduo primal escalado por α.** Com passo
  decrescente ele pode disparar pela queda do passo e não pela do resíduo.
  Compare sempre pelo resíduo primal, que é reportado ao lado.
- **O passo constante não converge ao ótimo**, e sim a uma vizinhança cujo raio
  cresce com α. Acima de α = 0,6 nesta rede o raio ultrapassa a tolerância.
- **O roteamento depende do TAMANHO da mensagem.** O ETX clássico, `1/(1−PER)`,
  vale para um quadro; um datagrama de N quadros perde `1−(1−p)^N`, porque perder
  qualquer fragmento perde o todo. Roteando por quadro, o servidor escolhia
  caminhos incapazes de entregar a mensagem que estava roteando. O custo agora é
  calculado para o número de quadros da mensagem em trânsito. Na MVLV75 isso não
  salva o nó 5, que não tem caminho alternativo, mas evita a classe de erro.
- **O 6TiSCH avança o relógio de simulação e nunca o zera.** Cada consulta de
  rota empurra o relógio do OMNeT++ pelo atraso da própria mensagem, então uma
  negociação inteira soma milhões de segundos simulados. Com o `simtime-scale`
  padrão, de picossegundos, o `simtime_t` de 64 bits estoura em 9,2e6 s, ou 106
  dias, e a simulação morre no meio. O `omnetpp.ini` usa nanossegundos, que
  levam o teto a 9,2e9 s.
- **O cliente do 6TiSCH serializa o acesso por trava.** O socket ZMQ do tipo REQ
  alterna envio e recepção por máquina de estados e não é seguro para uso
  concorrente, e o `SolverProtocol` responde de dentro de um `defer_to_thread`.
  Sem a trava o socket para com `Operation cannot be accomplished in current
  state` e a negociação fica esperando para sempre.
- **A rede é o caso de regressão, não o caso principal.** O `force.json` é um
  grafo sintético do trabalho original. O IEEE European LV Test Feeder, decidido
  como caso principal citável, ainda não foi montado.
