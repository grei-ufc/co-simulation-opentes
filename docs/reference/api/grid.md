# Rede elétrica (`tsre-der-opentes`)

Os módulos do simulador da rede elétrica, em `teams/tsre-der-opentes/src/`. O
papel de cada um está em [Arquitetura](../../explanation/architecture.md).

## O caso de mercado

::: simulators.gen_ieee13_market

## Matrizes de sensibilidade

::: simulators.sensitivity

## O circuito exposto ao Mosaik

O adaptador é o da equipe TSRE, usado direto do submódulo
`teams/tsre-der-opentes` (pacote `simulators.opendss`), sem cópia. A referência
dele é a que o próprio TSRE publica:
[API do adaptador OpenDSS](https://grei-ufc.github.io/tsre-der-opentes/reference/api/opendss/)
e [Adaptadores Mosaik](https://grei-ufc.github.io/tsre-der-opentes/reference/mosaik-adapters/).
