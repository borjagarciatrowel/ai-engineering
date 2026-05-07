import json
import os
import time

import httpx
import streamlit as st

BACKEND_URL = os.getenv("BACKEND_URL", "http://estimator:8000")

st.set_page_config(
    page_title="Estimador de Software",
    page_icon="🏗️",
    layout="wide",
)

if "messages" not in st.session_state:
    st.session_state.messages = []
if "last_metrics" not in st.session_state:
    st.session_state.last_metrics = None


def stream_from_api(transcription: str):
    """Call FastAPI /api/v1/estimate/stream and yield text tokens.

    Stores final metadata in st.session_state._pending_metrics.
    Raises httpx.HTTPError on connection failure.
    """
    with httpx.stream(
        "POST",
        f"{BACKEND_URL}/api/v1/estimate/stream",
        json={"transcription": transcription},
        timeout=120,
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line:
                continue
            chunk = json.loads(line)
            if "t" in chunk:
                yield chunk["t"]
            elif chunk.get("done"):
                st.session_state._pending_metrics = {
                    "model": chunk.get("model", "unknown"),
                    "input_tokens": chunk.get("usage", {}).get("input_tokens", 0),
                    "output_tokens": chunk.get("usage", {}).get("output_tokens", 0),
                }
            elif "error" in chunk:
                yield f"\n\n⚠️ Error: {chunk['error']}"


# Sidebar
with st.sidebar:
    st.header("📊 Métricas")

    if st.session_state.last_metrics:
        m = st.session_state.last_metrics
        st.metric("Modelo", m["model"])
        col1, col2 = st.columns(2)
        col1.metric("Tokens entrada", m["input_tokens"])
        col2.metric("Tokens salida", m["output_tokens"])
        st.metric("Tiempo de respuesta", f"{m['response_time']:.2f}s")

    st.divider()
    if st.button("🗑️ Limpiar conversación", use_container_width=True):
        st.session_state.messages = []
        st.session_state.last_metrics = None
        st.rerun()


# Main chat
st.title("🏗️ Estimador de Software")
st.caption("Pega la transcripción de una reunión y obtén una estimación detallada del proyecto.")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("Pega aquí la transcripción de la reunión..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        start_time = time.time()
        full_response = st.write_stream(stream_from_api(prompt))
        response_time = time.time() - start_time

    st.session_state.messages.append({"role": "assistant", "content": full_response})

    pending = st.session_state.pop("_pending_metrics", {})
    st.session_state.last_metrics = {
        "model": pending.get("model", "unknown"),
        "input_tokens": pending.get("input_tokens", 0),
        "output_tokens": pending.get("output_tokens", 0),
        "response_time": response_time,
    }
    st.rerun()
