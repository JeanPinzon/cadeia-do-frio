"""Transforma cada alerta numa ação sugerida para a central de operações."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .simulador import CDS, _distancia_km

if TYPE_CHECKING:
    from .monitor import Monitor


def cd_mais_proximo(lat: float, lon: float) -> tuple[str, float]:
    nome, pos = min(CDS.items(), key=lambda kv: _distancia_km((lat, lon), kv[1]))
    return nome, _distancia_km((lat, lon), pos)


def recomendar(tipo: str, mon: "Monitor", leitura: dict) -> str:
    cd, km = cd_mais_proximo(leitura["lat"], leitura["lon"])
    if tipo == "deriva_compressor":
        ef = mon.eficiencia_estimada()
        quanto = f" (rendendo cerca de {ef:.0%} do normal)" if ef else ""
        return (
            f"Compressor perdendo eficiência{quanto}. A carga ainda está na faixa. "
            f"Antecipar as entregas restantes e agendar manutenção; se piorar, desviar para o {cd} ({km:.0f} km)."
        )
    if tipo == "previsao_violacao":
        return f"Compressor no limite. Desviar agora para o {cd} ({km:.0f} km) e transferir a carga."
    if tipo == "porta_aberta":
        return "Ligar para o motorista e pedir para parar e conferir a porta do baú."
    if tipo == "temperatura_fora":
        return f"Carga fora da faixa. Registrar a excursão e avaliar o lote no {cd} ({km:.0f} km) antes de entregar."
    return ""
