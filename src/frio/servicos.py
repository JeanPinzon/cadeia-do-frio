"""Pipeline ao vivo sobre MQTT.

    simulador ──frio/<caminhão>/bruto──▶ borda ──frio/<caminhão>/tratado──▶ nuvem ──▶ SQLite ──▶ painel
                                          │                                  │
                                          └──frio/<caminhão>/alarme_local     └──frio/<caminhão>/alerta

Na vida real a borda roda num gateway dentro de cada caminhão. Aqui um único
processo faz o papel dos gateways de toda a frota.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt
import pandas as pd

from .borda import Borda
from .modelo import ModeloCiclo
from .monitor import Monitor
from .simulador import simular_viagem

QOS = 1  # pelo menos uma vez: o celular do caminhão cai, a leitura não pode sumir

FROTA_DEMO = [
    # (caminhão, semente, falha, carga)
    ("IOT-1021", 20094, "compressor", "vacinas"),
    ("IOT-2087", 20155, "porta", "laticinios"),
    ("IOT-3310", 20003, "nenhuma", "carnes"),
    ("IOT-4452", 20011, "nenhuma", "vacinas"),
]


def _cliente(nome: str, host: str, porta: int) -> mqtt.Client:
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=nome)
    c.connect(host, porta, keepalive=30)
    return c


def _json(obj: dict) -> str:
    return json.dumps(obj, default=str, ensure_ascii=False)


# ---------------------------------------------------------------- simulador
def simular(host: str, porta: int, velocidade: float, parar: threading.Event | None = None) -> dict[str, int]:
    """Publica um minuto de cada caminhão a cada ``1/velocidade`` segundos.

    Devolve o último minuto publicado de cada caminhão."""
    viagens = []
    inicio = pd.Timestamp.now().floor("min")
    for nome, semente, falha, carga in FROTA_DEMO:
        v = simular_viagem(semente, falha, carga=carga, caminhao=nome, inicio=inicio)
        viagens.append(v.drop(columns=[c for c in v.columns if c.startswith("verdade_")]))
    cli = _cliente("simulador", host, porta)
    cli.loop_start()
    for m in range(max(len(v) for v in viagens)):
        for v in viagens:
            if m < len(v):
                linha = v.iloc[m].to_dict()
                linha["temp"] = None if pd.isna(linha["temp"]) else linha["temp"]
                cli.publish(f"frio/{linha['caminhao']}/bruto", _json(linha), qos=QOS)
        if parar is not None and parar.is_set():
            break
        time.sleep(1 / velocidade)
    cli.loop_stop()
    cli.disconnect()
    return {v["caminhao"].iloc[0]: min(m, len(v) - 1) for v in viagens}


# ---------------------------------------------------------------- borda
def borda(host: str, porta: int) -> mqtt.Client:
    gateways: dict[str, Borda] = {}
    em_alarme: set[str] = set()

    def ao_receber(cli, _u, msg):
        l = json.loads(msg.payload)
        g = gateways.setdefault(l["caminhao"], Borda(l["carga"]))
        t = g.processar(l)
        cli.publish(f"frio/{l['caminhao']}/tratado", _json(t), qos=QOS)
        # alarme local: sirene/luz na cabine; só publica quando liga ou desliga
        if t["alarme_local"] != (l["caminhao"] in em_alarme):
            em_alarme.symmetric_difference_update({l["caminhao"]})
            aviso = {"minuto": t["minuto"], "temp": t["temp"], "ligado": t["alarme_local"]}
            cli.publish(f"frio/{l['caminhao']}/alarme_local", _json(aviso), qos=QOS)

    cli = _cliente("borda", host, porta)
    cli.on_message = ao_receber
    cli.subscribe("frio/+/bruto", qos=QOS)
    return cli


# ---------------------------------------------------------------- nuvem
ESQUEMA = """
create table if not exists leituras (
    caminhao text, carga text, minuto int, ts text, temp real, temp_status text,
    umidade real, porta int, temp_externa real, ciclo real, lat real, lon real, parada text,
    cusum real, eficiencia real, minutos_ate_violar real, vida_restante real,
    primary key (caminhao, minuto)
);
create table if not exists alertas (
    caminhao text, carga text, minuto int, ts text, tipo text, mensagem text, recomendacao text
);
"""


def abrir_banco(caminho: Path) -> sqlite3.Connection:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(caminho, check_same_thread=False)
    # WAL: o painel lê enquanto a nuvem escreve, e o commit não espera o disco a cada leitura
    db.executescript("pragma journal_mode=wal; pragma synchronous=normal;" + ESQUEMA)
    return db


def nuvem(host: str, porta: int, banco: Path, modelo: ModeloCiclo) -> mqtt.Client:
    db = abrir_banco(banco)
    db.executescript("delete from leituras; delete from alertas;")
    monitores: dict[str, Monitor] = {}
    trava = threading.Lock()

    def ao_receber(cli, _u, msg):
        l = json.loads(msg.payload)
        mon = monitores.setdefault(l["caminhao"], Monitor(l["caminhao"], l["carga"], modelo))
        if l["minuto"] <= mon.minuto and l["minuto"] > 0:
            return  # QoS 1 pode entregar repetido
        e = mon.atualizar(l)
        with trava:
            db.execute(
                "insert or replace into leituras values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    l["caminhao"], l["carga"], l["minuto"], l["ts"], l["temp"], l["temp_status"], l["umidade"],
                    l["porta"], l["temp_externa"], l["ciclo"], l["lat"], l["lon"], l["parada"],
                    e["cusum"], e["eficiencia_estimada"], e["minutos_ate_violar"], e["vida_restante"],
                ),
            )
            for a in e["novos_alertas"]:
                db.execute(
                    "insert into alertas values (?,?,?,?,?,?,?)",
                    (l["caminhao"], l["carga"], a["minuto"], l["ts"], a["tipo"], a["mensagem"], a["recomendacao"]),
                )
                cli.publish(f"frio/{l['caminhao']}/alerta", _json(a), qos=QOS)
            db.commit()

    cli = _cliente("nuvem", host, porta)
    cli.on_message = ao_receber
    cli.subscribe("frio/+/tratado", qos=QOS)
    return cli


def demo(host: str, porta: int, banco: Path, modelo: ModeloCiclo, velocidade: float) -> None:
    """Sobe borda e nuvem, roda o simulador até o fim das viagens."""
    clientes = [borda(host, porta), nuvem(host, porta, banco, modelo)]
    for c in clientes:
        c.loop_start()
    time.sleep(1)
    try:
        ultimos = simular(host, porta, velocidade)
        # espera a nuvem processar a fila antes de desligar
        db = sqlite3.connect(banco)
        for _ in range(600):
            feitos = dict(db.execute("select caminhao, max(minuto) from leituras group by caminhao").fetchall())
            if all(feitos.get(c, -1) >= m for c, m in ultimos.items()):
                break
            time.sleep(0.5)
    finally:
        for c in clientes:
            c.loop_stop()
            c.disconnect()
