"""Gateway do caminhão (borda).

Recebe a leitura bruta de cada minuto, limpa e decide o alarme local, que
precisa funcionar mesmo sem conexão com a nuvem.

Limpeza da temperatura:
    - valor fora da faixa física do baú (-40 a 60 °C) ou salto maior que
      5 °C em um minuto: descartado como pico de leitura
    - leitura ausente ou descartada: repete a última válida por até 10
      minutos e marca como estimada; depois disso fica ausente
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .cargas import CARGAS

FAIXA_FISICA = (-39.0, 60.0)
SALTO_MAX = 5.0
ESTIMAR_ATE = 10  # minutos
MARGEM_ALARME_LOCAL = 2.0  # °C acima do máximo da carga


@dataclass
class Borda:
    carga: str
    ultima_valida: float | None = None
    minutos_sem_leitura: int = 0
    descartes: int = 0
    estimadas: int = 0

    def processar(self, leitura: dict) -> dict:
        """Devolve a leitura tratada, com ``temp_status`` e ``alarme_local``."""
        bruto = leitura.get("temp")
        valido = bruto is not None and not (isinstance(bruto, float) and math.isnan(bruto))
        if valido and not (FAIXA_FISICA[0] <= bruto <= FAIXA_FISICA[1]):
            valido = False
            self.descartes += 1
        elif (
            valido
            and self.ultima_valida is not None
            and self.minutos_sem_leitura < ESTIMAR_ATE  # depois de um buraco longo, aceita o novo patamar
            and abs(bruto - self.ultima_valida) > SALTO_MAX
        ):
            valido = False
            self.descartes += 1

        tratado = dict(leitura)
        if valido:
            self.ultima_valida = bruto
            self.minutos_sem_leitura = 0
            tratado["temp_status"] = "ok"
        else:
            self.minutos_sem_leitura += 1
            if self.ultima_valida is not None and self.minutos_sem_leitura <= ESTIMAR_ATE:
                tratado["temp"] = self.ultima_valida
                tratado["temp_status"] = "estimada"
                self.estimadas += 1
            else:
                tratado["temp"] = None
                tratado["temp_status"] = "sem_leitura"

        limite = CARGAS[self.carga].maximo + MARGEM_ALARME_LOCAL
        tratado["alarme_local"] = tratado["temp"] is not None and tratado["temp"] > limite
        return tratado
