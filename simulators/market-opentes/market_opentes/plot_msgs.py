"""Figuras 58 e 59 da tese, a partir do traço de mensagens da nossa execução.

A tese analisa a comunicação da fase de OPERAÇÃO com dois pares de gráficos:

  Figura 58  cada mensagem, contra o tempo de co-simulação: (a) tamanho em bytes,
             (b) tempo de recepção em segundos.
  Figura 59  a distribuição das mesmas duas grandezas: histograma e acumulada.

Até aqui produzíamos `ciclos.png`, que é outra coisa: o tempo de rede AGREGADO
por ciclo contra a fatia de 15 minutos. Serve para responder "cabe na janela?",
não para comparar forma a forma com a tese. Sem estas quatro vistas não havia
como dizer em que a nossa comunicação difere da dela.

Entrada: o CSV que `NET_TRACE` grava, com uma linha por mensagem enviada.

    python -m market_opentes.plot_msgs --trace data/msg_trace.csv --out-dir data
"""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

INK = "#0b0b0b"
MUTED = "#52514e"
GRID = "0.85"

# Mesma convenção de cor da Figura 58: um tom por ciclo. A tese rotula os ciclos
# pelo agente que os INICIA, e não pelo remetente de cada mensagem: a nuvem
# vermelha dela são as propostas dos prosumidores dentro do ciclo aberto pelo AC.
CICLOS = {
    "ciclo1_AC_AP": ("#d81f1f", "Mens. do ciclo iniciado pelo AC"),
    "ciclo2_AD_AC": ("#1f4fd8", "Mens. do ciclo iniciado pelo AD"),
    "ciclo3_AM_AC_AD": ("#1baf7a", "Mens. do ciclo iniciado pelo AM"),
}
# Posição de cada ciclo dentro da janela de 15 min (subseção 6.1.2 da tese).
INICIO_MIN = {"ciclo1_AC_AP": 1.0, "ciclo2_AD_AC": 5.0, "ciclo3_AM_AC_AD": 10.0}
JANELA_MIN = 15.0


def _style(ax, xlabel, ylabel, title):
    ax.set_xlabel(xlabel, color=MUTED, fontsize=9)
    ax.set_ylabel(ylabel, color=MUTED, fontsize=9)
    ax.set_title(title, color=INK, fontsize=10, loc="left")
    ax.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    for lado in ("left", "bottom"):
        ax.spines[lado].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=8)


def carregar(trace_csv):
    """Lê o traço e reconstrói o tempo de co-simulação de cada mensagem.

    A tese põe no eixo x o tempo de execução da co-simulação. Aqui ele é
    reconstruído do intervalo de 15 min em curso, da posição do ciclo dentro da
    janela e do atraso da própria mensagem, que é o que produz o rastro
    ascendente dentro de cada aglomerado.
    """
    df = pd.read_csv(trace_csv)
    df = df[df["ciclo"].isin(CICLOS)]
    # Rede de seguranca para tracos gravados antes de o `network_link` passar a
    # excluir a instrumentacao: as copias que o PADE manda ao `sniffer` nao sao
    # trafego da arquitetura e falseiam as duas distribuicoes.
    antes = len(df)
    df = df[~df["receiver"].astype(str).str.startswith(("sniffer", "ams"))]
    if len(df) < antes:
        print(f"  descartadas {antes - len(df)} copias de instrumentacao "
              f"(sniffer/ams), que nao sao trafego da arquitetura")
    if "t" not in df or df["t"].isna().all():
        raise SystemExit("traço sem a coluna `t`: rode a fase de operação com "
                         "NET_TRACE ligado e a versão atual do network_link")
    df = df[df["t"].notna()].copy()
    df["t"] = df["t"].astype(int)
    df["min"] = (df["t"] * JANELA_MIN
                 + df["ciclo"].map(INICIO_MIN)
                 + df["delay_s"] / 60.0)
    return df


def figura_58(df, out_png, janelas=None):
    """(a) tamanho e (b) tempo de recepção, contra o tempo de co-simulação."""
    if janelas:
        t0 = int(df["t"].min())
        df = df[df["t"] < t0 + janelas]
    fig, axes = plt.subplots(2, 1, figsize=(11.0, 6.0), sharex=True)
    for eixo, coluna, rotulo in ((axes[0], "bytes", "Tamanho das mensagens\n(bytes)"),
                                 (axes[1], "delay_s", "Tempo de recep.\ndas mensagens (s)")):
        for nome, (cor, legenda) in CICLOS.items():
            sub = df[df["ciclo"] == nome]
            if sub.empty:
                continue
            eixo.scatter(sub["min"], sub[coluna], s=14, marker="x",
                         linewidths=0.9, color=cor, label=legenda)
        _style(eixo, "", rotulo, "")
    axes[0].set_title("Tempo de co-simulacao vs. tamanho das mensagens",
                      color=INK, fontsize=10, loc="left")
    axes[1].set_title("Tempo de co-simulacao vs. tempo de recepcao de mensagens",
                      color=INK, fontsize=10, loc="left")
    axes[1].set_xlabel("Tempo de execucao da co-simulacao (min)", color=MUTED,
                       fontsize=9)
    axes[0].legend(frameon=False, fontsize=8, loc="upper right")
    fig.tight_layout()
    fig.savefig(out_png, dpi=160)
    print(f"gravado {out_png}")


def figura_59(df, out_png):
    """Histograma e acumulada de tamanho e de tempo de recepção.

    A acumulada é em CONTAGEM, e não normalizada, para ser lida do mesmo jeito
    que a da tese: o eixo y termina no total de mensagens analisadas.
    """
    fig, axes = plt.subplots(2, 2, figsize=(10.5, 6.6))
    for linha, (coluna, unidade, nome) in enumerate(
            (("bytes", "bytes", "tamanho de mensagens"),
             ("delay_s", "s", "tempo de recepcao de mensagens"))):
        v = df[coluna].to_numpy()
        bins = np.histogram_bin_edges(v, bins=24)
        ax = axes[linha][0]
        ax.hist(v, bins=bins, color="#2a78d6", edgecolor="white", linewidth=0.4)
        _style(ax, f"{nome.split()[0].capitalize()} ({unidade})",
               "N de mensagens", f"Dist. de freq. de {nome}")
        ax = axes[linha][1]
        centros = (bins[:-1] + bins[1:]) / 2
        acum = np.cumsum(np.histogram(v, bins=bins)[0])
        ax.bar(centros, acum, width=(bins[1] - bins[0]) * 0.92,
               color="#2a78d6", edgecolor="white", linewidth=0.4)
        _style(ax, f"{nome.split()[0].capitalize()} ({unidade})",
               "N de mensagens", f"Dist. cumulada de {nome}")
    fig.tight_layout()
    fig.savefig(out_png, dpi=160)
    print(f"gravado {out_png}")


def resumo(df):
    """Os mesmos números que a tese cita no texto das Figuras 58 e 59."""
    n = len(df)
    janelas = df["t"].nunique()
    b, d = df["bytes"].to_numpy(), df["delay_s"].to_numpy()
    print(f"\n  mensagens                  {n}  em {janelas} janelas de 15 min "
          f"({n / janelas:.1f} por janela)")
    print(f"  tamanho                    {b.min():.0f} a {b.max():.0f} B, "
          f"mediana {np.median(b):.0f} B")
    print(f"  abaixo de 500 B            {(b <= 500).sum()} "
          f"({100.0 * (b <= 500).mean():.1f}%)")
    print(f"  entre 1000 e 1500 B        {((b >= 1000) & (b <= 1500)).sum()} "
          f"({100.0 * ((b >= 1000) & (b <= 1500)).mean():.1f}%)")
    print(f"  tempo de recepcao          {d.min():.1f} a {d.max():.1f} s, "
          f"mediana {np.median(d):.1f} s")
    print(f"  abaixo de 40 s             {(d <= 40).sum()} "
          f"({100.0 * (d <= 40).mean():.1f}%)")
    if "dropped" in df:
        print(f"  descartadas                {int(df['dropped'].sum())}")
    print("\n  por ciclo:")
    for nome in CICLOS:
        sub = df[df["ciclo"] == nome]
        if sub.empty:
            continue
        print(f"    {nome:<18} {len(sub):>5} mens  "
              f"{sub['bytes'].median():>6.0f} B mediana  "
              f"{sub['delay_s'].max():>6.1f} s pior atraso")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--trace", default="data/msg_trace.csv")
    p.add_argument("--out-dir", default="data")
    p.add_argument("--janelas", type=int, default=5,
                   help="quantas janelas de 15 min a Figura 58 mostra "
                        "(a tese mostra 5)")
    a = p.parse_args()
    out = Path(a.out_dir)
    df = carregar(a.trace)
    # O nome de arquivo das duas e o da legenda da tese, dado pelo
    # `figuras_tese`. Aqui elas so saem com nome curto para inspecao rapida.
    figura_58(df, out / "mensagens.png", a.janelas)
    figura_59(df, out / "distribuicoes.png")
    resumo(df)
