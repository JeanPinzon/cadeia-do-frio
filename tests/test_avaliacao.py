import numpy as np

from frio.avaliacao import _episodios, _primeiro


def test_episodios_um_disparo_por_episodio():
    acima = np.array([0, 1, 1, 0, 1, 1, 1, 0], dtype=bool)
    assert _episodios(acima, 1) == [1, 4]
    assert _episodios(acima, 3) == [6]


def test_primeiro_separa_falsos_de_validos():
    assert _primeiro([10, 50, 80], inicio=40) == (50, 1)
    assert _primeiro([10, 50], inicio=-1) == (-1, 2)
