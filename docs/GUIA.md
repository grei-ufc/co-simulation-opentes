# Guia do repositório

Para quem abre esta pasta pela primeira vez. Explica o que o trabalho faz, como
as peças se encaixam, o que rodar, onde cada coisa está e o que ler em seguida.

O `README.md` na raiz é a referência de instalação e comandos. Este documento é o
mapa: por que o repositório tem esta forma.

---

## 1. O que este trabalho é

Uma **plataforma de co-simulação multidomínio** para redes elétricas
inteligentes, e uma aplicação dela a um **sistema transativo de energia**.

O problema de fundo: avaliar uma rede com geração distribuída e prosumidores
negociando energia exige três coisas ao mesmo tempo, e elas costumam ser
simuladas em separado.

1. **A rede elétrica.** Onde a tensão cai, onde o transformador satura.
2. **A rede de comunicação.** Quanto tempo uma mensagem leva, quantas se perdem.
3. **A decisão dos agentes.** Quem propõe o quê, quem aceita, a que preço.

Simular só a primeira dá um estudo de fluxo de potência. Simular as três juntas
mostra o que nenhuma delas mostra sozinha: por exemplo, que um protocolo de
negociação que funciona com entrega instantânea perde propostas quando a entrega
atrasa, e que a programação resultante viola a tensão que ela deveria proteger.

Quatro simuladores, um por domínio, mais um orquestrador que sincroniza o tempo
entre eles:

```
      PADE (agentes)  ─┐
                       ├─  Mosaik (orquestrador do tempo)  ─┐
   OMNeT++ (comunicação)┘                                   ├─ OpenDSS (rede elétrica)
                                                            ┘
```

O Mosaik é o maestro: ele decide quem executa em que instante e transporta os
dados entre os simuladores. Nenhum simulador conhece os outros.

## 2. As duas metades do repositório

O repositório cresceu em duas etapas, e isso explica a estrutura.

**A primeira metade é a plataforma.** Agregação do que três times do projeto
OpenTES desenvolveram em separado (comunicação, agentes, rede elétrica), a
modernização do PADE para Python 3.12, e a dockerização. O benchmark é o IEEE 13
Barras. Documentado em `INTEGRACAO.md` e `RESULTADOS.md`.

**A segunda metade é o mercado transativo.** O porte da camada de mercado da tese
de doutorado do prof. Lucas Silveira Melo para esta plataforma, sobre uma rede de
75 barras. É o TCC. A formulação está em `MERCADO.md`; o código, no
`INTEGRACAO.md`; o confronto com a tese, em `Docs_Externo/`.

As duas convivem: os cenários da primeira continuam rodando, e o mercado é mais
um cenário.

## 3. Estrutura das pastas

```
co-simulation-opentes/
├── docker-compose.yaml      um serviço por simulador, agrupados por profile
├── run.sh                   ponto de entrada único: ./run.sh <cenario>
├── README.md                instalação e comandos
├── docs/                    ver a seção 6
├── output/                  resultados das execuções (CSV das co-simulações)
└── simulators/
    ├── comm-opentes/        rede de comunicação, OMNeT++ em C++
    ├── pade-opentes/        agentes, PADE 3.0 em Python
    ├── mosaik-opentes/      cenários e coletores do orquestrador
    ├── grid-opentes/        rede elétrica, OpenDSS via py-dss-interface
    └── market-opentes/      modelos de otimização do mercado, em Pyomo
```

### `comm-opentes`, a comunicação

C++ sobre OMNeT++, compilado dentro do container. Duas redes distintas convivem,
escolhidas pela configuração do `omnetpp.ini`:

- **`General`**, o padrão: uma nuvem de nó único, com perda plana e latência de
  milissegundos. É o que os cenários `integrated` e `star` usam.
- **`tisch`**: a rede LPWA 6TiSCH da tese, com erro de pacote em função da
  distância entre os agentes, matriz de adjacência e roteamento multi-salto. Não
  participa do passo do Mosaik; responde consultas de rota por ZMQ, porque a
  negociação inteira acontece dentro de um único passo, com o relógio da
  co-simulação parado.

### `pade-opentes`, os agentes

Contém uma cópia do PADE 3.0 e os agentes de cada cenário. O arquivo grande é
`agents/market_agents.py`: 33 agentes num processo só, com os quatro papéis da
tese (prosumidor, concentrador, DSO, mercado) conversando por protocolos FIPA.

`agents/network_link.py` é a camada de rede: substitui o envio de mensagens do
agente em tempo de execução, sem tocar no núcleo do PADE, e desvia cada mensagem
para um modelo de canal. Três backends: `ideal` (entrega tudo, na hora), `lossy`
(perda e atraso em Python) e `omnet` (cliente da rede 6TiSCH).

### `mosaik-opentes`, o orquestrador

Um arquivo por cenário em `scenarios/`, mais os coletores que gravam os
resultados. O cenário descreve quem fala com quem: qual atributo de qual
simulador alimenta qual entrada de qual outro.

### `grid-opentes`, a rede elétrica

Circuitos OpenDSS em `src/data/` (IEEE 13 Barras, IEEE 34, IEEE 123, a MVLV75 do
mercado, e as duas redes próprias BT16 e BT38) e os simuladores Mosaik que os
acionam. Quatro utilitários importam:

- `gen_market_grid.py` converte o grafo da tese (`force.json`) num circuito
  OpenDSS completo.
- `gen_test_grid.py` faz o contrário: PROJETA uma rede a partir de parâmetros e
  emite circuito, topologia, alocação de dispositivos e perfis. É de onde saem a
  BT16 e a BT38.
- `plot_grid.py` desenha o unifilar de uma rede a partir do `force.json` e do
  `config.json`.
- `sensitivity.py` obtém as matrizes `∂V/∂P` e `∂V/∂Q` por perturbação, o que
  substitui o Jacobiano que a tese extraía de um segundo simulador.

### `market-opentes`, a otimização

Os modelos matemáticos, em Pyomo, separados dos agentes de propósito: assim eles
rodam sozinhos, sem subir a co-simulação inteira, o que torna o desenvolvimento e
a validação viáveis.

| Módulo | O que faz |
|---|---|
| `config.py` | monta o caso a partir da rede e da alocação de dispositivos |
| `optimization.py` | os três modelos: prosumidor, concentrador, DSO |
| `dual.py` | a decomposição dual centralizada, para comparação |
| `operation.py` | a fase de operação |
| `settlement.py` | liquidação das transações e preço locacional |
| `loading.py` | verificação de carregamento térmico dos condutores |
| `plot_*.py` | as figuras |

## 4. Como rodar

Tudo pelo `run.sh`, que cuida da limpeza do Docker antes e depois e espera cada
simulador ficar pronto.

```bash
docker compose build      # uma vez
./run.sh --help           # lista os cenários
./run.sh integrated       # a co-simulação completa dos quatro domínios
./run.sh market           # o mercado transativo
```

**O cenário `market` exige o CPLEX**, que tem licença acadêmica pessoal e por
isso não está no repositório nem na imagem: ele é montado do host em tempo de
execução, pela variável `CPLEX_HOME`. Sem ele, dá para usar um solver livre
(`MARKET_SOLVER=ipopt`) ao custo de perder a parte inteira do modelo do
prosumidor. Os detalhes estão no `simulators/market-opentes/README.md`.

O `market` roda duas passadas, uma sem mecanismo nenhum e outra com a negociação,
e grava `result_baseline.csv` e `result_negociado.csv`. É a comparação entre as
duas que mede o efeito do mercado.

### Três redes

A rede vem de `MARKET_NETWORK`, e cada uma responde a uma pergunta diferente.

| Rede | Barras BT | Para quê |
|---|---|---|
| `MVLV75` | 75 | a da tese de referência; é onde a comparação é feita |
| `BT16` | 16 | bancada: 0,3 s por rodada, para iterar sobre o mecanismo |
| `BT38` | 38 | a rede final do trabalho, com quatro alimentadores |

```bash
MARKET_NETWORK=BT38 ./run.sh market      # -> output/market_BT38/
```

A MVLV75 não exibe sobretensão: alimentadores de 60 a 180 m e PV sobre carga de
0,37 dão cerca de 0,006 pu de elevação ao meio-dia, e a restrição superior nunca
fica ativa. A BT16 e a BT38 foram projetadas para que os DOIS extremos da faixa
ocorram, e sem forçar nada: a sobretensão vem da penetração fotovoltaica sobre
alimentador longo, que é o caso real que motiva o controle transativo. Na BT16 os
dois extremos ocorrem no mesmo alimentador, em horários diferentes. Na BT38
ocorrem em alimentadores diferentes e em horários diferentes: sobretensão no
condomínio solar ao meio-dia, subtensão na ponta rural e, à noite, nos
alimentadores residenciais. Isso vem da penetração desigual entre eles, e faz o
preço sombra variar entre alimentadores: ele assume os dois sinais no mesmo
intervalo em 52 de 96.

Os alimentadores das duas são ramificados, tronco em 70 mm² e ramais em 35 mm²,
e não cadeias de barras em linha. Detalhes e números medidos no `INTEGRACAO.md`,
item 12; o unifilar de cada uma sai do `plot_grid.py`.

### Chaves que mudam o resultado

Todas com valor padrão no `docker-compose.yaml`. As que mais importam:

| Variável | Padrão | O que muda |
|---|---|---|
| `MARKET_V_BACKOFF` | `2e-3` | margem na restrição de tensão, contra o erro da linearização |
| `MARKET_MAX_ROUNDS` | `60` | teto de rodadas; precisa acompanhar o backoff |
| `MARKET_SCENARIOS` | `1` | cenários por prosumidor; 1 é determinístico |
| `MARKET_REALIZED_MODE` | `perturb` | como a demanda realizada difere da programada |
| `MARKET_STORAGE_PF` | `none` | fator de potência do armazenamento; `none` reproduz a tese |
| `NET_BACKEND` | `ideal` | camada de rede entre os agentes |
| `MARKET_NETWORK` | `MVLV75` | qual rede de teste; ver a seção acima |

## 5. O que já foi medido

Os resultados principais, para saber o que esperar antes de rodar.

**A negociação resolve a violação de tensão.** No fluxo de potência não linear
completo, com a demanda realizada da tese, os pontos abaixo de 0,97 pu vão de 337
para zero, e a tensão mínima do dia sobe de 0,93946 para 0,97033 pu, com
convergência em 34 rodadas. O horário crítico é 17:45, o mesmo da tese.

**A camada de comunicação quebra suposições do protocolo.** O
`FipaContractNetProtocol` do PADE supõe entrega imediata: sem nenhuma perda de
pacote, apenas com atraso, o ciclo fechava com 19 das 25 programações. E o FIPA
não define retransmissão, o que numa rodada de 24 mensagens a 5% de perda dá 71%
de chance de perder ao menos uma.

**O conteúdo real das mensagens não cabe na rede da tese.** Com os tamanhos que
ela declara, a programação do dia seguinte gasta 3,7 h de tempo de rede. Com o
conteúdo serializado real, ela **não completa**: a mensagem de 35.663 bytes ocupa
281 quadros, e num enlace que a regra da tese admite isso dá 99,93% de perda de
datagrama, o que deixa um dos cinco concentradores incomunicável. Para trafegar
com confiabilidade, a chamada precisaria encolher para cerca de 500 bytes.

## 6. O que ler, e em que ordem

No repositório:

| Documento | Para quê |
|---|---|
| `README.md` | instalar e rodar |
| `GUIA.md` | este, o mapa geral |
| `INTEGRACAO.md` | o que foi mudado em cada componente para integrá-los, e por quê |
| `RESULTADOS.md` | o que há em `output/` e como se lê |
| `MERCADO.md` | a formulação do mercado, equação por equação, e os desvios |

Fora do repositório, em `Docs_Externo/`, ficam os documentos de pesquisa que não
descrevem o código: o confronto com a tese de referência (`COMPARACAO_TESE.md`),
a cobertura do
capítulo 6 (`REVISAO_TESE.md`), o registro cronológico com o porquê de cada
decisão (`DIARIO_MERCADO_2026-08.md`), o experimento de perda de pacotes e a
apresentação.

Para entender **o código**, comece pelo `INTEGRACAO.md`. Para **o modelo
matemático**, o `MERCADO.md`. Para **a fidelidade à tese**, o
`Docs_Externo/COMPARACAO_TESE.md`.

## 7. Onde estão as armadilhas

Coisas que já custaram tempo e estão documentadas para não custarem de novo.

- **O `py-dss-interface` troca o diretório de trabalho do processo** ao instanciar
  e ao compilar um circuito. Sem salvar e restaurar, tudo que resolve caminho
  relativo depois passa a apontar para dentro do circuito.
- **O `py-dss-interface` não é seguro para uso concorrente.** Chamá-lo de dentro
  do pool de threads do Twisted derruba o processo com `std::bad_alloc`.
- **Um socket ZMQ do tipo REQ também não é.** Duas threads no mesmo socket o
  deixam num estado de que ele não sai sozinho.
- **O relógio do OMNeT++ estoura em 106 dias** na resolução padrão de
  picossegundos. A configuração `tisch` acumula o atraso de todas as mensagens no
  mesmo relógio e precisa de nanossegundos.
- **Sem AMS, o `Agent._send` do PADE descarta mensagens em silêncio** se o
  destinatário não estiver na tabela de agentes.
- **`api_opendss.py` tem quebras de linha CRLF.** Editá-lo com ferramentas que
  normalizam para LF produz um diff do arquivo inteiro.
- **Figuras e resultados podem ficar velhos sem erro nenhum.** Já aconteceu de
  uma figura ler um arquivo que os agentes tinham deixado de escrever, e seguir
  desenhando dados antigos em silêncio. Ao mudar o que se grava, confira quem lê.
