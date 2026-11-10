# Problemas comuns

## `!! CPLEX nao encontrado`

O `run.sh` não achou `$CPLEX_HOME/bin/x86-64_linux/cplex`. Defina a variável
apontando para a pasta `cplex` da instalação (a que contém `bin/`):

```bash
export CPLEX_HOME=$HOME/IBM/CPLEX_Studio2211/cplex
```

No console, use `c` e o item "Caminho do CPLEX"; ele fica guardado em
`.opentes.env`.

## `!! timeout aguardando os agentes PADE` (ou o coletor, ou o servidor 6TiSCH)

O `run.sh` espera cada contêiner anunciar no log que está pronto: 120 s para os
agentes, 60 s para o coletor e 900 s para o servidor de rede, que compila o
OMNeT++ na primeira vez. Se o tempo estourar:

1. veja o log do serviço: `docker compose logs pade` (ou `collector`, `comm`);
2. derrube o que sobrou de uma execução anterior: tecla `x` no console, ou
   `docker compose down --remove-orphans`;
3. se mudou um Dockerfile ou dependência, reconstrua: `docker compose build`.

## O grid ou o coletor morrem logo depois de subir

Os simuladores `--remote` (`grid` e `collector`) aceitam **uma única** conexão
mosaik e encerram depois dela. Um teste de prontidão por TCP, um `nc` ou um
`curl` na porta consome essa conexão e mata o simulador. Não sonde as portas: o
`run.sh` detecta a prontidão pelo log e sobe contêineres novos a cada passada.

## Segfault do OpenDSS no contêiner

A engine do OpenDSS da imagem falha se o contêiner não rodar como root. Não use
`--user` no `docker compose run`. O `run.sh` roda como root e devolve a posse dos
arquivos de `output/` a quem o chamou, ao final.

## A negociação com a 6TiSCH parece parada

Sem `NET_TIME_SCALE=0.02`, cada rodada espera em relógio real todo o atraso da
rede, que passa de 500 s no ciclo 3. Com `0.02`, a co-simulação inteira leva
de 17 a 18 minutos com 2 fatias por enlace.

## Wi-SUN a 300 kbps não fecha

É o resultado esperado na IEEE 13: com a sensibilidade menor, a ligação da
subestação ao resto do alimentador depende de enlaces com erro alto, as
mensagens grandes não atravessam e o concentrador esgota as retentativas. Use 50
ou 150 kbps ([Resultados](../results.md#comparacao-de-redes-6tisch-com-mais-fatias-e-wi-sun-fan)).

## Figuras faltando

Cada figura é pulada quando falta o arquivo de que depende, com a mensagem
`sem <arquivo>; pulando ...`. Rode `centralizado` e `market` na mesma
configuração antes de `figuras`
([Gerar as figuras](generate-figures.md#de-qual-execucao)).

## Resultados de configurações diferentes misturados

Pela linha de comando, sem `OPENTES_SAIDA`, toda execução por fase grava em
`output/market/`. O `run.json` registra a configuração com que foi gerado
(`config`), o que permite conferir de onde veio cada arquivo. Pelo console, cada
configuração já tem a sua pasta.
