"""`cricdex rules` — citation-grounded Q&A over the parsed rule corpus.

Renderer mirrors the Streamlit Rules Chat page: intro panel, Q/A pair
with bold answer, human-readable citation list with publisher labels.
"""

from __future__ import annotations

import typer

from cricdex.cli import _copy, _render
from cricdex.cli._shared import EXIT_MISSING_CRED, console, die

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command("ask", help="Ask a rules question — Gemini-backed, citations attached.")
def ask(
    question: str = typer.Argument(..., metavar="QUESTION"),
    formats: str = typer.Option(
        "", "--formats", help="comma-sep (ipl,t20i,test,…) — filters source corpus"
    ),
    top_k: int = typer.Option(8, "--top-k"),
) -> None:
    from cricdex.config import settings
    from cricdex.rules import sources
    from cricdex.rules.qa import answer

    if not (settings.gemini_api_key or settings.gemini_tmp_url):
        die(
            "no Gemini credential — run `cricdex config set gemini_api_key <key>` "
            "or `cricdex init`",
            code=EXIT_MISSING_CRED,
        )

    _render.header("Rules Q&A", subtitle=f"formats: {formats or 'all'}  ·  top_k: {top_k}")
    _render.intro_panel(_copy.RULES_INTRO, title="Rules")

    fmt_list = [f.strip() for f in formats.split(",") if f.strip()] or None
    with _render.spinner("retrieving + ranking + answering"):
        res = answer(question, formats=fmt_list, top_k=top_k)

    c = console()
    c.print(f"[bold]Q.[/bold] {question}\n")
    c.print(f"[bold green]A.[/bold green] {res.get('answer', '')}\n")
    citations = res.get("citations") or []
    if citations:
        _render.section("Citations")
        for src_id, law in citations:
            label = sources.label_for(src_id)
            c.print(f"  [dim]•[/dim] [bold]{label}[/bold], clause [cyan]{law}[/cyan]")
    _render.footnote(
        "Citations are human-readable publisher labels — open the PDF "
        "via the source URL on the dashboard for the full clause."
    )
