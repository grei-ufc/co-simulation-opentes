# Resultados da co-simulação OpenTES: guia da pasta `output/`

Este documento explica, de forma didática, **tudo o que a co-simulação grava em
`output/`**: o que cada arquivo `.csv` significa (coluna a coluna, linha a
linha) e por que cada gráfico tem o comportamento que tem. A ideia é que
qualquer pessoa, mesmo sem conhecer o código, consiga ler os resultados.

> Conceito-base: o tempo avança em **passos de 5 minutos**. Um dia inteiro =
> **288 passos**. Cada **linha** dos arquivos de resultado é **um passo** (um
> instante do dia). A coluna `date` diz qual instante.

```
output/
├── integrated/                    ← co-simulação completa do IEEE 13: rede elétrica + comunicação
├── market/                        ← mercado transativo na rede de 75 barras da tese
├── market_13Bus/                  ← mercado transativo sobre o próprio IEEE 13
├── market_BT16/, market_BT38/     ← mercado transativo nas redes projetadas
├── ieee13/                        ← teste isolado da rede elétrica (sem comunicação)
├── star/                          ← teste isolado da comunicação (sem rede elétrica)
├── sensibilidade_48h/             ← cenário integrado em horizonte de 48 h
└── sensibilidade_perda*/          ← varredura de perda de pacotes (1 e 20 sementes)
```

> **Atenção ao passo de tempo.** Os cenários `integrated`, `ieee13` e `star`
> avançam de **5 em 5 minutos** (288 passos por dia). O cenário `market` avança
> de **15 em 15 minutos** (96 intervalos), que é a resolução do mercado. Ao
> comparar arquivos de cenários diferentes, confira qual é a base.

---

## 1. `output/integrated/`, a co-simulação completa

É o cenário principal. Roda **duas vezes** e gera dois conjuntos de arquivos:

- sufixo **`_baseline`** → execução **SEM** controle (os inversores só injetam a solar);
- sufixo **`_volt_var`** → execução **COM** controle Volt/Var (os agentes regulam a tensão).

Comparar os dois é o experimento: *"o controle, decidido por agentes que recebem
a tensão pela rede de comunicação, melhora a operação da rede?"*

### 1.1. `result_baseline.csv` e `result_volt_var.csv`: o estado ELÉTRICO

São **288 linhas** (um dia) e **74 colunas**. A coluna `date` é o instante; as
demais se dividem em **6 grupos** (lidos da co-simulação a cada passo):

| Grupo de colunas | Quantas | Exemplo de coluna | O que é |
|---|---|---|---|
| **Tensão das barras** | 48 | `DSS-0.Bus-632-V1_pu` | Tensão em *por unidade* (1,0 = nominal) na barra `632`, fase 1. São 16 barras × 3 fases. Fases inexistentes (trecho monofásico) ficam ~0 e são ignoradas. |
| **P_dc dos painéis** | 5 | `PVSimulator-0.PVPanel_0-P_dc` | Potência **ativa disponível** (corrente contínua) que o painel solar entrega ao inversor, em kW. Depende da irradiância. |
| **P_ref dos controladores** | 5 | `PadeSim-0.AgenteB_1-P_ref` | Potência **ativa** que o agente **mandou** o inversor injetar (kW). Aqui = a solar disponível. |
| **Q_ref dos controladores** | 5 | `PadeSim-0.AgenteB_1-Q_ref` | Potência **reativa** que o agente decidiu (kvar), a "alavanca" do Volt/Var. No baseline é sempre 0. |
| **P_meas dos PVs** | 5 | `DSS-0.PVSystem-pv1-P_meas` | Potência **ativa medida** nos terminais do inversor pelo OpenDSS (kW), o que de fato entrou na rede. |
| **Q_meas dos PVs** | 5 | `DSS-0.PVSystem-pv1-Q_meas` | Potência **reativa medida** pelo OpenDSS (kvar). |

> `P_ref` é o **setpoint** que o agente comanda e `P_meas` é o que o OpenDSS
> injeta depois de resolver o circuito. Neste cenário os dois coincidem: o
> setpoint cabe nos limites do inversor. Já houve uma diferença grande e ela era
> defeito, não física: o PV1 estava declarado em três fases numa barra que só tem
> duas, e 37% da potência ia para um nó que nenhum outro elemento usa. Uma
> diferença sistemática entre `P_ref` e `P_meas` é motivo para desconfiar da
> declaração do elemento.

#### Lendo linha a linha (exemplos reais do `result_volt_var.csv`)

**Linha da meia-noite** (`date = 2026-01-01`, passo 0):

```
P_dc = 0   |  P_ref = 0   |  Q_ref = 0   |  P_meas = 0   |  V ≈ 1,00 pu
```

*Interpretação:* **sem sol**, o painel não gera (`P_dc = 0`), então o inversor
não injeta nada e o agente não tem o que controlar (`Q_ref = 0`). A rede está
quase no nominal (~1,0 pu), só com a carga noturna.

**Linha do meio-dia** (passo 144, PV2 na barra 632):

```
P_dc = 517,8 kW  |  P_ref = 517,8 kW  |  Q_ref = 0 kvar  |  P_meas = 517,8 kW
```

*Interpretação:* **com sol**, o painel entrega 517,8 kW; o agente repassa essa
ativa (`P_ref = P_dc`) e, como a tensão daquela barra está **dentro da faixa
morta** (0,98–1,02 pu), ele decide `Q_ref = 0` (não precisa corrigir). No mesmo
instante o PV1, na barra 646, já está acima da faixa e **absorve** 27,3 kvar,
enquanto o PV5, na 652, **injeta** 13,9 kvar. As duas pontas do controle
aparecem no mesmo passo.

**Quando o Volt/Var atua:** numa barra subtensionada (ex.: Bus 652, que chega a
0,92 pu), o agente da barra calcula um `Q_ref > 0` (injeta reativo) para
**levantar** a tensão; numa barra acima de 1,02 pu ele calcula `Q_ref < 0`
(absorve reativo) para **baixar**. É esse número que diferencia o
`result_volt_var.csv` do `result_baseline.csv`.

### 1.2. `comm_trace_baseline.csv` e `comm_trace_volt_var.csv`: o estado da COMUNICAÇÃO

Aqui mora a prova de que **a tensão trafega pela rede OMNeT++**. O formato é
"longo": **4 colunas** (`Tempo, Origem, Atributo, Valor`) e ~2304 linhas (288
passos × 8 atributos). `Origem` é sempre o nó da rede (`OmnetSim-0.node_0`).

Cada passo registra **8 atributos** (a coluna `Atributo` diz qual; `Valor`
guarda o dado):

| Atributo | O que é | Como ler |
|---|---|---|
| `val_out` | As **mensagens FIPA-ACL** que saíram da rede naquele passo | Texto JSON, várias mensagens separadas por `\|\|\|` |
| `packets_sent` | Total acumulado de pacotes **enviados** | Número |
| `packets_received` | Total acumulado **entregues** | Número |
| `packets_dropped` | Total acumulado **perdidos** | Número |
| `latencies_out` | **Latência** de cada pacote do passo (s) | Lista separada por `\|\|\|` |
| `jitters_out` | **Jitter** (atraso extra aleatório) de cada pacote (s) | Lista separada por `\|\|\|` |
| `packet_sizes_out` | **Tamanho** de cada pacote (bytes) | Lista separada por `\|\|\|` |
| `status` | Estado do nó (`idle`/`ok`) | Texto |

#### Exemplo de uma mensagem (`val_out`, passo t=600 s = 00:10)

```json
{"sender": "AgenteA_2", "bus": "632", "ontology": "medicao_tensao",
 "conversation_id": "meas-632-t600", "V_meas": 0.963648, "t": 600}
```

*Interpretação, palavra por palavra:* o medidor **`AgenteA_2`** leu a tensão da
barra **`632`** e mediu **`V_meas = 0,9636 pu`** no instante **`t = 600 s`**.
Essa carta entrou na rede OMNeT++, sofreu latência/jitter (e pode ter sido
descartada), e, se chegou, o controlador da barra 632 (`AgenteB_2`) a leu e
calculou o reativo. **É essa carta, com a tensão real lá dentro, que liga os
dois mundos.**

> Como verificar a integridade: pegue o último `packets_sent` e o último
> `packets_dropped`. No nosso caso, **1.227 enviados, 213 perdidos (17,4%)**, que
> é o efeito do parâmetro `drop_probability = 0,15` do modelo de rede, com a
> flutuação de um sorteio por pacote.

### 1.3. `dashboard_integrated.png`, o resumo visual (8 quadros)

O painel junta os dois domínios. Abaixo, **o que cada quadro mostra e por que ele
se comporta assim**:

**1) Irradiância solar (5 PVs).** Curva em sino: **zero à noite**, sobe após o
nascer do sol (~6h), **pico ao meio-dia/início da tarde**, cai até zerar no
pôr do sol (~18h). As 5 curvas diferem um pouco porque vêm de **dados reais**
(dataset BR-PVGen): há nuvens e ruído.

**2) Temperatura dos módulos (5 PVs).** Acompanha a irradiância **com atraso**:
os módulos esquentam *depois* que o sol bate, então o pico de temperatura vem
**um pouco depois** do pico solar e cai devagar à tarde. Por isso a curva é
"empurrada para a direita" em relação ao quadro 1.

**3) Geração fotovoltaica agregada.** Duas linhas: **Σ disponível** (tracejada =
irradiância × potência nominal dos 5 PVs) e **Σ P_meas injetado** (o que de fato
entrou na rede). Ambas seguem o sol, com pico de 4.390 kW no início da tarde. A
temperatura do módulo desconta parte da geração pela curva potência-temperatura
do painel, o que é o motivo de a curva não acompanhar a irradiância ponto a
ponto.

**4) Tensões nas 13 barras (p.u.).** À noite ficam próximas de 1,0 (carga leve,
sem PV). Durante o dia, a **injeção dos PVs tende a levantar** as barras, e a
**carga tende a baixar**, e o equilíbrio varia por barra: as **mais distantes da
subestação** (ex.: 652, 611) afundam mais (subtensão); a barra da **fonte (650)**
fica colada em 1,0. As linhas pontilhadas marcam os limites ANEEL (0,95–1,05).

**5) Integridade dos pacotes (pizza).** Mostra **entregues × dropados** no dia.
No nosso caso **82,6% entregues / 17,4% dropados**, reflexo direto do
`drop_probability` do modelo de rede. (Ver discussão sobre esse parâmetro em
[`INTEGRACAO.md`](INTEGRACAO.md#a-perda-de-pacotes-é-parâmetro-não-resultado).)

**6) Latência exata por pacote.** Cada ponto é **um pacote**: o eixo Y é o atraso
em ms (32–451 ms aqui). A nuvem de pontos sobe quando há **mais pacotes
competindo** pela banda no mesmo instante (mais fila → mais latência).

**7) Jitter distribuído.** O **atraso extra aleatório** de cada pacote (média
44 ms, contra o parâmetro de 50 ms). É o que torna a chegada das mensagens **irregular**: duas medições
seguidas podem chegar com espaçamentos diferentes. Espalhamento é esperado:
é estocástico por natureza.

**8) Efeito Volt/Var nas 5 barras PV.** Para cada barra controlada, a linha
**pontilhada** é o baseline (sem controle) e a **sólida** é com Volt/Var; a
faixa cinza é a zona morta. Onde a sólida está **mais próxima de 1,0 / mais
"puxada para dentro"** que a pontilhada, o controle **regulou** a tensão. O
efeito é maior na barra mais crítica (652): a mínima sobe de **0,9203 → 0,9366
pu**. Na 646 o controle age no sentido oposto e a máxima cai de **1,0517 →
1,0437 pu**.

### 1.4. Figuras dedicadas de comparação e análise

Além do dashboard de 8 quadros, há duas figuras **focadas** (mais legíveis para
a apresentação), geradas por `plot_comparacao.py`:

**`comparacao_volt_var.png`, o controle atuando × não atuando.** É a resposta
direta a "qual a diferença, em p.u., do Volt/Var ligado vs desligado":

- *Linha de cima*: um quadro por barra PV (646, 632, 634, 645, 652). Em cada um,
  a curva **vermelha tracejada** é SEM controle e a **verde sólida** é COM
  Volt/Var. A faixa cinza é a zona morta; a linha pontilhada inferior é o limite
  ANEEL (0,95 pu). Onde a verde está **acima** da vermelha, o controle deu
  **suporte de tensão** (injetou reativo e levantou a barra subtensão).
- *Embaixo, à esquerda*: **desvio-padrão (σ) da tensão por barra**, vermelho
  (sem) vs verde (com). Barra verde mais baixa = tensão **menos oscilante** =
  controle regulando. **↓ é melhor.**
- *Embaixo, ao centro*: **tensão mínima do dia por barra**. Barra verde mais
  alta = o controle **tirou a barra do fundo do poço** (afastou da subtensão).
  **↑ é melhor.**
- *Embaixo, à direita*, o resumo: **σ médio −15%** (0,0198 → 0,0169 pu), a mínima
  crítica do Bus 652 subindo **0,9203 → 0,9366 pu** e a máxima do Bus 646 caindo
  **1,0517 → 1,0437 pu**. O quadro imprime o máximo medido por barra, e não a
  afirmação de que os máximos foram preservados: com o medidor corrigido, o
  controle também corta sobretensão.

> Por que o efeito é "modesto"? O ganho é **propositalmente suave**
> (`Q_MAX_PCT = 0,05`). Com 5 inversores agindo juntos sob atraso/perda de rede,
> um ganho agressivo desestabiliza (chegou a ~1,12 pu nos testes). O valor da
> figura é mostrar que, mesmo suave, o controle **mede melhora consistente** em
> todas as barras, e que comunicação ruim limita o quão agressivo dá para ser.

**`analise_comunicacao.png`, caracterização da rede de comunicação.** Quatro
quadros que descrevem a **qualidade do canal** que o controle enfrenta (é a
mesma rede no baseline e no Volt/Var, com a mesma semente, então caracterizamos uma
execução, não comparamos as duas):

- *Histograma de latência*: distribuição do atraso de entrega. Concentrado nos
  valores baixos com **cauda à direita** (média ~81 ms): a maioria chega rápido,
  alguns poucos demoram muito (fila/congestionamento momentâneo).
- *Histograma de jitter*: distribuição do atraso aleatório extra. Média de
  44 ms, **coerente com o parâmetro** `jitter_mean = 0,05 s` do modelo, ou seja,
  a figura **valida** que o OMNeT++ está aplicando o atraso configurado.
- *Pizza de integridade*: dos **1.227** pacotes enviados, **1.014 entregues
  (82,6%)** e **213 dropados (17,4%)**. Reflete o `drop_probability = 0,15`
  (a perda observada flutua em torno dos 15% por ser **estocástica**).
- *Pacotes acumulados*, três linhas no tempo: **enviados** (azul, sobe até 1.227),
  **entregues** (verde = enviados − dropados) e **dropados** (vermelho). O **vão
  entre a azul e a verde é exatamente a perda** acumulada ao longo do dia.

> Detalhe de leitura: no `comm_trace`, `packets_received` espelha `packets_sent`
> (todo pacote "chega" ao nó e o descarte é marcado à parte). Por isso o
> **entregue real** é sempre `enviados − dropados`, e é assim que a figura conta.

---

## 2. `output/market/`, o mercado transativo

Roda a negociação multiagente sobre a rede de **75 barras**, em **96 intervalos
de 15 minutos**. Com `MARKET_NETWORK=BT16`, `BT38` ou `13Bus` a mesma execução
usa outra rede e grava em `output/market_BT16/`, `output/market_BT38/` ou
`output/market_13Bus/`; a estrutura dos arquivos é idêntica, muda o número de
barras. Como o `integrated`, roda **duas vezes** e grava dois arquivos:

- **`result_baseline.csv`**, a execução **sem mecanismo nenhum**: nem negociação
  do dia seguinte, nem correção na operação. É a linha de base.
- **`result_negociado.csv`**, a execução **com** a negociação multiagente.

A rede vê a **mesma demanda realizada** nas duas passadas, então a comparação
isola o efeito do mercado.

### Como ler as colunas

Cada linha é um intervalo de 15 minutos. As colunas seguem o padrão
`DSS-0.Bus-n<barra>-V1_pu`, ou seja, a tensão da barra `<barra>` em pu. São 75
barras, o que dá **7.200 medições de tensão** por arquivo.

O número que resume o resultado é a **contagem de pares (barra, intervalo) abaixo
de 0,97 pu**. Não é o número de barras ruins nem de instantes ruins: é a
contagem de células da tabela de 75 por 96. Serve melhor que a tensão mínima
porque distingue uma violação isolada de um problema espalhado.

| Caso | Tensão mínima | Tensão máxima | Pontos abaixo de 0,97 pu |
|---|---:|---:|---:|
| `result_baseline.csv` | 0,93946 pu | 1,02488 pu | **337** |
| `result_negociado.csv` | 0,97033 pu | 1,02282 pu | **0** |

O horário crítico é **17:45**, quando a demanda sobe e a geração solar já caiu.

### O caso `13Bus`, em `output/market_13Bus/`

O mesmo alimentador que valida a plataforma, agora com 14 bancos de
armazenamento somando 5.350 kW. Aqui o problema é a **sobretensão**, e não a
subtensão da MVLV75, o que torna visível o passo intermediário do mecanismo:

| Caso | Faixa de tensão | Violações (baixa, alta) |
|---|---|---:|
| carga base | 0,9846 a 1,0780 pu | (0, 72) |
| cada prosumidor otimizando sozinho | 0,9432 a 1,1041 pu | (14, 157) |
| negociado | 0,9710 a 1,0290 pu | **(0, 0)** |

A linha do meio é o argumento do mecanismo: **otimizar cada bolso contra o preço
piora a rede**, de 72 para 171 pares barra-intervalo violados. A negociação
converge em 98 rodadas e zera os dois lados. Conferido no fluxo não linear do
OpenDSS, com a média das fases, o dia inteiro cabe em ANSI Range A.

Na co-simulação completa, com os agentes reais e a rede 6TiSCH no laço, a
negociação converge em 81 rodadas com 3.212 mensagens e nenhuma perda, e as
leituras **por fase** fora de ANSI Range A caem de 191 para 104. A diferença
para a execução centralizada tem três causas medidas: a medição é por fase e não
a média que o DSO enxerga, o regulador está livre e disputa a variável com o
mercado, e a demanda é a realizada, não a programada. O estudo completo está em
`Docs_Externo/ESTUDO_IEEE13.md`.

### As figuras, em `simulators/market-opentes/data/`

Diferente dos outros cenários, as figuras do mercado não ficam em `output/`, e
sim junto do pacote que as gera.

| Figura | O que mostra |
|---|---|
| `tensao_mercado.png` | tensão mínima e máxima da rede nas 24 h, com e sem negociação |
| `programacao_no.png` | a programação que o concentrador propõe e a que o DSO aceita, rodada a rodada, num nó |
| `dlmp.png` | onde e quando o preço apareceu, por nó e por hora |
| `convergencia.png` | o desacordo entre as partes caindo, e o preço estabilizando |
| `operacao.png` | a fase de operação: tensão antes e depois da intervenção |
| `comunicacao.png` | o custo de comunicação da negociação |
| `tisch_per.png` | erro de pacote por distância na rede 6TiSCH |
| `ciclos.png` | tempo de rede de cada ciclo contra a fatia dele na janela de 15 min |
| `arquitetura_simsg.png`, `fluxo_cosimulacao.png` | diagramas da arquitetura e do fluxo |

Também são gravados três CSV de liquidação: `transactions.csv` (energia e custo
por prosumidor nos dois mercados), `flexibility.csv` (quanta flexibilidade cada
um entregou) e `dlmp.csv` (o preço locacional por nó e intervalo).

> **A unidade do preço.** Com o peso adimensional adotado, o multiplicador não
> está em unidade monetária, e as colunas saem como `_signal`. Vira preço quando
> o peso for calibrado em moeda, e aí as colunas saem como `_eur`. A própria tese
> de referência trata o valor como variável de controle, não como dinheiro.

### Como gerar

```bash
export CPLEX_HOME=/caminho/para/cplex        # licença pessoal, não vai no repo
./run.sh market

# as figuras, depois da execução
docker run --rm -v "$PWD/simulators/market-opentes:/market" \
  -v "$PWD/output:/app/output" -w /market opentes/mosaik:local \
  python -m market_opentes.plot_results --output-dir /app/output/market
```

A figura de ciclos exige uma camada de rede: o `./run.sh market` roda com entrega
ideal. Cada figura sai **carimbada no rodapé** com a configuração que a produziu,
justamente para que execuções diferentes não sejam confundidas.

---

## 3. `output/ieee13/`, teste isolado da rede elétrica

Roda **só** a rede (OpenDSS + 5 PVs + inversores), **sem** comunicação nem
agentes. É a bancada de **validação da física**.

- **`result_run_ieee13_cosim_pv_5min.csv`**, com as mesmas grandezas elétricas
  (tensões, P/Q dos PVs), 288 passos. Máximos do dia: `P_dc` de 2.531,8 kW no
  PV1, e geração agregada injetada de 4.030,4 kW. Aqui, ao contrário do cenário
  integrado, o `P_ac` passa pelo estágio de eficiência do inversor, então fica
  abaixo do `P_dc`.
- **`ieee13_dashboard.png`**, com 4 quadros: irradiância, geração (P_dc e P_meas),
  tensões das barras e temperatura.

A referência de validação não é a execução anterior do TSRE, e sim o **perfil de
tensão publicado do IEEE 13**: com as derivações do regulador nos valores
oficiais, o circuito o reproduz com erro médio de 0,00044 pu e máximo de
0,00134 pu nas 33 medidas de fase da tabela. Use este cenário quando quiser
conferir se uma mudança quebrou a parte elétrica.

---

## 4. `output/star/`, teste isolado da comunicação

Roda **só** a comunicação (50 agentes PADE conversando em estrela via OMNeT++),
**sem** rede elétrica. É a bancada para estudar a rede de comunicação sozinha.

- **`results.csv`**, no formato `Tempo, Origem, Atributo, Valor` (igual ao
  `comm_trace`), com a telemetria de rede e as mensagens trocadas.
- **`grafico_trafego.png`**, o dashboard de tráfego: latência, jitter, tamanho de
  pacote e a **pizza de integridade** (entregues/dropados). É a referência visual
  que o quadro 5 do dashboard integrado reaproveita.

---

## Como gerar/atualizar os gráficos

```bash
# dashboard do cenário integrado (após ./run.sh integrated)
docker compose run --rm --no-deps -e MOSAIK_OUTPUT_DIR=/app/output/integrated \
  mosaik python plot_integrated.py

# figuras dedicadas: comparacao_volt_var.png + analise_comunicacao.png
docker compose run --rm --no-deps -e MOSAIK_OUTPUT_DIR=/app/output/integrated \
  mosaik python plot_comparacao.py

# dashboard do ieee13 isolado (após ./run.sh ieee13)
docker compose run --rm --no-deps mosaik python plot_ieee13.py
```

Os números e observações consolidados (efeito do controle, estabilidade,
parâmetro de perda) estão em [`INTEGRACAO.md`](INTEGRACAO.md#resultados).

---

## Experimento: sensibilidade à perda de pacotes

O estudo do **impacto da qualidade da comunicação** sobre o controle distribuído
(varredura de perda **0→100% em passos de 5%**, **20 sementes/nível**) tem doc
própria, mantida fora do repositório em `Docs_Externo/EXPERIMENTO_PERDA.md`.
Roda com `./run.sh loss-multiseed` e gera
`sensibilidade_perda_multiseed.png`. Achado central: a redução do desvio-padrão
da tensão fica em **15% até 75% de perda**, com variação entre sementes abaixo de
0,3 ponto percentual, cai a partir de 80%, chega a 10,8% com 95% e desaparece em
100%, quando o reativo vai a zero. A explicação está na dinâmica do caso: a
tensão muda devagar entre passos de 5 min e o controlador segura o último reativo
válido, então a perda só pesa quando as medições passam a chegar com intervalos
de vários passos. Não generalize para controles de passo curto.

Uma ressalva de leitura: o "lift da média" premia injeção, e não regulação, então
ele não serve como métrica do controle.
