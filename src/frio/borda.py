from __future__ import annotations

import math
from dataclasses import dataclass

from .cargas import CARGAS

FAIXA_FISICA = (-39.0, 60.0)
SALTO_MAX = 5.0
ESTIMAR_ATE = 10
MARGEM_ALARME_LOCAL = 2.0


@dataclass
class Borda:
    carga: str
    ultima_valida: float | None = None
    minutos_sem_leitura: int = 0
    descartes: int = 0
    estimadas: int = 0

    def processar(self, leitura: dict) -> dict:
        bruto = leitura.get("temp")
        valido = bruto is not None and not (isinstance(bruto, float) and math.isnan(bruto))
        if valido and not (FAIXA_FISICA[0] <= bruto <= FAIXA_FISICA[1]):
            valido = False
            self.descartes += 1
        elif (
            valido
            and self.ultima_valida is not None
            and self.minutos_sem_leitura < ESTIMAR_ATE
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
