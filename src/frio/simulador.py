from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .cargas import CARGAS, Carga

CDS = {
    "CD Porto Alegre": (-30.0346, -51.2177),
    "CD Caxias do Sul": (-29.1678, -51.1794),
    "CD Santa Cruz do Sul": (-29.7175, -52.4258),
}
CIDADES = {
    "Canoas": (-29.9178, -51.1839),
    "Esteio": (-29.8616, -51.1794),
    "São Leopoldo": (-29.7604, -51.1478),
    "Novo Hamburgo": (-29.6783, -51.1309),
    "Gravataí": (-29.9440, -50.9919),
    "Cachoeirinha": (-29.9472, -51.0932),
    "Montenegro": (-29.6886, -51.4613),
    "Venâncio Aires": (-29.6061, -52.1917),
    "Lajeado": (-29.4669, -51.9614),
    "Bento Gonçalves": (-29.1662, -51.5165),
    "Farroupilha": (-29.2227, -51.3419),
    "Guaíba": (-30.1139, -51.3250),
}

FALHAS = ("nenhuma", "compressor", "porta")


@dataclass
class Bau:
    caminhao: str
    isolamento: float  # perda por minuto por °C de diferença
    capacidade: float  # °C por minuto de frio a 100% do ciclo
    ganho: float = 0.15
    porta_coef: float = 0.03

    @staticmethod
    def sortear(caminhao: str, rng: np.random.Generator) -> "Bau":
        return Bau(
            caminhao=caminhao,
            isolamento=float(rng.uniform(0.0030, 0.0045)),
            capacidade=float(rng.uniform(0.35, 0.45)),
        )


@dataclass
class Falha:
    tipo: str = "nenhuma"
    inicio: int | None = None  # minuto em que começa
    duracao: int = 0  # minutos (porta) ou minutos até a eficiência mínima (compressor)
    eficiencia_min: float = 1.0


@dataclass
class Parada:
    nome: str
    chegada: int
    saida: int
    aberturas: list[tuple[int, int]] = field(default_factory=list)  # (início, fim)


def _distancia_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def montar_rota(rng: np.random.Generator) -> tuple[list[Parada], np.ndarray, int]:
    origem = CDS["CD Porto Alegre"]
    n = int(rng.integers(5, 9))
    nomes = list(rng.choice(list(CIDADES), size=n, replace=False))
    pontos = [("CD Porto Alegre", origem)] + [(c, CIDADES[c]) for c in nomes] + [("CD Porto Alegre", origem)]

    paradas: list[Parada] = []
    posicoes: list[tuple[float, float]] = []
    t = 0
    for i in range(1, len(pontos)):
        (_, a), (nome, b) = pontos[i - 1], pontos[i]
        viagem = max(10, int(_distancia_km(a, b) / 50 * 60))  # 50 km/h com trânsito
        for k in range(viagem):
            f = k / viagem
            posicoes.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
        t += viagem
        if i == len(pontos) - 1:
            break
        estadia = int(rng.integers(20, 41))
        parada = Parada(nome, t, t + estadia)
        inicio = t + int(rng.integers(2, 6))
        for _ in range(int(rng.integers(1, 3))):
            dur = int(rng.integers(2, 6))
            if inicio + dur >= t + estadia:
                break
            parada.aberturas.append((inicio, inicio + dur))
            inicio += dur + int(rng.integers(3, 8))
        paradas.append(parada)
        posicoes.extend([b] * estadia)
        t += estadia
    return paradas, np.array(posicoes), t


def sortear_falha(tipo: str, duracao: int, paradas: list[Parada], rng: np.random.Generator) -> Falha:
    if tipo == "compressor":
        inicio = int(rng.integers(90, max(91, duracao // 2)))
        return Falha("compressor", inicio, int(rng.integers(150, 300)), float(rng.uniform(0.05, 0.25)))
    if tipo == "porta":
        # porta mal fechada na saída de uma entrega: fica aberta com o caminhão andando
        p = paradas[int(rng.integers(1, len(paradas)))]
        return Falha("porta", p.saida - 1, int(rng.integers(20, 46)))
    return Falha()


def simular_viagem(
    seed: int,
    falha: str = "nenhuma",
    carga: str | None = None,
    caminhao: str | None = None,
    inicio: pd.Timestamp | None = None,
    ruido_sensor: bool = True,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    c: Carga = CARGAS[carga or str(rng.choice(list(CARGAS)))]
    caminhao = caminhao or f"IOT-{int(rng.integers(1000, 9999))}"
    bau = Bau.sortear(caminhao, rng)
    paradas, posicoes, duracao = montar_rota(rng)
    f = sortear_falha(falha, duracao, paradas, rng)
    inicio = inicio or pd.Timestamp("2026-11-16") + pd.Timedelta(minutes=int(rng.integers(5 * 60, 9 * 60)))

    porta = np.zeros(duracao, dtype=int)
    em_parada = np.zeros(duracao, dtype=bool)
    nome_parada = np.full(duracao, "", dtype=object)
    for p in paradas:
        em_parada[p.chegada : p.saida] = True
        nome_parada[p.chegada : p.saida] = p.nome
        for a, b in p.aberturas:
            porta[a:b] = 1
    if f.tipo == "porta":
        porta[f.inicio : f.inicio + f.duracao] = 1

    eficiencia = np.ones(duracao)
    if f.tipo == "compressor":
        m = np.arange(duracao)
        queda = np.clip((m - f.inicio) / f.duracao, 0, 1)
        eficiencia = 1 - (1 - f.eficiencia_min) * queda

    horas = np.array([(inicio + pd.Timedelta(minutes=int(m))).hour + m % 60 / 60 for m in range(duracao)])
    base_dia = float(rng.uniform(20, 27))
    externa = base_dia + 7 * np.sin(2 * np.pi * (horas - 9) / 24) + rng.normal(0, 0.4, duracao)

    temp = np.empty(duracao)
    ciclo = np.empty(duracao)
    t = c.setpoint + float(rng.normal(0, 0.2))
    for m in range(duracao):
        delta = externa[m] - t
        calor = bau.isolamento * delta + porta[m] * bau.porta_coef * delta
        pedido = calor + bau.ganho * (t - c.setpoint)
        maximo = bau.capacidade * eficiencia[m]
        frio = min(max(pedido, 0.0), maximo)
        ciclo[m] = frio / maximo if maximo > 0 else 1.0
        t = t + calor - frio + float(rng.normal(0, 0.03))
        temp[m] = t

    umidade = np.clip(88 + rng.normal(0, 1.5, duracao) + porta * 6, 60, 100)
    ciclo_medido = np.clip(ciclo + rng.normal(0, 0.03, duracao), 0, 1)

    temp_medida = temp + rng.normal(0, 0.05, duracao)
    if ruido_sensor:
        picos = rng.random(duracao) < 0.002
        temp_medida[picos] = rng.choice([85.0, -40.0], size=int(picos.sum()))
        for _ in range(int(rng.integers(1, 4))):
            a = int(rng.integers(0, duracao - 20))
            temp_medida[a : a + int(rng.integers(2, 16))] = np.nan

    return pd.DataFrame(
        {
            "ts": [inicio + pd.Timedelta(minutes=m) for m in range(duracao)],
            "minuto": np.arange(duracao),
            "caminhao": caminhao,
            "carga": c.nome,
            "temp": np.round(temp_medida, 2),
            "umidade": np.round(umidade, 1),
            "porta": porta,
            "temp_externa": np.round(externa, 2),
            "ciclo": np.round(ciclo_medido, 3),
            "lat": np.round(posicoes[:, 0], 5),
            "lon": np.round(posicoes[:, 1], 5),
            "parada": nome_parada,
            "verdade_falha": f.tipo,
            "verdade_inicio": f.inicio if f.inicio is not None else -1,
            "verdade_temp": np.round(temp, 3),
            "verdade_eficiencia": np.round(eficiencia, 3),
        }
    )
