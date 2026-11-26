from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SAIDA = Path("saida")
MODELO = SAIDA / "modelo.pkl"
BANCO = SAIDA / "frio.db"


def _modelo():
    from .avaliacao import treinar
    from .modelo import ModeloCiclo

    if MODELO.exists():
        return ModeloCiclo.carregar(MODELO)
    print("Treinando o modelo de ciclo com 40 viagens normais...")
    m = treinar()
    m.salvar(MODELO)
    return m


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="frio", description="Monitoramento da cadeia do frio com IoT e IA")
    p.add_argument("--host", default="localhost", help="broker MQTT")
    p.add_argument("--porta", type=int, default=1883)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("treinar", help="treina o modelo de ciclo do compressor")
    av = sub.add_parser("avaliar", help="roda a avaliação com viagens simuladas")
    av.add_argument("--conjunto", choices=["ajuste", "teste"], default="teste")
    d = sub.add_parser("demo", help="simulador + borda + nuvem ao vivo (precisa do broker)")
    d.add_argument("--velocidade", type=float, default=5.0, help="minutos simulados por segundo")
    sub.add_parser("painel", help="abre o painel no navegador")
    sub.add_parser("borda", help="só o gateway")
    sub.add_parser("nuvem", help="só o monitor na nuvem")
    s = sub.add_parser("simular", help="só o simulador da frota")
    s.add_argument("--velocidade", type=float, default=5.0)

    a = p.parse_args(argv)
    if a.cmd == "treinar":
        from .avaliacao import treinar

        m = treinar()
        m.salvar(MODELO)
        print(f"Modelo salvo em {MODELO} (erro médio do ciclo: {m.erro_medio:.3f})")
    elif a.cmd == "avaliar":
        from .avaliacao import rodar

        print(json.dumps(rodar(SAIDA, a.conjunto), indent=2, ensure_ascii=False))
    elif a.cmd == "demo":
        from .servicos import demo

        demo(a.host, a.porta, BANCO, _modelo(), a.velocidade)
    elif a.cmd == "painel":
        painel = Path(__file__).with_name("painel.py")
        subprocess.run([sys.executable, "-m", "streamlit", "run", str(painel), "--", str(BANCO.resolve())], check=False)
    elif a.cmd in ("borda", "nuvem"):
        from . import servicos

        cli = servicos.borda(a.host, a.porta) if a.cmd == "borda" else servicos.nuvem(a.host, a.porta, BANCO, _modelo())
        cli.loop_forever()
    elif a.cmd == "simular":
        from .servicos import simular

        simular(a.host, a.porta, a.velocidade)


if __name__ == "__main__":
    main()
