"""`cricdex rules` — citation-grounded Q&A over the parsed rule corpus."""

from __future__ import annotations

import typer

from cricdex.cli._shared import EXIT_MISSING_CRED, console, die

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command("ask", help="Ask a rules question — Gemini-backed, citations attached.")
def ask(
    question: str = typer.Argument(..., metavar="QUESTION"),
    formats: str = typer.Option(
        "", "--formats", help="comma-sep (ipl,t20i,test,…) — filters source corpus"
    ),
    top_k: int = typer.Option(5, "--top-k"),
) -> None:
    from cricdex.config import settings
    from cricdex.rules.qa import answer, resolve_formats

    if not (settings.gemini_api_key or settings.gemini_tmp_url):
        die(
            "no Gemini credential — run `cricdex config set gemini_api_key <key>` "
            "or `cricdex init`",
            code=EXIT_MISSING_CRED,
        )
    src_ids = resolve_formats([f.strip() for f in formats.split(",") if f.strip()] or None)
    res = answer(question, source_ids=src_ids, top_k=top_k)
    c = console()
    c.print(f"\n[bold]Q.[/bold] {question}\n")
    c.print(f"[bold green]A.[/bold green] {res.get('answer', '')}\n")
    cits = res.get("citations") or []
    if cits:
        c.print("[bold]Citations:[/bold]")
        for cit in cits:
            c.print(
                f"  • {cit.get('source_id', '?')} {cit.get('law_number', '')}: {cit.get('title', '')[:80]}"
            )
