import pytest

from frio.avaliacao import avaliar_viagem, treinar


@pytest.fixture(scope="module")
def modelo():
    return treinar(8)


def test_viagem_normal_sem_alerta_de_ia(modelo):
    r, _, _ = avaliar_viagem(20003, "nenhuma", modelo)
    assert r.ia_falsos == 0


def test_compressor_avisa_antes_de_sair_da_faixa(modelo):
    r, _, alertas = avaliar_viagem(20131, "compressor", modelo)
    assert r.violacao > 0
    assert 0 <= r.ia < r.violacao
    assert any("Antecipar as entregas" in a.recomendacao for a in alertas)


def test_porta_aberta_avisa_em_poucos_minutos(modelo):
    r, _, _ = avaliar_viagem(20160, "porta", modelo)
    assert r.ia_tipo == "porta_aberta"
    assert r.ia - r.inicio_falha <= 5


def test_bau_quente_sem_porta_nao_justifica_compressor_no_maximo(modelo):
    # primeira rodada do teste: o CUSUM voltava a zero com a carga já a 18 °C e nunca alertava
    r, serie, _ = avaliar_viagem(20081, "compressor", modelo)
    assert r.ia >= 0
    assert serie["cusum"].iloc[-1] > 3
