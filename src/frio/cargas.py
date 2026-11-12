"""Tipos de carga refrigerada e suas faixas de temperatura."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Carga:
    nome: str
    minimo: float  # °C
    maximo: float  # °C
    setpoint: float  # °C em que o baú é regulado
    vida_h: float  # vida útil a setpoint, em horas
    q10: float  # quanto a degradação acelera a cada 10 °C acima do setpoint


CARGAS = {
    "vacinas": Carga("vacinas", 2.0, 8.0, 5.0, vida_h=24 * 30, q10=3.0),
    "laticinios": Carga("laticinios", 0.0, 7.0, 3.0, vida_h=24 * 10, q10=2.5),
    "carnes": Carga("carnes", -2.0, 4.0, 1.0, vida_h=24 * 6, q10=2.5),
}
