import time

import streamlit as st
from dotenv import load_dotenv

from app.config import get_settings
from app.context.examples import ESTIMATION_EXAMPLES
from app.services.llm_service import MAX_TOKENS, build_system_prompt

load_dotenv()

st.set_page_config(
    page_title="Estimador de Software",
    page_icon="🏗️",
    layout="wide",
)

SYSTEM_PROMPT = build_system_prompt()

if "messages" not in st.session_state:
    st.session_state.messages = []
if "last_metrics" not in st.session_state:
    st.session_state.last_metrics = None


def stream_openai(messages: list[dict]) -> tuple:
    from openai import OpenAI

    settings = get_settings()
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    usage_data = {}

    def generator():
        stream = client.chat.completions.create(
            model=settings.LLM_MODEL,
            max_tokens=MAX_TOKENS,
            stream=True,
            stream_options={"include_usage": True},
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, *messages],
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
            if chunk.usage:
                usage_data["input_tokens"] = chunk.usage.prompt_tokens
                usage_data["output_tokens"] = chunk.usage.completion_tokens
        usage_data.setdefault("input_tokens", 0)
        usage_data.setdefault("output_tokens", 0)

    return generator(), usage_data, settings.LLM_MODEL


def stream_anthropic(messages: list[dict]) -> tuple:
    from anthropic import Anthropic

    settings = get_settings()
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    usage_data = {}

    def generator():
        with client.messages.stream(
            model=settings.LLM_MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                yield text
            msg = stream.get_final_message()
            usage_data["input_tokens"] = msg.usage.input_tokens
            usage_data["output_tokens"] = msg.usage.output_tokens

    return generator(), usage_data, settings.LLM_MODEL


# Sidebar — Level 3
with st.sidebar:
    st.header("🔍 Contexto CAG")

    with st.expander("System Prompt", expanded=False):
        st.text_area(
            "system_prompt",
            SYSTEM_PROMPT,
            height=250,
            disabled=True,
            label_visibility="collapsed",
        )

    with st.expander(f"Ejemplos de referencia ({len(ESTIMATION_EXAMPLES)})", expanded=False):
        for i, ex in enumerate(ESTIMATION_EXAMPLES):
            st.markdown(f"**Ejemplo {i + 1}:** {ex['meeting_summary'][:150]}…")

    if st.session_state.last_metrics:
        st.divider()
        st.subheader("📊 Última llamada")
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


# Main chat interface
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
        settings = get_settings()
        start_time = time.time()

        if settings.LLM_PROVIDER == "anthropic":
            gen, usage_data, model = stream_anthropic(st.session_state.messages)
        else:
            gen, usage_data, model = stream_openai(st.session_state.messages)

        full_response = st.write_stream(gen)
        response_time = time.time() - start_time

    st.session_state.messages.append({"role": "assistant", "content": full_response})
    st.session_state.last_metrics = {
        "model": model,
        "input_tokens": usage_data.get("input_tokens", 0),
        "output_tokens": usage_data.get("output_tokens", 0),
        "response_time": response_time,
    }
    st.rerun()
