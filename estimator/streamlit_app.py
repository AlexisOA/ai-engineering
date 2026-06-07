import httpx
import streamlit as st


API_URL = "http://localhost:8000/api/v1/estimate"
STREAM_URL = "http://localhost:8000/api/v1/estimate/stream"


st.set_page_config(
    page_title="Estimator Chat",
    page_icon="💬",
)

st.title("Estimator Chat")
st.caption("Chat básico en Streamlit que llama al endpoint FastAPI de estimación normal o en Streaming")

if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": (
                "Hola. Pega una transcripción de una reunión "
                "y te devolveré una estimación usando el backend FastAPI."
            ),
        }
    ]

use_stream = st.sidebar.toggle("Respuesta en streaming", value=True)

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])


prompt = st.chat_input("Escribe algo...")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        if use_stream:
            try:
                def token_generator():
                    with httpx.stream(
                        "POST",
                        STREAM_URL,
                        json={"transcription": prompt},
                        timeout=120,
                    ) as response:
                        response.raise_for_status()
                        for chunk in response.iter_text():
                            if chunk:
                                yield chunk

                full_response = st.write_stream(token_generator())
                st.session_state.messages.append(
                    {"role": "assistant", "content": full_response}
                )

            except httpx.ConnectError:
                error_message = "No puedo conectar con el backend FastAPI."
                st.error(error_message)
                st.session_state.messages.append(
                    {"role": "assistant", "content": error_message}
                )
            except httpx.HTTPStatusError as exc:
                error_message = f"El backend respondió con error HTTP {exc.response.status_code}."
                st.error(error_message)
                st.session_state.messages.append(
                    {"role": "assistant", "content": error_message}
                )
            except httpx.TimeoutException:
                error_message = "La petición tardó demasiado tiempo. Inténtalo de nuevo..."
                st.error(error_message)
                st.session_state.messages.append(
                    {"role": "assistant", "content": error_message}
                )
        else:
            with st.spinner("Generando estimación..."):
                try:
                    response = httpx.post(
                        API_URL,
                        json={"transcription": prompt},
                        timeout=60,
                    )
                    response.raise_for_status()
                    data = response.json()

                    estimation = data.get("estimation", "No se recibió una estimación.")
                    st.markdown(estimation)

                    st.session_state.messages.append(
                        {"role": "assistant", "content": estimation}
                    )

                except httpx.ConnectError:
                    error_message = "No puedo conectar con el backend FastAPI."
                    st.error(error_message)
                    st.session_state.messages.append(
                        {"role": "assistant", "content": error_message}
                    )
                except httpx.HTTPStatusError as exc:
                    error_message = f"El backend respondió con error HTTP {exc.response.status_code}."
                    st.error(error_message)
                    st.session_state.messages.append(
                        {"role": "assistant", "content": error_message}
                    )
                except httpx.TimeoutException:
                    error_message = "La petición tardó demasiado tiempo. Inténtalo de nuevo..."
                    st.error(error_message)
                    st.session_state.messages.append(
                        {"role": "assistant", "content": error_message}
                    )
