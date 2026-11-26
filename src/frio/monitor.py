from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np

from .cargas import CARGAS
from .decisao import recomendar
from .modelo import ModeloCiclo

CALIBRAR_MIN = 60
CUSUM_FOLGA = 0.06
CUSUM_LIMITE = 3.0
IGNORAR_APOS_PORTA = 10
PORTA_FORA_DE_ENTREGA = 3
PORTA_NA_ENTREGA = 12
JANELA_TENDENCIA = 30
PORTA_RECUPERACAO = 15
DESVIO_MAX_SEM_PORTA = 0.5
RECUPERACAO_MAX = 45


@dataclass
class Alerta:
    minuto: int
    tipo: str
    mensagem: str
    recomendacao: str


@dataclass
class Monitor:
    caminhao: str
    carga: str
    modelo: ModeloCiclo
    minuto: int = 0
    fator: float | None = None
    cusum: float = 0.0
    vida_consumida: float = 0.0
    minutos_fora: int = 0
    porta_aberta_desde: int | None = None
    ultima_porta: int = -10_000
    voltou_ao_setpoint: bool = True
    alertas: list[Alerta] = field(default_factory=list)
    _ativos: set[str] = field(default_factory=set)
    _calib: list[tuple[float, float]] = field(default_factory=list)
    _porta10: deque = field(default_factory=lambda: deque(maxlen=10))
    _temps: deque = field(default_factory=lambda: deque(maxlen=JANELA_TENDENCIA))
    _ciclos: deque = field(default_factory=lambda: deque(maxlen=JANELA_TENDENCIA))
    _razao: deque = field(default_factory=lambda: deque(maxlen=JANELA_TENDENCIA))

    def atualizar(self, l: dict) -> dict:
        c = CARGAS[self.carga]
        m = l["minuto"]
        self.minuto = m
        temp, porta, ciclo = l["temp"], int(l["porta"]), float(l["ciclo"])
        self._porta10.append(porta)
        novos: list[Alerta] = []

        if temp is not None:
            self.vida_consumida += c.q10 ** ((temp - c.setpoint) / 10) / (c.vida_h * 60)
            if not (c.minimo <= temp <= c.maximo):
                self.minutos_fora += 1
            self._temps.append(temp)
        if porta:
            self.ultima_porta = m
            self.voltou_ao_setpoint = False
        elif temp is not None and temp <= c.setpoint + DESVIO_MAX_SEM_PORTA:
            self.voltou_ao_setpoint = True

        # 1. deriva do compressor
        previsto = None
        if temp is not None:
            previsto = float(
                self.modelo.prever(
                    {
                        "delta_externa": l["temp_externa"] - c.setpoint,
                        "desvio": temp - c.setpoint
                        if not self._bau_recuperado(m)
                        else min(temp - c.setpoint, DESVIO_MAX_SEM_PORTA),
                        "porta": porta,
                        "porta_recente": sum(self._porta10),
                    }
                )[0]
            )
        calmo = previsto is not None and m - self.ultima_porta > IGNORAR_APOS_PORTA
        if calmo and self.fator is None:
            self._calib.append((ciclo, previsto))
            if m >= CALIBRAR_MIN and len(self._calib) >= 20:
                medido, prev = np.array(self._calib).T
                self.fator = float(np.clip(np.median(medido) / max(np.median(prev), 1e-3), 0.6, 1.6))
        if calmo and self.fator is not None:
            esperado = min(1.0, previsto * self.fator)
            self.cusum = max(0.0, self.cusum + (ciclo - esperado) - CUSUM_FOLGA)
            if ciclo < 0.95:
                self._razao.append(esperado / max(ciclo, 1e-3))
            if self.cusum > CUSUM_LIMITE:
                novos += self._abrir("deriva_compressor", m, "Compressor trabalhando acima do normal para esta carga e este calor")
        self._ciclos.append(ciclo)

        # 2. porta
        if porta:
            self.porta_aberta_desde = m if self.porta_aberta_desde is None else self.porta_aberta_desde
            aberta = m - self.porta_aberta_desde + 1
            fora = not l.get("parada")
            if (fora and aberta >= PORTA_FORA_DE_ENTREGA) or aberta >= PORTA_NA_ENTREGA:
                onde = "com o caminhão fora de um ponto de entrega" if fora else f"há {aberta} min na entrega"
                novos += self._abrir("porta_aberta", m, f"Porta aberta {onde}")
        else:
            self.porta_aberta_desde = None
            self._ativos.discard("porta_aberta")

        # 3. previsão de violação
        eta = self.minutos_ate_violar()
        if eta is not None and eta <= 60:
            novos += self._abrir("previsao_violacao", m, f"Temperatura deve passar de {c.maximo:.0f} °C em cerca de {eta:.0f} min")

        if temp is not None and temp > c.maximo and m - self.ultima_porta > PORTA_RECUPERACAO:
            novos += self._abrir("temperatura_fora", m, f"Temperatura de {temp:.1f} °C, acima do máximo de {c.maximo:.0f} °C")
        elif temp is not None and temp <= c.maximo:
            self._ativos.discard("temperatura_fora")

        for a in novos:
            a.recomendacao = recomendar(a.tipo, self, l)
        self.alertas += novos
        return self.estado(novos)

    def _abrir(self, tipo: str, minuto: int, msg: str) -> list[Alerta]:
        if tipo in self._ativos:
            return []
        self._ativos.add(tipo)
        return [Alerta(minuto, tipo, msg, "")]

    def _bau_recuperado(self, m: int) -> bool:
        if m - self.ultima_porta <= PORTA_RECUPERACAO:
            return False
        return self.voltou_ao_setpoint or m - self.ultima_porta > RECUPERACAO_MAX

    def eficiencia_estimada(self) -> float | None:
        if self.fator is None:
            return None
        if self._ciclos and np.mean(list(self._ciclos)[-10:]) > 0.95:
            return None 
        if len(self._razao) < 10:
            return None
        return float(np.clip(np.median(self._razao), 0, 1.2))

    def minutos_ate_violar(self) -> float | None:
        c = CARGAS[self.carga]
        if len(self._temps) < JANELA_TENDENCIA or self.minuto - self.ultima_porta <= JANELA_TENDENCIA:
            return None
        if np.mean(list(self._ciclos)[-10:]) < 0.95:
            return None  # compressor ainda tem folga
        temps = np.array(self._temps)
        inclinacao = np.polyfit(np.arange(len(temps)), temps, 1)[0]
        if inclinacao <= 0.005 or temps[-1] >= c.maximo:
            return None
        return float((c.maximo - temps[-1]) / inclinacao)

    def estado(self, novos: list[Alerta] | None = None) -> dict:
        return {
            "caminhao": self.caminhao,
            "carga": self.carga,
            "minuto": self.minuto,
            "cusum": round(self.cusum, 3),
            "eficiencia_estimada": self.eficiencia_estimada(),
            "minutos_ate_violar": self.minutos_ate_violar(),
            "vida_restante": round(max(0.0, 1 - self.vida_consumida), 4),
            "minutos_fora": self.minutos_fora,
            "novos_alertas": [a.__dict__ for a in (novos or [])],
        }
