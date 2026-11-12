import math

from frio.borda import ESTIMAR_ATE, Borda


def leitura(temp):
    return {"temp": temp, "minuto": 0}


def test_pico_e_descartado_e_repete_a_ultima():
    b = Borda("vacinas")
    b.processar(leitura(5.0))
    t = b.processar(leitura(85.0))
    assert t["temp"] == 5.0 and t["temp_status"] == "estimada"
    assert b.descartes == 1


def test_buraco_curto_estima_e_longo_fica_sem_leitura():
    b = Borda("vacinas")
    b.processar(leitura(5.0))
    status = [b.processar(leitura(math.nan))["temp_status"] for _ in range(ESTIMAR_ATE + 2)]
    assert status[:ESTIMAR_ATE] == ["estimada"] * ESTIMAR_ATE
    assert status[-1] == "sem_leitura"


def test_depois_de_buraco_longo_aceita_novo_patamar():
    b = Borda("vacinas")
    b.processar(leitura(5.0))
    for _ in range(ESTIMAR_ATE + 1):
        b.processar(leitura(None))
    t = b.processar(leitura(12.0))  # salto de 7 °C, mas depois de muito tempo sem dado
    assert t["temp"] == 12.0 and t["temp_status"] == "ok"


def test_alarme_local_so_acima_da_margem():
    b = Borda("vacinas")  # máximo 8 °C, alarme local a partir de 10 °C
    assert not b.processar(leitura(9.5))["alarme_local"]
    assert b.processar(leitura(10.5))["alarme_local"]
