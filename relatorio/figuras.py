from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from frio.cargas import CARGAS

AQUI = Path(__file__).parent
SAIDA = AQUI.parent / "saida"
SEMENTE = 20131  # viagem de teste com falha de compressor, antecedência perto da mediana

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.spines.top": False, "axes.spines.right": False})


def viagem_exemplo() -> None:
    leit = pd.read_parquet(SAIDA / "leituras-teste.parquet")
    v = leit[leit.semente == SEMENTE]
    r = pd.read_csv(SAIDA / "viagens-teste.csv").set_index("semente").loc[SEMENTE]
    c = CARGAS[r.carga]
    fig, ax = plt.subplots(3, 1, figsize=(7.2, 5.4), sharex=True, gridspec_kw={"height_ratios": [2, 1, 1]})
    ax[0].axhspan(c.minimo, c.maximo, color="#2E7D32", alpha=0.08)
    ax[0].plot(v.minuto, v.temp_tratada, color="#1565C0", lw=1)
    ax[0].scatter(v.minuto[v.porta == 1], [c.maximo + 0.6] * int((v.porta == 1).sum()), s=4, color="#F9A825", label="porta aberta")
    ax[0].set_ylabel("°C no baú")
    ax[0].legend(loc="lower left", frameon=False)
    ax[1].plot(v.minuto, v.ciclo, color="#6A1B9A", lw=0.8)
    ax[1].set_ylabel("ciclo")
    ax[1].set_ylim(0, 1.05)
    ax[2].plot(v.minuto, v.cusum, color="#C62828", lw=1)
    ax[2].axhline(3.0, color="#C62828", ls=":", lw=0.8)
    ax[2].set_ylabel("CUSUM")
    ax[2].set_ylim(0, 10)  # depois do alerta ele segue subindo; o que importa é o cruzamento do limite
    ax[2].set_xlabel("minuto da viagem")
    for a in ax:
        a.axvline(r.inicio_falha, color="#555", ls="--", lw=0.8)
        a.axvline(r.ia, color="#C62828", lw=1)
        a.axvline(r.violacao, color="#000", lw=1)
    topo = ax[0].get_ylim()[1]
    ax[0].text(r.inicio_falha, topo, " falha começa", va="top", ha="right", fontsize=8, color="#555")
    ax[0].text(r.ia, topo, " alerta da IA", va="top", fontsize=8, color="#C62828")
    ax[0].text(r.violacao, topo * 0.88, " sai da faixa", va="top", fontsize=8)
    fig.tight_layout()
    fig.savefig(AQUI / "figuras" / "viagem-compressor.png", dpi=200)


def antecedencia() -> None:
    d = pd.read_csv(SAIDA / "viagens-teste.csv")
    f = d[(d.falha == "compressor") & (d.violacao >= 0) & (d.ia >= 0)]
    fig, ax = plt.subplots(figsize=(7.2, 2.4))
    ax.hist(f.violacao - f.ia, bins=20, color="#1565C0")
    ax.axvline(0, color="#000", lw=0.8)
    ax.set_xlabel("minutos entre o alerta da IA e a saída da faixa (positivo = avisou antes)")
    ax.set_ylabel("viagens")
    fig.tight_layout()
    fig.savefig(AQUI / "figuras" / "antecedencia.png", dpi=200)


if __name__ == "__main__":
    viagem_exemplo()
    antecedencia()
