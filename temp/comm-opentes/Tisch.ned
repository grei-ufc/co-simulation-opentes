//
// Rede LPWA 6TiSCH (modelo de Melo, 2022, secao 6.1.5), como servidor de rotas.
//
// Modelo multi-salto com PER por distancia, que responde consultas de rota
// vindas dos agentes PADE em vez de participar do passo do Mosaik.
//
simple TischServer
{
    parameters:
        // Porta ZMQ das consultas de rota.
        int port = default(5556);
        string positions_file = default("nodes_xy.csv");
        // Matriz de adjacencia publicada, se houver. Vazia = gerar pelo limiar
        // de PER, o que exige supor o orcamento de enlace do radio.
        string adjacency_file = default("adjacency.txt");

        // --- Radio: IEEE 802.15.4g modo 1, banda ISM dos EUA ---------------
        double frequency_hz = default(915e6);
        double tx_power_dbm = default(0.0);
        double tx_gain_db = default(0.0);
        double rx_gain_db = default(0.0);
        // Pister-Hack: o RSSI de espaco livre menos uma uniforme de 0 a 40 dB.
        // Sorteada UMA vez por enlace, porque o modelo descreve a variacao de
        // longo prazo do ambiente de propagacao, nao o desvanecimento por pacote.
        double pister_hack_shift_db = default(40.0);
        double sensitivity_dbm = default(-106.37);

        // --- TSCH ----------------------------------------------------------
        // 101 timeslots, 4,04 s por slotframe. Um cell dedicado por enlace por
        // slotframe e o padrao minimo do 6TiSCH.
        double slotframe_s = default(4.04);
        // Cells alocados por enlace por slotframe. A referencia NAO informa este
        // valor, e ele e o que mais mexe no tempo de entrega. O padrao e
        // CALIBRADO: com 2 cells, os tempos de entrega ficam na faixa de 10 a
        // 90 s reportada na referencia. Com 1 cell, que e a configuracao minima
        // do 6TiSCH, eles dobram. E uma calibracao, e nao uma previsao do modelo.
        int cells_per_slotframe = default(2);
        // Frame maximo do IEEE 802.15.4, como na referencia; uma pilha real
        // gasta parte disso em cabecalho 802.15.4, 6LoWPAN e UDP, e sobram cerca
        // de 80 bytes uteis, o que aumenta os tempos em cerca de 60%.
        int frame_bytes = default(127);
        // macMaxFrameRetries do IEEE 802.15.4.
        int max_retries = default(3);

        // --- MAC: "tsch" (6TiSCH, a rede da referencia) ou "wisun" (Wi-SUN FAN) --
        // Os dois usam o mesmo radio, o mesmo modelo de propagacao e a mesma
        // topologia gerada pelo limiar de PER; muda o acesso ao meio.
        string mac = default("tsch");

        // --- Wi-SUN FAN: so valem com mac = "wisun" --------------------------
        // Taxa da camada fisica. 50 kbps e o modo 1 do 802.15.4g, o mesmo da
        // referencia; 150 kbps e o modo FSK 3; 300 kbps, o modo FSK 5 do Wi-SUN.
        // A sensibilidade sobe 10 log10(R / 50 kbps) dB, o que encurta o alcance.
        double phy_rate_bps = default(50000);
        // Carga do quadro. O SUN PHY aceita PSDU de ate 2047 bytes; 1280 e o MTU
        // minimo do IPv6, que cabe inteiro em um quadro, sem fragmentar.
        int wisun_frame_bytes = default(1280);
        // CSMA/CA nao sincronizado do IEEE 802.15.4 (macMinBE, macMaxBE). A
        // unidade de recuo e a reversao mais o CCA: cerca de 1,16 ms no SUN FSK.
        int min_be = default(3);
        int max_be = default(5);
        double unit_backoff_s = default(0.00116);
        // Tempo de reversao entre transmitir e receber (aTurnaroundTime do SUN).
        double turnaround_s = default(0.001);
        // Preambulo (8), SFD (2) e cabecalho fisico (2) de cada quadro SUN FSK.
        int shr_phr_bytes = default(12);
        // ACK estendido com os elementos de informacao do Wi-SUN.
        int ack_bytes = default(30);

        // Agentes na mesma coordenada trocam mensagens por cabo, sem radio.
        // Desligado, o par paga o escalonamento TSCH como qualquer enlace.
        bool colocated_wired = default(false);

        // Um enlace so existe se o PER estiver abaixo deste valor.
        double link_per_threshold = default(0.5);

        // Grava o levantamento dos enlaces para a figura de PER por distancia.
        string links_csv = default("tisch_links.csv");

        @display("i=block/network2");
}

network TischNetwork
{
    submodules:
        tisch: TischServer {
            @display("p=50,50");
        }
}
