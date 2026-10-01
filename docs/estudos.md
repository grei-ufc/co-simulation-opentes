--8<-- "estudos/ieee13/README.md"

!!! info "Por que a pasta `estudos/` existe"

    São scripts curtos, fora do caminho de execução, que respondem a uma
    pergunta de projeto cada um e imprimem o número que a resposta usa. Eles
    existem para que uma decisão registrada na documentação possa ser refeita
    sem reconstruir o raciocínio.

## As decisões que esses scripts sustentam

O caso de mercado sobre o IEEE 13 foi montado a partir de medições sobre o
próprio circuito, e não de regra de bolso. Em resumo:

=== "O regulador"

    O `run_ieee13_cosim_pv_5min.dss` trava as derivações com
    `Batchedit RegControl..* maxtapchange=0`. Isso faz sentido no cenário
    Volt/Var, onde o objetivo é que o inversor seja o único ator. Para um estudo
    de alocação de armazenamento não serve: as derivações ficam onde a
    inicialização as deixou e a rede passa a violar por causa do regulador. O
    caso de mercado usa o **ajuste oficial com derivações livres**.

=== "O armazenamento"

    Para cada um dos 96 intervalos resolveu-se, com a matriz de sensibilidade do
    próprio caso, a menor injeção total que mantém todas as barras dentro da
    faixa. A necessidade medida soma **4.226 kW e 6,3 MWh**, concentrada nas
    barras onde o fotovoltaico excede a carga local com folga. A alocação
    adotada é **5.350 kW em 14 bancos**, 1,27 vez essa necessidade, com
    capacidade de 3,3 vezes a potência e estado de carga entre 10% e 90%.

    | limite por nó | folga residual |
    |---|---|
    | 200 kW | 15,00 mpu |
    | 400 kW | 6,12 mpu |
    | **600 kW** | **0, factível** |

=== "O concentrador"

    Um só, porque o alimentador tem um transformador só. Na MVLV75 são cinco, um
    por transformador. Os terminais da subestação (650 e `rg60`) ficam fora da
    restrição do operador.

=== "A topologia de rádio"

    As posições dos nós saem do circuito e vão em `nodes_xy.csv`. Os enlaces que
    valem são os que o servidor 6TiSCH sorteia e grava em `tisch_links.csv`
    durante a execução: **18 posições e 74 enlaces viáveis**. O gerador já teve
    uma estimativa própria de enlaces, que divergia da simulada e foi retirada,
    porque um segundo sorteio da mesma grandeza só cria a chance de os dois
    números discordarem na documentação.

!!! tip "Contexto para julgar o porte do armazenamento"

    O alimentador tem 3.390 kW de pico de carga e 4.030 kW de pico de geração,
    com o PV1 sozinho pondo 5 MW de placa numa derivação bifásica cuja carga é
    230 kW. O armazenamento está dimensionado contra a geração, e não contra a
    carga, e é isso que explica o número.

O estudo completo, com as execuções por trás de cada número, fica fora do
repositório, em `Docs_Externo/ESTUDO_IEEE13.md`.
