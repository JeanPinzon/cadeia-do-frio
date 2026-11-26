from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error
from threadpoolctl import threadpool_limits

from .cargas import CARGAS

COLUNAS = ["delta_externa", "desvio", "porta", "porta_recente"]


def atributos(df: pd.DataFrame) -> pd.DataFrame:
    setpoint = df["carga"].map(lambda c: CARGAS[c].setpoint)
    porta = df["porta"].astype(float)
    return pd.DataFrame(
        {
            "delta_externa": df["temp_externa"] - setpoint,
            "desvio": df["temp"] - setpoint,
            "porta": porta,
            # minutos de porta aberta nos últimos 10, porque o baú leva um tempo para se recuperar
            "porta_recente": porta.rolling(10, min_periods=1).sum(),
        }
    )


class ModeloCiclo:
    def __init__(self) -> None:
        self.reg = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, random_state=0)
        self.erro_medio: float | None = None

    def treinar(self, viagens: list[pd.DataFrame]) -> "ModeloCiclo":
        x = pd.concat([atributos(v) for v in viagens], ignore_index=True)
        y = pd.concat([v["ciclo"] for v in viagens], ignore_index=True)
        ok = x["desvio"].notna().to_numpy()
        xs = x[COLUNAS].to_numpy()[ok]
        self.reg.fit(xs, y[ok])
        self.erro_medio = float(mean_absolute_error(y[ok], self.reg.predict(xs)))
        return self

    def prever(self, x: pd.DataFrame | dict) -> np.ndarray:
        linhas = np.array([[x[c] for c in COLUNAS]]) if isinstance(x, dict) else x[COLUNAS].to_numpy()
        with threadpool_limits(1):
            return np.clip(self.reg.predict(linhas), 0, 1)

    def salvar(self, caminho: Path) -> None:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(pickle.dumps(self))

    @staticmethod
    def carregar(caminho: Path) -> "ModeloCiclo":
        return pickle.loads(caminho.read_bytes())
