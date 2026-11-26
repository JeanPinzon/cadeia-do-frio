from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from frio.cargas import CARGAS

BANCO = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("saida/frio.db")
COR = {"ok": "#2E7D32", "atencao": "#F9A825", "critico": "#C62828"}
NOME_ALERTA = {
    "deriva_compressor": "Compressor perdendo eficiência",
    "previsao_violacao": "Violação prevista",
    "porta_aberta": "Porta aberta",
    "temperatura_fora": "Temperatura fora da faixa",
}

st.set_page_config(page_title="Cadeia do frio", page_icon="❄️", layout="wide")


def ler() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not BANCO.exists():
        return pd.DataFrame(), pd.DataFrame()
    with sqlite3.connect(f"file:{BANCO}?mode=ro", uri=True) as db:
        return (
            pd.read_sql("select * from leituras order by caminhao, minuto", db),
            pd.read_sql("select * from alertas order by minuto desc", db),
        )


def situacao(ultima: pd.Series, alertas: pd.DataFrame) -> str:
    tipos = set(alertas.loc[alertas.caminhao == ultima.caminhao, "tipo"])
    c = CARGAS[ultima.carga]
    if ultima.temp is not None and not pd.isna(ultima.temp) and ultima.temp > c.maximo and not ultima.porta:
        return "critico"
    if "previsao_violacao" in tipos or "temperatura_fora" in tipos:
        return "critico"
    if tipos:
        return "atencao"
    return "ok"


def grafico(df: pd.DataFrame, carga: str) -> go.Figure:
    c = CARGAS[carga]
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.06, row_heights=[0.5, 0.25, 0.25],
                        subplot_titles=("Temperatura interna (°C)", "Ciclo do compressor", "Excesso acumulado de ciclo (CUSUM)"))
    fig.add_hrect(y0=c.minimo, y1=c.maximo, fillcolor="#2E7D32", opacity=0.08, line_width=0, row=1, col=1)
    fig.add_trace(go.Scatter(x=df.minuto, y=df.temp, name="interna", line=dict(color="#1565C0")), row=1, col=1)
    abertas = df[df.porta == 1]
    fig.add_trace(go.Scatter(x=abertas.minuto, y=[c.maximo + 0.5] * len(abertas), mode="markers", name="porta aberta",
                             marker=dict(color="#F9A825", size=5, symbol="square")), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.minuto, y=df.ciclo, name="ciclo", line=dict(color="#6A1B9A")), row=2, col=1)
    fig.add_trace(go.Scatter(x=df.minuto, y=df.cusum, name="CUSUM", line=dict(color="#C62828")), row=3, col=1)
    fig.add_hline(y=3.0, line_dash="dot", line_color="#C62828", row=3, col=1)
    fig.update_yaxes(range=[0, 1.05], row=2, col=1)
    fig.update_xaxes(title_text="minuto da viagem", row=3, col=1)
    fig.update_layout(height=560, margin=dict(l=10, r=10, t=30, b=10), showlegend=False)
    return fig


@st.fragment(run_every=2)
def painel() -> None:
    leituras, alertas = ler()
    st.title("❄️ Cadeia do frio: central de operações")
    if leituras.empty:
        st.info("Nenhuma leitura ainda. Rode `frio demo` com o broker ligado.")
        return

    ultimas = leituras.groupby("caminhao").tail(1).set_index("caminhao", drop=False)
    ultimas["situacao"] = [situacao(r, alertas) for _, r in ultimas.iterrows()]

    cols = st.columns(len(ultimas))
    for col, (_, u) in zip(cols, ultimas.iterrows()):
        c = CARGAS[u.carga]
        with col:
            st.markdown(f"<div style='border-left:6px solid {COR[u.situacao]};padding-left:10px'>"
                        f"<b>{u.caminhao}</b> · {u.carga}<br>"
                        f"<span style='font-size:28px'>{'sem leitura' if pd.isna(u.temp) else f'{u.temp:.1f} °C'}</span> <small>faixa {c.minimo:g} a {c.maximo:g}</small></div>",
                        unsafe_allow_html=True)
            ef = "medindo" if pd.isna(u.eficiencia) else f"{u.eficiencia:.0%}"
            st.caption(f"Compressor: {ef} do normal · vida útil restante: {u.vida_restante * c.vida_h / 24:.1f} dias")
            if not pd.isna(u.minutos_ate_violar):
                st.error(f"Sai da faixa em ~{u.minutos_ate_violar:.0f} min")

    esq, dir_ = st.columns([3, 2])
    with esq:
        fig = go.Figure(go.Scattermap(
            lat=ultimas.lat, lon=ultimas.lon, mode="markers+text", text=ultimas.caminhao, textposition="top center",
            marker=dict(size=16, color=[COR[s] for s in ultimas.situacao]),
        ))
        fig.update_layout(map=dict(style="open-street-map", center=dict(lat=-29.8, lon=-51.4), zoom=7),
                          height=360, margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig, width="stretch")
    with dir_:
        st.subheader("Alertas e ações sugeridas")
        if alertas.empty:
            st.success("Nenhum alerta.")
        for _, a in alertas.head(8).iterrows():
            st.markdown(f"**{a.caminhao}** · minuto {a.minuto} · {NOME_ALERTA.get(a.tipo, a.tipo)}  \n{a.mensagem}  \n➜ {a.recomendacao}")

    escolhido = st.session_state.get("caminhao") or ultimas.index[0]
    df = leituras[leituras.caminhao == escolhido]
    st.subheader(f"Viagem do {escolhido}")
    st.plotly_chart(grafico(df, df.carga.iloc[0]), width="stretch")


st.sidebar.selectbox("Caminhão no gráfico", sorted(ler()[0].get("caminhao", pd.Series(dtype=str)).unique()) or [""], key="caminhao")
painel()
