# Usando o console

O console é a forma do dia a dia de operar a plataforma: mostra se o ambiente
está pronto, guarda a configuração entre sessões e acompanha cada execução. Ele
só chama o `run.sh`, então tudo o que faz também funciona por linha de comando
([CLI](../reference/cli.md)).

## Abrir

```bash
./run.sh          # ou: opentes, com o link da Instalação
```

A tela inicial mostra o logo, o estado do ambiente (Docker, imagens, CPLEX e as
matrizes do caso), a configuração atual e o menu.

## O menu

| Tecla | O que faz |
|---|---|
| `1` | co-simulação completa: agentes, rede elétrica e operação |
| `2` | negociação centralizada, sem agentes, com liquidação |
| `3` | figuras, a partir dos resultados |
| `4` | fluxo completo: 2, depois 1, depois 3 |
| `5` | regenerar o caso IEEE 13 e as matrizes |
| `c` | configurar (abaixo) |
| `r` | refazer o último comando |
| `s` | resumo dos resultados da configuração atual |
| `l` | log da última execução |
| `f` | abrir a pasta das figuras |
| `d` | documentação (abre este site) |
| `b` | construir as imagens (`docker compose build`) |
| `x` | reiniciar o ambiente: derruba contêineres presos |
| `h` | atalhos de linha de comando |
| `q` | sair |

Durante uma execução, a tela mostra a etapa, a rodada da negociação com o
desacordo relativo e, na operação, a hora do dia. A saída completa vai para
`output/console/`. Ctrl+C interrompe e limpa os contêineres.

## Configurar

A tecla `c` abre a configuração:

| Item | Opções |
|---|---|
| Formulação | por fase (padrão) ou por barra |
| Inversor | quatro fios (padrão) ou três fios; só na análise por fase |
| Regulador | derivações pela previsão (padrão) ou neutro |
| Rede entre agentes | ideal; 6TiSCH com 1 a 20 fatias por enlace; Wi-SUN FAN a 50, 150 ou 300 kbps; com perda, em % por mensagem |
| Critério de parada | relativo (padrão) ou absoluto |
| Tolerância | `ε_rel` do critério relativo ou `ε` do absoluto |
| Cenários do prosumidor | 1 (determinístico) ou 3 |
| Caminho do CPLEX | a pasta que contém `bin/` |

`p` restaura os padrões. Cada item corresponde a uma variável de ambiente
([Variáveis de ambiente](../reference/environment-variables.md)).

A configuração fica em `.opentes.env`, fora do git, e vale para a próxima
sessão.

## Uma pasta por configuração

Cada configuração grava numa pasta própria de `output/`, para uma execução não
apagar a outra. O nome é montado assim:

| Parte | Quando |
|---|---|
| `market` | análise por fase |
| `market_por_no` | análise por barra |
| `_equilibrado` | inversor de três fios |
| `_omnet` | rede 6TiSCH, com `_c5`, `_c20`... quando não usa 2 fatias |
| `_wisun_50k` | rede Wi-SUN FAN, com a taxa |
| `_perda` | canal com perda |

Por exemplo, por fase com Wi-SUN a 50 kbps grava em `output/market_wisun_50k/`.
Fora do console, a variável `OPENTES_SAIDA` escolhe a pasta.

## Um estudo pelo console

1. `c`, depois `4` (Rede entre agentes), escolha `2` (6TiSCH) e mantenha 2
   fatias; `v` para voltar.
2. `4` (Fluxo completo). Com a 6TiSCH, a co-simulação leva de 17 a 18 minutos.
3. `s` para o resumo e `f` para as figuras, em `output/market_omnet/figuras/`.
