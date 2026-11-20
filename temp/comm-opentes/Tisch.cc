/**
 * @file Tisch.cc
 * @brief Rede LPWA 6TiSCH multi-salto, como servidor de rotas para os agentes.
 *
 * O MODELO
 * --------
 * O modelo de rede de Melo (2022, secao 6.1.5): IEEE 802.15.4g modo 1 na banda
 * ISM dos EUA, 50 kbps, 16 canais, TSCH com salto de canal. Slotframe de 101
 * timeslots executado em 4,04 s. RSSI pelo modelo de Friis menos uma uniforme de
 * 0 a 40 dB (Pister-Hack, LE et al. 2009), que e a abordagem do Simulador 6TiSCH
 * (MUNICIO et al., 2019). Conversao de RSSI para PER pela curva de Prando et al.
 * (2019, Fig. 3), com nivel de sensibilidade de -106,37 dBm. Enlace viavel
 * sempre que o PER ficar abaixo de 0,5. As posicoes dos agentes vem do
 * `nodes_xy.csv` do caso.
 *
 * A MATRIZ DE ADJACENCIA
 * ----------------------
 * Pode ser lida de um arquivo (`adjacency_file`), quando a topologia e dado
 * publicado, ou gerada pelo limiar de PER, como no caso IEEE 13, que nao tem
 * topologia de radio publicada. Gerar pelo limiar exige supor o orcamento de
 * enlace do radio (0 dBm aqui), e a suposicao pesa: uma rede mais conectada tem
 * menos saltos e menos perda, ou seja, resultados de comunicacao otimistas.
 *
 * O CAMINHO SALTO A SALTO
 * -----------------------
 * O caminho e percorrido salto a salto em tempo de evento do OMNeT++, entao o
 * atraso sai da propria simulacao e nao de uma tabela pre-calculada. O numero
 * de frames vem do tamanho da mensagem FIPA que o agente informa.
 *
 * DOIS MACS SOBRE O MESMO RADIO
 * ------------------------------
 * `mac = "tsch"` e a rede da referencia: TSCH, um quadro de 127 bytes por cell
 * alocado ao enlace, `cells_per_slotframe` cells por slotframe de 4,04 s.
 *
 * `mac = "wisun"` e o Wi-SUN FAN (IEEE 802.15.4g com salto de canal
 * assincrono): o mesmo radio e o mesmo modelo de propagacao, mas o acesso ao
 * meio e por CSMA/CA, sem fatia reservada. O remetente transmite no canal em
 * que o receptor esta ouvindo, quando quiser, e o quadro pode ter ate 2047
 * bytes (PSDU do SUN PHY). O atraso por quadro e recuo aleatorio + tempo no ar
 * + reversao + ACK + espacamento. A sensibilidade piora com a taxa na
 * proporcao do ruido termico, 10 log10(R / 50 kbps), o que encurta o alcance e
 * muda a topologia. Nenhum dos dois modelos tem disputa entre enlaces: cada
 * mensagem e calculada sozinha, o que e otimista nos dois.
 *
 * POR QUE UM SERVIDOR DE ROTAS E NAO UM PASSO DO MOSAIK
 * ---------------------------------------------------
 * A negociacao inteira acontece DENTRO de um passo de 15 min do Mosaik, com o
 * relogio da co-simulacao parado. Nao ha passo do Mosaik onde encaixar as
 * mensagens. Os agentes consultam este servidor por ZMQ a cada envio e recebem
 * atraso e descarte daquele par origem-destino.
 */

#include <omnetpp.h>
#include <zmq.hpp>
#include <nlohmann/json.hpp>

#include <algorithm>
#include <cmath>
#include <fstream>
#include <limits>
#include <queue>
#include <sstream>
#include <string>
#include <vector>

using namespace omnetpp;
using json = nlohmann::json;

namespace {

// PER em funcao do RSSI acima do nivel de sensibilidade, em passos de 1 dB
// (Prando et al., 2019). O indice 0 e o proprio nivel de sensibilidade.
const double PER_TABLE[] = {1.0, 0.8, 0.4, 0.15, 0.03, 0.006, 0.0015, 0.0};
const int PER_TABLE_LEN = 8;

const double SPEED_OF_LIGHT = 299792458.0;

}  // namespace

class TischServer : public cSimpleModule {
  private:
    zmq::context_t context{1};
    zmq::socket_t socket{context, zmq::socket_type::rep};

    std::vector<std::string> names;
    std::vector<double> xs, ys;
    std::map<std::string, int> indexOf;

    std::vector<std::vector<double>> per;      // PER por enlace, ja com Pister-Hack
    std::vector<std::vector<bool>> adjacent;   // PER < limiar
    std::vector<std::vector<bool>> colocated;  // mesma coordenada (distancia zero)
    std::vector<std::vector<int>> nextHop;     // roteamento por menor custo ETX
    int routedFrames = -1;                     // tamanho para o qual nextHop vale

    // Pacote em transito.
    struct InFlight {
        std::vector<int> path;
        size_t hop = 0;
        int frames = 0;
        bool dropped = false;
        double nominalDelay = 0.0;
        simtime_t start;
    };
    InFlight flight;
    cMessage *hopMsg = nullptr;

    double slotframe, sensitivity, txPower, txGain, rxGain, frequency, shiftDb, threshold;
    int frameBytes, maxRetries, cells;
    bool colocatedWired;
    // Wi-SUN FAN
    bool wisun = false;
    double phyRate, unitBackoff, turnaround, lifs;
    int minBE, maxBE, shrPhrBytes, ackBytes;
    double perQuadro(int i, int j) const;   // PER do quadro do MAC em uso
    double wisunHopDelay(int i, int j, int frames, bool& lost);

    void loadPositions(const std::string& path);
    bool loadAdjacency(const std::string& path);
    void buildLinks(const std::string& csvPath);
    void buildRoutes(int frames);
    double perFromRssi(double rssi) const;
    std::vector<int> route(int src, int dst, int frames);
    void serve();                       // recebe e trata pedidos ate um virar pacote
    void startPacket(const json& j);
    double hopDelay(int i, int j, int frames, bool& lost);
    void replyDone();

  protected:
    virtual void initialize() override;
    virtual void handleMessage(cMessage *msg) override;
    virtual void finish() override;
};

Define_Module(TischServer);

// ---------------------------------------------------------------------------
// Montagem do modelo
// ---------------------------------------------------------------------------

void TischServer::loadPositions(const std::string& path) {
    std::ifstream f(path);
    if (!f) throw cRuntimeError("nao consegui abrir %s", path.c_str());
    std::string line;
    std::getline(f, line);                       // cabecalho
    while (std::getline(f, line)) {
        if (line.empty()) continue;
        std::stringstream ss(line);
        std::string name, sx, sy;
        std::getline(ss, name, ',');
        std::getline(ss, sx, ',');
        std::getline(ss, sy, ',');
        indexOf[name] = names.size();
        names.push_back(name);
        xs.push_back(std::stod(sx));
        ys.push_back(std::stod(sy));
    }
    EV << "[6TiSCH] " << names.size() << " posicoes carregadas de " << path << "\n";
}

double TischServer::perFromRssi(double rssi) const {
    // Abaixo da sensibilidade nao ha recepcao; acima de sensibilidade+7 dB a
    // tabela ja chegou a zero.
    int step = (int)std::floor(rssi - sensitivity);
    if (step < 0) return 1.0;
    if (step >= PER_TABLE_LEN) return 0.0;
    return PER_TABLE[step];
}

bool TischServer::loadAdjacency(const std::string& path) {
    if (path.empty()) return false;
    std::ifstream f(path);
    if (!f) return false;

    size_t n = names.size();
    adjacent.assign(n, std::vector<bool>(n, false));
    size_t i = 0;
    std::string line;
    while (std::getline(f, line) && i < n) {
        if (line.find_first_not_of(" \t\r\n") == std::string::npos) continue;
        std::stringstream ss(line);
        int v;
        size_t j = 0;
        while (ss >> v && j < n) {
            adjacent[i][j] = (v != 0);
            j++;
        }
        if (j != n)
            throw cRuntimeError("matriz de adjacencia com %zu colunas na linha %zu, "
                                "esperava %zu", j, i, n);
        i++;
    }
    if (i != n)
        throw cRuntimeError("matriz de adjacencia com %zu linhas, esperava %zu", i, n);
    EV << "[6TiSCH] adjacencia lida de " << path << "\n";
    return true;
}

void TischServer::buildLinks(const std::string& csvPath) {
    size_t n = names.size();
    per.assign(n, std::vector<double>(n, 1.0));
    colocated.assign(n, std::vector<bool>(n, false));

    // Uma matriz de adjacencia publicada, quando informada, e usada como esta,
    // em vez de ser reconstruida: reconstruir exige supor o orcamento de enlace
    // do radio, o que pode tornar a rede mais densa que a real e os resultados
    // de comunicacao otimistas.
    bool doArquivo = loadAdjacency(par("adjacency_file").stdstringValue());
    if (!doArquivo) adjacent.assign(n, std::vector<bool>(n, false));

    std::ofstream out;
    if (!csvPath.empty()) {
        out.open(csvPath);
        out << "i,j,name_i,name_j,distance_m,rssi_dbm,per,adjacent\n";
    }

    int links = 0, forcados = 0;
    for (size_t i = 0; i < n; ++i) {
        for (size_t j = i + 1; j < n; ++j) {
            double d = std::hypot(xs[i] - xs[j], ys[i] - ys[j]);
            double p, rssi;
            if (d < 1e-9) {
                // Mesmo ponto: o AM e o AD dividem a coordenada da subestacao.
                // Enlace perfeito, sem radio no meio.
                rssi = 0.0;
                p = 0.0;
                colocated[i][j] = colocated[j][i] = true;
            } else {
                // Friis em dB, com o termo de espaco livre invertido, como no
                // Simulador 6TiSCH.
                double fspl = 20.0 * std::log10(SPEED_OF_LIGHT / (4.0 * M_PI * d * frequency));
                double pr = txPower + txGain + rxGain + fspl;
                // Pister-Hack: subtrai uma uniforme de 0 a `shiftDb`. Sorteada
                // uma vez por enlace: e variacao de longo prazo do ambiente,
                // nao desvanecimento por pacote.
                //
                // Com a adjacencia vinda de arquivo, o sorteio de um enlace que
                // EXISTE e condicionado a PER < limiar, que e a distribuicao
                // implicada por ele existir. Sem isso, um enlace publicado como
                // viavel poderia receber PER 1,0 e virar rota morta.
                int tentativas = 0;
                do {
                    rssi = pr - uniform(0.0, shiftDb);
                    p = perFromRssi(rssi);
                } while (doArquivo && adjacent[i][j] && p >= threshold
                         && ++tentativas < 200);
                if (doArquivo && adjacent[i][j] && p >= threshold) {
                    // A distancia e grande demais para o modelo admitir o enlace
                    // publicado. Fica com o melhor PER possivel, e o aviso sai.
                    p = PER_TABLE[PER_TABLE_LEN - 2];
                    forcados++;
                }
            }
            per[i][j] = per[j][i] = p;
            bool ok = doArquivo ? adjacent[i][j] : (p < threshold);
            adjacent[i][j] = adjacent[j][i] = ok;
            if (ok) links++;
            if (out.is_open())
                out << i << "," << j << "," << names[i] << "," << names[j] << ","
                    << d << "," << rssi << "," << p << "," << (ok ? 1 : 0) << "\n";
        }
    }
    std::printf("[6TiSCH] %d enlaces viaveis (%s)%s\n", links,
                doArquivo ? "matriz de adjacencia do arquivo" : "PER abaixo do limiar",
                forcados ? " com enlaces alem do alcance do modelo" : "");
    if (forcados)
        std::printf("[6TiSCH] AVISO: %d enlaces publicados excedem o alcance que o "
                    "modelo de propagacao admite; PER fixado no melhor valor.\n",
                    forcados);
    std::fflush(stdout);
}

void TischServer::buildRoutes(int frames) {
    // Dijkstra por origem, com custo em numero esperado de transmissoes ate o
    // destino, que e o que gasta cell de TSCH. Minimizar saltos escolheria
    // enlaces longos e ruins.
    //
    // O custo depende do TAMANHO da mensagem, e ignorar isso e um erro grave. O
    // ETX classico, 1/(1-PER), vale para UM quadro. Um enlace admitido com PER
    // 0,4 perde 2,56% dos quadros mesmo apos as retentativas do MAC, o que e
    // tolеravel para uma mensagem de um quadro e fatal para uma de 281: a perda
    // do datagrama vai a 99,93%, porque perder qualquer fragmento perde o todo.
    // Roteando por quadro, o servidor escolhia caminhos incapazes de entregar a
    // mensagem que ele estava roteando.
    if (frames == routedFrames) return;        // rota ja montada para este tamanho
    routedFrames = frames;

    size_t n = names.size();
    nextHop.assign(n, std::vector<int>(n, -1));
    const double INF = std::numeric_limits<double>::infinity();

    for (size_t src = 0; src < n; ++src) {
        std::vector<double> dist(n, INF);
        std::vector<int> prev(n, -1);
        std::priority_queue<std::pair<double, int>,
                            std::vector<std::pair<double, int>>,
                            std::greater<>> pq;
        dist[src] = 0.0;
        pq.push({0.0, (int)src});
        while (!pq.empty()) {
            auto [d, u] = pq.top();
            pq.pop();
            if (d > dist[u] + 1e-12) continue;
            for (size_t v = 0; v < n; ++v) {
                if (!adjacent[u][v]) continue;
                // Perda do datagrama neste enlace, ja com as retentativas do MAC,
                // e custo esperado de transmissoes para entrega-lo.
                double pQuadro = std::pow(perQuadro(u, v), maxRetries + 1);
                double pDatagrama = 1.0 - std::pow(1.0 - pQuadro, frames);
                double etx = frames / std::max(1e-9, 1.0 - pDatagrama);
                if (dist[u] + etx < dist[v] - 1e-12) {
                    dist[v] = dist[u] + etx;
                    prev[v] = u;
                    pq.push({dist[v], (int)v});
                }
            }
        }
        for (size_t dst = 0; dst < n; ++dst)
            nextHop[src][dst] = (dist[dst] < INF) ? prev[dst] : -1;
    }
}

std::vector<int> TischServer::route(int src, int dst, int frames) {
    buildRoutes(frames);
    std::vector<int> path;
    if (src == dst) return {src};
    // `nextHop[src]` guarda o predecessor na arvore de menor custo com raiz em
    // src, entao o caminho e reconstruido de tras para frente.
    int cur = dst;
    while (cur != src) {
        path.push_back(cur);
        cur = nextHop[src][cur];
        if (cur < 0) return {};              // destino inalcancavel
    }
    path.push_back(src);
    std::reverse(path.begin(), path.end());
    return path;
}

// ---------------------------------------------------------------------------
// Transporte
// ---------------------------------------------------------------------------

double TischServer::perQuadro(int i, int j) const {
    // A tabela de PER (Prando et al., 2019) e de um quadro de 127 bytes. Um
    // quadro maior tem mais bits para errar: com erro de bit independente,
    // PER(L) = 1 - (1 - PER(127))^(L/127). No TSCH, L = 127 e nada muda.
    if (frameBytes <= 127) return per[i][j];
    return 1.0 - std::pow(1.0 - per[i][j], frameBytes / 127.0);
}

double TischServer::wisunHopDelay(int i, int j, int frames, bool& lost) {
    // Por quadro: recuo do CSMA/CA (uniforme em 0 .. 2^BE - 1 unidades), tempo
    // no ar do quadro com preambulo, SFD e PHR, reversao, ACK e espacamento
    // longo entre quadros. Uma falha dobra a janela de recuo, ate maxBE, e
    // gasta mais uma tentativa. O canal esta sempre livre: sem disputa.
    lost = false;
    double ar = (frameBytes + shrPhrBytes) * 8.0 / phyRate;
    double ack = turnaround + (ackBytes + shrPhrBytes) * 8.0 / phyRate;
    double p = perQuadro(i, j);
    double delay = 0.0;
    for (int f = 0; f < frames; ++f) {
        int be = minBE;
        for (int tentativa = 0;; ++tentativa) {
            delay += intuniform(0, (1 << be) - 1) * unitBackoff + ar;
            if (uniform(0.0, 1.0) >= p) {
                delay += ack + lifs;
                break;
            }
            delay += turnaround + (ackBytes + shrPhrBytes) * 8.0 / phyRate;  // espera do ACK
            if (tentativa >= maxRetries) {
                lost = true;
                return delay;
            }
            be = std::min(be + 1, maxBE);
        }
    }
    return delay;
}

double TischServer::hopDelay(int i, int j, int frames, bool& lost) {
    // Em TSCH o quadro so sai no cell alocado para o enlace. O primeiro espera
    // uma fracao qualquer do slotframe; os seguintes esperam um slotframe cheio,
    // um por cell disponivel. Cada retransmissao gasta mais um cell.
    lost = false;
    // Agentes na mesma coordenada (na IEEE 13, o AM, o AD e o concentrador, todos
    // na subestacao) estao no mesmo equipamento ou na mesma rede local. Com
    // `colocated_wired`, a troca entre eles nao passa pelo radio.
    if (colocatedWired && colocated[i][j]) return 0.0;
    if (wisun) return wisunHopDelay(i, j, frames, lost);
    double spacing = slotframe / std::max(1, cells);
    double delay = uniform(0.0, slotframe);
    for (int f = 0; f < frames; ++f) {
        if (f > 0) delay += spacing;
        int attempt = 0;
        while (uniform(0.0, 1.0) < per[i][j]) {
            attempt++;
            delay += spacing;
            if (attempt > maxRetries) {
                // Esgotou macMaxFrameRetries. Perder um fragmento perde o
                // datagrama inteiro: o 6LoWPAN nao recupera fragmento isolado.
                lost = true;
                return delay;
            }
        }
    }
    return delay;
}

void TischServer::startPacket(const json& j) {
    std::string src = j.value("src", "");
    std::string dst = j.value("dst", "");
    long bytes = j.value("bytes", 0L);

    flight = InFlight();
    flight.start = simTime();

    auto itS = indexOf.find(src), itD = indexOf.find(dst);
    if (itS == indexOf.end() || itD == indexOf.end()) {
        // Origem ou destino sem posicao no `nodes_xy.csv`. Entregar sem atraso e
        // mentir menos do que descartar: o agente nao esta no modelo de radio.
        flight.dropped = false;
        flight.path.clear();
        replyDone();
        return;
    }

    flight.frames = (int)std::max(1L, (bytes + frameBytes - 1) / frameBytes);
    flight.path = route(itS->second, itD->second, flight.frames);
    flight.hop = 0;

    if (flight.path.empty()) {
        flight.dropped = true;                    // destino inalcancavel
        replyDone();
        return;
    }
    if (flight.path.size() == 1) {                // origem e destino no mesmo no
        replyDone();
        return;
    }

    bool lost = false;
    double d = hopDelay(flight.path[0], flight.path[1], flight.frames, lost);
    flight.dropped = lost;
    flight.nominalDelay = d;
    flight.hop = 1;
    if (!hopMsg) hopMsg = new cMessage("hop");
    scheduleAt(simTime() + d, hopMsg);
}

void TischServer::replyDone() {
    json resp = {
        {"status", "ok"},
        {"dropped", flight.dropped},
        {"delay", flight.nominalDelay},
        {"hops", flight.path.empty() ? 0 : (int)flight.path.size() - 1},
        {"frames", flight.frames},
    };
    socket.send(zmq::buffer(resp.dump()), zmq::send_flags::none);
    serve();
}

// ---------------------------------------------------------------------------
// Servico ZMQ
// ---------------------------------------------------------------------------

void TischServer::serve() {
    // Bloqueia ate chegar um pedido. Pedidos que nao geram pacote (info, stop)
    // sao respondidos aqui mesmo e o laco continua.
    while (true) {
        zmq::message_t request;
        auto got = socket.recv(request, zmq::recv_flags::none);
        if (!got) continue;
        std::string s(static_cast<char*>(request.data()), request.size());
        json j = json::parse(s, nullptr, false);
        if (j.is_discarded()) {
            socket.send(zmq::buffer(json({{"status", "error"}}).dump()),
                        zmq::send_flags::none);
            continue;
        }

        std::string action = j.value("action", "route");
        if (action == "route") {
            startPacket(j);
            return;                              // a resposta sai quando o pacote resolver
        }
        if (action == "info") {
            size_t n = names.size();
            int links = 0;
            double perSum = 0.0;
            for (size_t i = 0; i < n; ++i)
                for (size_t k = i + 1; k < n; ++k)
                    if (adjacent[i][k]) { links++; perSum += per[i][k]; }
            int unreachable = 0, hopSum = 0, pairs = 0;
            for (size_t i = 0; i < n; ++i)
                for (size_t k = 0; k < n; ++k) {
                    if (i == k) continue;
                    auto p = route(i, k, 1);
                    if (p.empty()) unreachable++;
                    else { hopSum += (int)p.size() - 1; pairs++; }
                }
            json resp = {
                {"status", "ok"},
                {"nodes", (int)n},
                {"links", links},
                {"mean_link_per", links ? perSum / links : 0.0},
                {"mean_hops", pairs ? (double)hopSum / pairs : 0.0},
                {"unreachable_pairs", unreachable},
                {"slotframe_s", slotframe},
                {"frame_bytes", frameBytes},
            };
            socket.send(zmq::buffer(resp.dump()), zmq::send_flags::none);
            continue;
        }
        if (action == "stop") {
            socket.send(zmq::buffer(json({{"status", "ok"}}).dump()),
                        zmq::send_flags::none);
            endSimulation();
            return;
        }
        socket.send(zmq::buffer(json({{"status", "error"},
                                      {"reason", "acao desconhecida"}}).dump()),
                    zmq::send_flags::none);
    }
}

void TischServer::initialize() {
    frequency = par("frequency_hz").doubleValue();
    txPower = par("tx_power_dbm").doubleValue();
    txGain = par("tx_gain_db").doubleValue();
    rxGain = par("rx_gain_db").doubleValue();
    shiftDb = par("pister_hack_shift_db").doubleValue();
    sensitivity = par("sensitivity_dbm").doubleValue();
    slotframe = par("slotframe_s").doubleValue();
    cells = par("cells_per_slotframe").intValue();
    frameBytes = par("frame_bytes").intValue();
    maxRetries = par("max_retries").intValue();
    threshold = par("link_per_threshold").doubleValue();
    colocatedWired = par("colocated_wired").boolValue();

    std::string mac = par("mac").stdstringValue();
    if (mac != "tsch" && mac != "wisun")
        throw cRuntimeError("mac desconhecido: '%s' (use tsch ou wisun)", mac.c_str());
    wisun = (mac == "wisun");
    phyRate = par("phy_rate_bps").doubleValue();
    if (wisun) {
        frameBytes = par("wisun_frame_bytes").intValue();
        unitBackoff = par("unit_backoff_s").doubleValue();
        turnaround = par("turnaround_s").doubleValue();
        minBE = par("min_be").intValue();
        maxBE = par("max_be").intValue();
        shrPhrBytes = par("shr_phr_bytes").intValue();
        ackBytes = par("ack_bytes").intValue();
        // Espacamento longo (LIFS): 40 simbolos; no FSK, um simbolo por bit.
        lifs = 40.0 / phyRate;
        // Mesmo Eb/N0 a uma taxa maior pede mais potencia recebida.
        sensitivity += 10.0 * std::log10(phyRate / 50000.0);
    }

    loadPositions(par("positions_file").stdstringValue());
    // A topologia do Wi-SUN depende da taxa (a sensibilidade muda), entao vai
    // para um arquivo proprio e nao sobrescreve a da 6TiSCH.
    std::string links = par("links_csv").stdstringValue();
    if (wisun && !links.empty()) {
        auto ponto = links.rfind(".csv");
        std::string sufixo = "_wisun_" + std::to_string((int)(phyRate / 1000)) + "k";
        links = ponto == std::string::npos ? links + sufixo : links.substr(0, ponto) + sufixo + ".csv";
    }
    buildLinks(links);
    buildRoutes(1);

    std::string endpoint = "tcp://*:" + std::to_string(par("port").intValue());
    socket.bind(endpoint);
    EV << "[6TiSCH] servidor de rotas em " << endpoint << "\n";
    // A saida padrao e o que o `docker compose logs` mostra; o EV do Cmdenv nao
    // aparece sem verbosidade alta.
    // O prefixo "[6TiSCH] pronto" e o que o run.sh espera no log, nos dois MACs.
    if (wisun)
        std::printf("[6TiSCH] pronto: %zu nos, servidor em %s (Wi-SUN FAN, %.0f kbps, "
                    "quadro de %d bytes, sensibilidade %.2f dBm)\n", names.size(),
                    endpoint.c_str(), phyRate / 1000.0, frameBytes, sensitivity);
    else
        std::printf("[6TiSCH] pronto: %zu nos, servidor em %s (TSCH, %d cells por "
                    "slotframe de %.2f s)\n", names.size(), endpoint.c_str(), cells, slotframe);
    std::fflush(stdout);

    serve();
}

void TischServer::handleMessage(cMessage *msg) {
    if (msg != hopMsg) { delete msg; return; }

    if (flight.dropped || flight.hop + 1 >= flight.path.size()) {
        replyDone();
        return;
    }
    bool lost = false;
    double d = hopDelay(flight.path[flight.hop], flight.path[flight.hop + 1],
                        flight.frames, lost);
    flight.dropped = lost;
    flight.nominalDelay += d;
    flight.hop++;
    scheduleAt(simTime() + d, hopMsg);
}

void TischServer::finish() {
    if (hopMsg) cancelAndDelete(hopMsg);
    socket.close();
}
