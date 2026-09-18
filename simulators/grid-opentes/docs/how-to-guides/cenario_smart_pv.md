# Cenário smart inverter

Neste guia, abordo a forma de se trabalhar em um cenário o qual envolve um sistema fotovoltaico em que o inversor performa as funções de controle do padrão IEEE 1547.

## Instânciando o inversor

O construtor para o inversor inteligente é apresentado no código abaixo:

```py title="Construtor InverterModel"
InverterModel(
    kVA,
    eff_curve_x,
    eff_curve_y,
    ctrl_config=None,
    phase_mode='AVG'):
```

Em que:

* **kVA**: potência aparente do inversor
* **eff_curve_x**: pontos do eixo X da curva de eficiência
* **eff_curve_y**: pontos do eixo Y da curva de eficiência
* **ctrl_config**: Tipo de controle do inversor (default | volt-var | volt-watt)
* **phase_mode**: Parametro que indica se o inversor receve a leitura de tensão de cada fase independemente ou uma média das três fases

Os três primeiros parâmetros são intuitivos de compreender. O parâmetro `ctrl_config` irá indicar qual função de controle ele irá operar, a saber:

* **default** ( `ctrl_config = CONST_PF` ) indica o funcionamento padrão com fator de potência fixo
* **volt-var** (`ctrl_config = Volt_Var`) e **volt-watt** (`ctrl_config = Volt_Watt`) indicam os devidos modo de operação que constam no padrão IEEE 1547. O parâmetro `phase_mode` será melhor abordado nos no futuro deste mesmo guia.

## PVSystem declarado trifásico

Quando no OpenDSS é declarado um elemento `PVSystem` de modo trifásico, a saída de potência de em seus terminais são iguais para cada uma das três fases, não sendo possível controlar de maneira independente a saída de cada fase.

Portanto uma observação ao ser instanciando um elemento PVSystem (conjunto painel e inversor) é o parâmetro `phase_mode = AVG`. Desta forma a referência de tensão que é necessário para a operação deste elemento será a média das três fases.

## PVSystem declarado como um conjunto de equipamentos monofásicos

Quando no OpenDSS é declarado 3 elementos `PVSystem` monofásicos, com conexões adequadas para que este conjunto seja equivalente a um elemento trifásico, criamos então uma abstração que performa um elemento `PVSystem` o qual possui output de suas fases independentes. Nesce caso informamos o parâmetro `phase_mode = INDEP`, a respectiva tensão de cada fase irá influência na potência de saída da mesma.

## Observações

Se em comparação ao primeiro simulador de inversor, este ainda não possui a implementação de alguns comportamentos, como por exemplo *cut-in* *cut-out*. Estou estudano e verificando se consigo obter este comportanto por meio do elemento da biblioteca `OpenDER`.
