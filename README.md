# Cadeia do frio: monitoramento com IoT e IA

Projeto final de Internet das Coisas e Aplicações de IA (Big Data), Unisinos, 2026/2.

Caminhões refrigerados levam vacinas, laticínios e carnes. O alarme comum toca quando a temperatura passa do limite, ou seja, quando a carga já está estragando. Este projeto usa os sensores do baú para avisar antes. Um modelo aprende quanto o compressor deveria trabalhar para o calor daquele momento e percebe quando ele começa a trabalhar demais, horas antes de a temperatura subir.

## O que tem aqui

| Peça | Arquivo | O que faz |
|---|---|---|
| Simulador | `src/frio/simulador.py` | Frota de baús com física térmica simples, rotas reais no RS, entregas com porta aberta e falhas injetadas (compressor perdendo eficiência, porta mal fechada, picos e buracos do sensor) |
| Borda | `src/frio/borda.py` | Gateway do caminhão: descarta picos, estima leituras ausentes por até 10 min e liga o alarme local, que funciona sem internet |
| Modelo | `src/frio/modelo.py` | Gradient boosting que prevê o ciclo normal do compressor a partir da temperatura externa, da porta e do desvio do setpoint |
| Monitor | `src/frio/monitor.py` | Na nuvem, minuto a minuto: CUSUM sobre o excesso de ciclo, porta aberta fora de ponto de entrega (GPS), previsão de quando a carga sai da faixa e vida útil restante (Q10) |
| Decisão | `src/frio/decisao.py` | Ação sugerida para cada alerta, com o centro de distribuição mais próximo |
| MQTT | `src/frio/servicos.py` | Simulador, borda e nuvem conversando pelo broker (Mosquitto, QoS 1) e gravando no SQLite |
| Painel | `src/frio/painel.py` | Streamlit: mapa da frota, situação de cada caminhão, alertas com ação e gráficos da viagem |
| Avaliação | `src/frio/avaliacao.py` | 200 viagens de teste com gabarito, comparando a IA com o alarme de limite fixo |

```
simulador ──MQTT frio/<caminhão>/bruto──▶ borda ──frio/<caminhão>/tratado──▶ nuvem ──▶ SQLite ──▶ painel
                                          └─ alarme local                     └─ frio/<caminhão>/alerta
```

## Como rodar

Precisa de Python 3.12 ou mais novo, [uv](https://docs.astral.sh/uv/) e Docker (só para o broker).

```bash
uv sync
uv run frio treinar            # treina o modelo com 40 viagens normais
uv run frio avaliar            # 200 viagens de teste, resultados em saida/
uv run pytest                  # testes
```

Demonstração ao vivo, em dois terminais:

```bash
docker compose up -d                # broker MQTT na porta 1883
uv run frio demo --velocidade 5     # 5 minutos simulados por segundo
```

```bash
uv run frio painel                  # abre em http://localhost:8501
```

A demo roda quatro caminhões: o IOT-1021 com o compressor falhando, o IOT-2087 com a porta mal fechada e dois normais. Os serviços também sobem separados (`frio simular`, `frio borda`, `frio nuvem`), com `--host` apontando para outro broker.

## Resultados (conjunto de teste, 200 viagens)

| | IA | Limite fixo | Limite que ignora entregas |
|---|---|---|---|
| Viagens normais com alarme falso (de 80) | 0 | 18 | 0 |
| Falha de compressor: avisou antes de a carga sair da faixa (de 66) | 65 | 63 (1) | 3 |
| Falha de compressor: antecedência mediana | 125 min | 19 min (1) | 0 min |
| Porta mal fechada: detectadas (de 50) e atraso mediano | 50, 2 min | 50, 7 min | 26, 48 min |

(1) O limite fixo só "avisa antes" porque toca nas aberturas de porta das entregas, as mesmas que geram os 18 alarmes falsos. Quem recebe esse alarme não tem como saber se é entrega ou compressor.

Os parâmetros do monitor foram ajustados em outro conjunto de 80 viagens (`frio avaliar --conjunto ajuste`). O teste rodou uma vez, com tudo congelado. As figuras do relatório saem de `uv run python relatorio/figuras.py`.

## Limites

Os dados são simulados, e a física do baú é simples. O sinal que torna a detecção possível é o ciclo do compressor. Nem todo equipamento de refrigeração informa esse dado; num baú real ele viria do controlador do equipamento ou de um sensor de corrente no compressor.
