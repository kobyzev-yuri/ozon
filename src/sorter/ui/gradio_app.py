"""Gradio UI — фаза 4. Запуск: python -m sorter.ui.gradio_app"""

from __future__ import annotations


def launch() -> None:
    try:
        import gradio as gr
    except ImportError as exc:
        raise SystemExit("Install gradio: pip install gradio") from exc

    with gr.Blocks(title="Ozon Sorter Digital Twin") as demo:
        gr.Markdown(
            "# Ozon Sorter — Digital Twin\n"
            "Два окна: 3D/видео ленты + CV overlay + `events.jsonl`.\n"
            "Скелет UI — подключить `main_loop` и MJPEG после ТЗ."
        )
        gr.Markdown("См. `ARCHITECTURE.md` и `python main.py --help`.")

    demo.launch()


if __name__ == "__main__":
    launch()
