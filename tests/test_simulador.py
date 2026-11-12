from frio.cargas import CARGAS
from frio.simulador import simular_viagem


def test_mesma_semente_mesma_viagem():
    a, b = simular_viagem(7, "compressor"), simular_viagem(7, "compressor")
    assert a.equals(b)


def test_viagem_normal_fica_na_faixa_com_porta_fechada():
    v = simular_viagem(3, "nenhuma", ruido_sensor=False)
    c = CARGAS[v.carga[0]]
    fechada = v["porta"].rolling(16, min_periods=1).max() == 0
    assert v.loc[fechada, "verdade_temp"].max() < c.maximo
    assert v["verdade_inicio"].iloc[0] == -1


def test_compressor_perde_eficiencia_a_partir_do_inicio():
    v = simular_viagem(4, "compressor")
    ini = v["verdade_inicio"].iloc[0]
    assert (v.loc[: ini - 1, "verdade_eficiencia"] == 1).all()
    assert v["verdade_eficiencia"].iloc[-1] < 0.3


def test_porta_fica_aberta_com_caminhao_andando():
    v = simular_viagem(5, "porta")
    ini = v["verdade_inicio"].iloc[0]
    trecho = v.iloc[ini + 2 : ini + 15]
    assert (trecho["porta"] == 1).all() and (trecho["parada"] == "").all()
