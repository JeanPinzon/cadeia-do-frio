from dataclasses import dataclass


@dataclass(frozen=True)
class Carga:
    nome: str
    minimo: float
    maximo: float
    setpoint: float
    vida_h: float
    q10: float


CARGAS = {
    "vacinas": Carga("vacinas", 2.0, 8.0, 5.0, vida_h=24 * 30, q10=3.0),
    "laticinios": Carga("laticinios", 0.0, 7.0, 3.0, vida_h=24 * 10, q10=2.5),
    "carnes": Carga("carnes", -2.0, 4.0, 1.0, vida_h=24 * 6, q10=2.5),
}
