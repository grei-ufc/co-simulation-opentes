# Arquivos de saída

Cada execução grava em `output/<pasta>/`: `market` (por fase), `market_por_no`
(`MARKET_FASE=0`) ou a pasta de `OPENTES_SAIDA`
([CLI](cli.md#pasta-de-resultados)). A pasta `output/` fica fora do git.

| Arquivo | Comando | Conteúdo |
|---|---|---|
| `result_baseline.csv`, `result_negociado.csv` | `market` | tensão de cada fase de cada barra e potência de cada barra e porta, a cada 15 min |
| `run.json` | `market` | configuração da execução, histórico da negociação distribuída, registro de cada janela da operação, tempo de rede por ciclo e retransmissões |
| `msg_trace.csv` | `market` com `omnet` | cada mensagem: remetente, destino, tamanho, atraso, perda |
| `figuras.npz`, `history.json` | `centralizado` | tensões, programações, λ e a trilha de cada rodada |
| `dlmp.csv`, `flexibility.csv` | `centralizado` | preço locacional por porta e intervalo, e quanto cada porta deslocou |
| `transactions.csv`, `market_series.csv` | `centralizado` | energia e custo nos mercados bilateral e spot, no dia e por intervalo |
| `figuras/` | `figuras` | as figuras ([Gerar as figuras](../how-to-guides/generate-figures.md#os-arquivos)) |

Fora das pastas de resultado, `output/console/` guarda a saída completa de cada
execução feita pelo console.

## Colunas

| Arquivo | Colunas |
|---|---|
| `transactions.csv` | `node`, `market`, `energy_kwh`, `price_eur_mwh`, `cost_eur` |
| `market_series.csv` | `node`, `t`, `bilateral_kw`, `spot_kw`, `spot_eur_mwh`, `bilateral_eur_mwh` |
| `dlmp.csv` | `node`, `fase`, `t`, `dlmp_signal`, `spot_eur_mwh`, `adder_signal` |
| `flexibility.csv` | `node`, `fase`, `energy_shifted_kwh`, `net_shift_kwh`, `value_signal`, `dlmp_mean_signal`, `dlmp_max_signal` |
| `history.json` | uma entrada por rodada: `round`, `d_lambda_max`, `residual_max`, `residual_rms`, `residual_rel_max`, `lambda_max`, `v_min`, `v_max`, `violations`, `seconds` |

A coluna `fase` só existe na análise por fase, em que as chaves do armazenamento
são as portas (`671.A`). As colunas de preço saem com o sufixo `_signal`
enquanto `MARKET_CK_EUR` não for calibrado, porque o preço sombra não está em
unidade monetária ([O modelo de mercado](../explanation/market-model.md)).
