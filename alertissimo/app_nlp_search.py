"""Streamlit entry page for natural-language transient investigations."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import streamlit as st
from dotenv import load_dotenv

from alertissimo.app_search import load_demo_search_data, render_dsl_entry
from alertissimo.nlp.prompt import NLP_TO_DSL_SYSTEM_PROMPT


load_dotenv(Path(__file__).parents[1] / ".env", override=False)

SYSTEM_PROMPT = NLP_TO_DSL_SYSTEM_PROMPT


def translate_to_dsl(*, host: str, model: str, request_text: str) -> str:
    """Translate one request through the local Ollama model."""
    payload = json.dumps(
        {
            "model": model,
            "stream": False,
            "think": False,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": request_text},
            ],
            "options": {"temperature": 0, "seed": 42, "num_predict": 256},
        }
    ).encode("utf-8")
    http_request = Request(
        host.rstrip("/") + "/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(http_request, timeout=600) as response:
        result = json.loads(response.read().decode("utf-8"))
    dsl = str(result["message"]["content"]).strip()
    if dsl.startswith("```") and dsl.endswith("```"):
        dsl = "\n".join(dsl.splitlines()[1:-1]).strip()
    return dsl


def main() -> None:
    st.set_page_config(page_title="Alertissimo · NLP search", page_icon="🔭", layout="wide")
    st.title("Start with natural language")
    st.caption(
        "Describe the astronomical request. Alertissimo will translate it to DSL; "
        "you can review it and continue through the normal live execution flow."
    )

    if "nlp_dsl" not in st.session_state:
        with st.form("nlp-search"):
            request_text = st.text_area(
                "Astronomy request",
                height=150,
                placeholder="Example: Find the latest 3 ZTF objects through ALeRCE within 5 arcseconds of RA 124.88 and Dec -6.02.",
            )
            submitted = st.form_submit_button("Translate to DSL", type="primary")
        if not submitted:
            return
        if not request_text.strip():
            st.warning("Enter an astronomy request first.")
            return
        host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
        model = os.getenv("OLLAMA_MODEL", "alertissimo-qwen3-qlora")
        try:
            with st.spinner(f"Translating with {model}…"):
                dsl = translate_to_dsl(
                    host=host,
                    model=model,
                    request_text=request_text.strip(),
                )
        except (HTTPError, URLError, TimeoutError, KeyError, ValueError) as error:
            st.error(f"NLP translation failed: {error}")
            st.caption(
                f"Check that Ollama is running at {host} and that model "
                f"`{model}` exists."
            )
            return
        st.session_state["nlp_request"] = request_text.strip()
        st.session_state["nlp_dsl"] = dsl
        # Seed the existing DSL block editor; its submit button then enters the
        # exact same execution and continuation flow as app_search.py.
        st.session_state["nlp_dsl_block_dsl"] = dsl
        st.rerun()

    st.subheader("Generated DSL")
    st.caption("Review the translation below, then click the DSL editor's execute button.")
    st.code(st.session_state["nlp_dsl"], language="text")
    if st.button("Start over", key="nlp-start-over"):
        for key in tuple(st.session_state):
            if key == "nlp_dsl" or key == "nlp_request" or key.startswith("nlp_dsl_"):
                del st.session_state[key]
        st.rerun()

    candidates, _ = load_demo_search_data()
    render_dsl_entry(
        candidates,
        title="Review and execute DSL",
        context="The generated DSL is loaded into the same execution flow as the DSL mode on the search page.",
        key="nlp_dsl",
    )


if __name__ == "__main__":
    main()
