"""
Presentation Studio — local Streamlit app (127.0.0.1 only).

Run: streamlit run presentation_studio/app.py
Or:  .\\scripts\\run_presentation_studio.ps1
"""

from __future__ import annotations

import json
import tempfile
from datetime import date
from pathlib import Path

import streamlit as st

from presentation_studio.ai_coach import run_ai_coach
from presentation_studio.config import get_settings
from presentation_studio.content_parser import load_plain_text, load_source
from presentation_studio.deck_builder import DeckBuildOptions, build_deck

st.set_page_config(
    page_title="Presentation Studio",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

settings = get_settings()


def _init_state() -> None:
    if "doc" not in st.session_state:
        st.session_state.doc = None
    if "pptx_path" not in st.session_state:
        st.session_state.pptx_path = None
    if "pptx_bytes" not in st.session_state:
        st.session_state.pptx_bytes = None
    if "chat" not in st.session_state:
        st.session_state.chat = []


def _generate_deck(
    doc: dict,
    output_path: Path,
    footer: str,
    client_line: str,
    brand_pptx: Path,
    brand_json: Path,
) -> Path:
    options = DeckBuildOptions(
        output_path=output_path,
        brand_pptx=brand_pptx,
        brand_json=brand_json,
        footer=footer,
        client_line=client_line,
    )
    return build_deck(doc, options)


def main() -> None:
    _init_state()
    st.title("Presentation Studio")
    st.caption(
        "Build brand-formatted PowerPoint decks from Word, PDF, or plain text. "
        "Runs **locally only** on your machine."
    )

    with st.sidebar:
        st.header("Settings")
        api_key = st.text_input(
            "OpenAI API key",
            value=settings.openai_api_key or "",
            type="password",
            help="Stored in session only unless set in .env",
        )
        if api_key:
            settings.openai_api_key = api_key

        brand_pptx = st.text_input(
            "Brand template (.pptx)",
            value=str(settings.brand_pptx),
        )
        brand_json = st.text_input(
            "Brand tokens (.json)",
            value=str(settings.brand_json),
        )
        output_dir = st.text_input(
            "Default output folder",
            value=str(settings.default_output_dir),
        )
        footer = st.text_input("Slide footer", value=settings.default_footer)
        client_line = st.text_input("Cover client line", value="PwC")
        output_name = st.text_input(
            "Output filename",
            value=f"presentation_{date.today().isoformat()}.pptx",
        )

        st.divider()
        st.markdown("**Local server**")
        st.code(
            f"http://{settings.streamlit_host}:{settings.streamlit_port}",
            language=None,
        )
        if not settings.has_llm and not api_key:
            st.warning("Set OPENAI_API_KEY in `.env` or sidebar for AI edits.")

    tab_source, tab_generate, tab_ai = st.tabs(["1. Source content", "2. Generate deck", "3. AI assistant"])

    with tab_source:
        col_u, col_t = st.columns(2)
        with col_u:
            st.subheader("Upload document")
            upload = st.file_uploader(
                "Word (.docx) or PDF (.pdf)",
                type=["docx", "pdf"],
            )
            title_override = st.text_input("Title override (optional)")
            subtitle_override = st.text_input("Subtitle override (optional)")

            if st.button("Parse uploaded file", type="primary", disabled=upload is None):
                suffix = Path(upload.name).suffix.lower()
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(upload.getvalue())
                    tmp_path = Path(tmp.name)
                try:
                    st.session_state.doc = load_source(
                        path=tmp_path,
                        title=title_override or None,
                        subtitle=subtitle_override or None,
                    )
                    st.success(f"Parsed **{upload.name}** — ready to generate.")
                except Exception as exc:
                    st.error(str(exc))

        with col_t:
            st.subheader("Plain text")
            plain = st.text_area(
                "Paste narrative (first line = title, second = subtitle)",
                height=280,
                placeholder="Project Vienna\nDiagnostic and Discovery Phase\n\n1. What? ...",
            )
            if st.button("Parse plain text", disabled=not plain.strip()):
                st.session_state.doc = load_plain_text(plain)
                if title_override:
                    st.session_state.doc["title"] = title_override
                if subtitle_override:
                    st.session_state.doc["subtitle"] = subtitle_override
                st.success("Plain text parsed.")

        if st.session_state.doc:
            with st.expander("Parsed content preview (JSON)", expanded=False):
                st.json(
                    {
                        k: st.session_state.doc[k]
                        for k in st.session_state.doc
                        if k != "sections"
                    }
                )

    with tab_generate:
        st.subheader("Generate PowerPoint")
        if not st.session_state.doc:
            st.info("Parse a document or plain text in the **Source content** tab first.")
        else:
            custom_path = st.text_input(
                "Save to path (optional)",
                placeholder=r"C:\Users\...\presentation.pptx",
            )
            if st.button("Generate presentation", type="primary"):
                out_dir = Path(output_dir)
                out_dir.mkdir(parents=True, exist_ok=True)
                out_path = Path(custom_path) if custom_path.strip() else out_dir / output_name
                if out_path.suffix.lower() != ".pptx":
                    out_path = out_path.with_suffix(".pptx")
                try:
                    result = _generate_deck(
                        st.session_state.doc,
                        out_path,
                        footer,
                        client_line,
                        Path(brand_pptx),
                        Path(brand_json),
                    )
                    st.session_state.pptx_path = result
                    st.session_state.pptx_bytes = result.read_bytes()
                    st.success(f"Saved to **{result}**")
                except Exception as exc:
                    st.error(f"Generation failed: {exc}")

            if st.session_state.pptx_bytes:
                st.download_button(
                    "Download .pptx",
                    data=st.session_state.pptx_bytes,
                    file_name=Path(st.session_state.pptx_path or "presentation.pptx").name,
                    mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                )
                if st.session_state.pptx_path:
                    st.caption(f"On disk: `{st.session_state.pptx_path}`")

    with tab_ai:
        st.subheader("AI assistant")
        st.markdown(
            "Ask for content changes, slide emphasis, or **where to save** the file. "
            'Example: *"Shorten opportunities on slide 6 and save to '
            r'C:\Users\...\deck_v2.pptx"*'
        )

        for msg in st.session_state.chat:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        prompt = st.chat_input("Describe changes or save location...")
        if prompt and st.session_state.doc:
            st.session_state.chat.append({"role": "user", "content": prompt})
            with st.spinner("Thinking..."):
                try:
                    result = run_ai_coach(
                        user_prompt=prompt,
                        doc=st.session_state.doc,
                        settings=settings,
                        last_output_path=st.session_state.pptx_path,
                    )
                except Exception as exc:
                    st.session_state.chat.append(
                        {"role": "assistant", "content": f"Error: {exc}"}
                    )
                    st.rerun()

            st.session_state.doc = result["doc"]
            reply = result["message"]
            if result.get("patches"):
                reply += f"\n\n_Patches applied: {json.dumps(result['patches'], indent=2)[:800]}_"

            save_path = result.get("save_path")
            should_regen = result.get("regenerate", False)
            ai_footer = result.get("footer") or footer
            ai_client = result.get("client_line") or client_line

            if should_regen or save_path:
                out_dir = Path(output_dir)
                out_dir.mkdir(parents=True, exist_ok=True)
                target = save_path or (
                    st.session_state.pptx_path
                    or out_dir / output_name
                )
                if target.suffix.lower() != ".pptx":
                    target = target.with_suffix(".pptx")
                try:
                    built = _generate_deck(
                        st.session_state.doc,
                        target,
                        ai_footer,
                        ai_client,
                        Path(brand_pptx),
                        Path(brand_json),
                    )
                    st.session_state.pptx_path = built
                    st.session_state.pptx_bytes = built.read_bytes()
                    reply += f"\n\n**Deck saved:** `{built}`"
                except Exception as exc:
                    reply += f"\n\n_Generation error: {exc}_"
            elif save_path and not should_regen and st.session_state.pptx_bytes:
                try:
                    save_path.parent.mkdir(parents=True, exist_ok=True)
                    save_path.write_bytes(st.session_state.pptx_bytes)
                    st.session_state.pptx_path = save_path
                    reply += f"\n\n**Copied to:** `{save_path}`"
                except Exception as exc:
                    reply += f"\n\n_Save error: {exc}_"

            st.session_state.chat.append({"role": "assistant", "content": reply})
            st.rerun()


if __name__ == "__main__":
    main()
