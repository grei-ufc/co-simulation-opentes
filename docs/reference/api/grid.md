# Rede elétrica (`grid-opentes`)

Os módulos do simulador da rede elétrica, em `simulators/grid-opentes/src/`. O
papel de cada um está em [Arquitetura](../../explanation/architecture.md).

## O caso de mercado

::: simulators.gen_ieee13_market

## Matrizes de sensibilidade

::: simulators.sensitivity

## O circuito exposto ao Mosaik

O adaptador é o da equipe TSRE, copiado sem alteração do
[tsre-der-opentes](https://github.com/grei-ufc/tsre-der-opentes); a referência
completa dele está na documentação daquele repositório.

::: simulators.opendss.api_opendss
