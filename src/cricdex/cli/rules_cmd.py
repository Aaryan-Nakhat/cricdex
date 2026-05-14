"""`cricdex rules` — citation-grounded Q&A over the parsed rule corpus."""

from __future__ import annotations

import typer

from cricdex.cli._shared import EXIT_MISSING_CRED, console, die

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command("ask", help="Ask a rules question — LLM-backed, citations attached.")
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

    if not (settings.llm_api_key or settings.llm_api_base):
        die(
            "no LLM credential — run `cricdex config set llm_api_key <key>` "
            "or `cricdex init`",
            code=EXIT_MISSING_CRED,
        )
    fmt_list = [f.strip() for f in formats.split(",") if f.strip()] or None
    res = answer(question, formats=fmt_list, top_k=top_k)
    c = console()
    c.print(f"\n[bold]Q.[/bold] {question}\n")
    c.print(f"[bold green]A.[/bold green] {res.get('answer', '')}\n")
    citations = res.get("citations") or []
    if citations:
        c.print("[bold]Citations:[/bold]")
        for src_id, law in citations:
            c.print(f"  • {sources.label_for(src_id)}, clause {law}")
