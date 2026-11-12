"""Avaliação com viagens simuladas e gabarito conhecido.

Compara o monitor com dois alarmes clássicos de limite fixo:
    limite: dispara na primeira leitura acima do máximo da carga
    limite_porta: o mesmo, mas ignora os 15 minutos depois de uma abertura de
        porta, para não tocar a cada entrega

Na falha de compressor só contam os alertas de compressor da IA
(deriva_compressor e previsao_violacao); na de porta, só porta_aberta.

Sementes separadas para treino (10000+), ajuste (15000+) e teste (20000+).
Os parâmetros do monitor foram escolhidos olhando só as viagens de ajuste.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .borda import Borda
from .cargas import CARGAS
from .modelo import ModeloCiclo
from .monitor import Monitor
from .simulador import simular_viagem

SEMENTE_TREINO = 10_000
SEMENTE_AJUSTE = 15_000
SEMENTE_TESTE = 20_000
ALERTAS_IA = {"deriva_compressor", "porta_aberta", "previsao_violacao"}
ALERTAS_DA_FALHA = {
    "compressor": {"deriva_compressor", "previsao_violacao"},
    "porta": {"porta_aberta"},
}
PORTA_RECENTE = 16  # minutos (a abertura e os 15 seguintes)


def tratar(df: pd.DataFrame) -> list[dict]:
    borda = Borda(df["carga"].iloc[0])
    campos = ["ts", "minuto", "caminhao", "carga", "temp", "umidade", "porta", "temp_externa", "ciclo", "lat", "lon", "parada"]
    return [borda.processar(r) for r in df[campos].to_dict("records")]


def treinar(n: int = 40) -> ModeloCiclo:
    viagens = []
    for i in range(n):
        t = pd.DataFrame(tratar(simular_viagem(SEMENTE_TREINO + i, "nenhuma")))
        viagens.append(t[t["temp"].notna()])
    return ModeloCiclo().treinar(viagens)


def lote(semente: int, n_normal: int, n_compressor: int, n_porta: int) -> list[tuple[int, str]]:
    tipos = ["nenhuma"] * n_normal + ["compressor"] * n_compressor + ["porta"] * n_porta
    return [(semente + i, t) for i, t in enumerate(tipos)]


@dataclass
class ResultadoViagem:
    semente: int
    falha: str
    carga: str
    inicio_falha: int
    violacao: int  # primeiro minuto com a temperatura real acima do máximo (-1 se não houve)
    ia: int  # primeiro alerta de IA a partir do início da falha (-1 se não houve)
    ia_tipo: str
    ia_falsos: int  # alertas de IA sem falha ou antes do início dela
    limite: int
    limite_falsos: int
    limite_porta: int
    limite_porta_falsos: int


def primeira_violacao(bruto: pd.DataFrame, maximo: float, inicio: int) -> int:
    """Primeiro minuto, depois do início da falha, com a temperatura real acima
    do máximo sem porta aberta nos 15 minutos anteriores (excursões curtas de
    entrega não contam). -1 se não houve."""
    porta_recente = _porta_recente(bruto)
    acima = (bruto["verdade_temp"].to_numpy() > maximo) & ~porta_recente
    acima[: max(inicio, 0)] = False
    return int(np.argmax(acima)) if acima.any() else -1


def _porta_recente(bruto: pd.DataFrame) -> np.ndarray:
    return bruto["porta"].rolling(PORTA_RECENTE, min_periods=1).max().to_numpy() > 0


def _primeiro(minutos: list[int], inicio: int) -> tuple[int, int]:
    """(primeiro alarme depois do início da falha, quantos alarmes antes dele)."""
    validos = [m for m in minutos if inicio >= 0 and m >= inicio]
    falsos = [m for m in minutos if inicio < 0 or m < inicio]
    return (validos[0] if validos else -1), len(falsos)


def _episodios(acima: np.ndarray, persistencia: int) -> list[int]:
    """Minutos em que um alarme de limite dispara (um por episódio)."""
    disparos, seguidos = [], 0
    for m, a in enumerate(acima):
        seguidos = seguidos + 1 if a else 0
        if seguidos == persistencia:
            disparos.append(m)
    return disparos


def avaliar_viagem(semente: int, falha: str, modelo: ModeloCiclo) -> tuple[ResultadoViagem, pd.DataFrame, list]:
    bruto = simular_viagem(semente, falha)
    c = CARGAS[bruto["carga"].iloc[0]]
    leituras = tratar(bruto)
    mon = Monitor(bruto["caminhao"].iloc[0], c.nome, modelo)
    estados = [mon.atualizar(l) for l in leituras]

    inicio = int(bruto["verdade_inicio"].iloc[0])
    violacao = primeira_violacao(bruto, c.maximo, inicio)

    ia_alertas = [a for a in mon.alertas if a.tipo in ALERTAS_IA]
    ia_falsos = sum(1 for a in ia_alertas if inicio < 0 or a.minuto < inicio)
    da_falha = [a for a in ia_alertas if a.tipo in ALERTAS_DA_FALHA.get(falha, set()) and a.minuto >= inicio]
    ia = da_falha[0].minuto if da_falha else -1
    ia_tipo = da_falha[0].tipo if da_falha else ""

    medida = np.array([l["temp"] if l["temp"] is not None else np.nan for l in leituras])
    acima = np.nan_to_num(medida, nan=-99) > c.maximo
    limite, limite_falsos = _primeiro(_episodios(acima, 1), inicio)
    limite_porta, limite_porta_falsos = _primeiro(_episodios(acima & ~_porta_recente(bruto), 1), inicio)

    r = ResultadoViagem(semente, falha, c.nome, inicio, violacao, ia, ia_tipo, ia_falsos, limite, limite_falsos, limite_porta, limite_porta_falsos)
    serie = bruto.assign(**{k: [e[k] for e in estados] for k in ("cusum", "eficiencia_estimada", "vida_restante")})
    serie["temp_tratada"] = medida
    return r, serie, mon.alertas


def resumir(res: list[ResultadoViagem]) -> dict:
    df = pd.DataFrame([asdict(r) for r in res])
    out: dict = {"viagens": len(df), "por_tipo": df["falha"].value_counts().to_dict()}

    normais = df[df.falha == "nenhuma"]
    out["alarmes_falsos_por_viagem_normal"] = {
        "ia": round(normais.ia_falsos.mean(), 3),
        "limite": round(normais.limite_falsos.mean(), 3),
        "limite_porta": round(normais.limite_porta_falsos.mean(), 3),
    }
    out["viagens_normais_com_alarme_falso"] = {
        "ia": int((normais.ia_falsos > 0).sum()),
        "limite": int((normais.limite_falsos > 0).sum()),
        "limite_porta": int((normais.limite_porta_falsos > 0).sum()),
        "de": len(normais),
    }

    for tipo in ("compressor", "porta"):
        f = df[df.falha == tipo]
        bloco: dict = {"viagens": len(f)}
        for nome in ("ia", "limite", "limite_porta"):
            det = f[f[nome] >= 0]
            bloco[nome] = {
                "detectadas": len(det),
                "atraso_mediano_min": float((det[nome] - det.inicio_falha).median()) if len(det) else None,
            }
        if tipo == "compressor":
            viol = f[f.violacao >= 0]
            bloco["com_violacao"] = len(viol)
            for nome in ("ia", "limite", "limite_porta"):
                antes = viol[(viol[nome] >= 0) & (viol[nome] < viol.violacao)]
                bloco[nome]["avisou_antes_da_violacao"] = len(antes)
                d = viol[viol[nome] >= 0]
                bloco[nome]["antecedencia_mediana_min"] = float((d.violacao - d[nome]).median()) if len(d) else None
            sem = f[f.violacao < 0]
            bloco["sem_violacao"] = len(sem)
            bloco["ia"]["pegou_sem_violacao"] = int((sem.ia >= 0).sum())
        out[tipo] = bloco
    return out


def rodar(saida: Path, conjunto: str = "teste", n_treino: int = 40) -> dict:
    saida.mkdir(parents=True, exist_ok=True)
    modelo = treinar(n_treino)
    modelo.salvar(saida / "modelo.pkl")
    semente = SEMENTE_TESTE if conjunto == "teste" else SEMENTE_AJUSTE
    viagens = lote(semente, 80, 70, 50) if conjunto == "teste" else lote(semente, 30, 30, 20)

    resultados, series = [], []
    for s, f in viagens:
        r, serie, _ = avaliar_viagem(s, f, modelo)
        resultados.append(r)
        series.append(serie.assign(semente=s))
    resumo = resumir(resultados)
    resumo["conjunto"] = conjunto
    resumo["erro_medio_modelo_ciclo"] = round(modelo.erro_medio or 0, 4)

    pd.DataFrame([asdict(r) for r in resultados]).to_csv(saida / f"viagens-{conjunto}.csv", index=False)
    pd.concat(series).to_parquet(saida / f"leituras-{conjunto}.parquet", index=False)
    (saida / f"resumo-{conjunto}.json").write_text(json.dumps(resumo, indent=2, ensure_ascii=False))
    return resumo
