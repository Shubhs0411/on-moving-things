#!/usr/bin/env python3
"""
FreightMind AI — Interactive CLI Demo
Multi-agent transportation compliance intelligence.

Usage:
    python demo/cli.py                    # interactive mode
    python demo/cli.py demo               # run scripted demo sequence
    python demo/cli.py eval               # run eval harness
    python demo/cli.py query "..."        # single query
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

load_dotenv()

# ── Theme ─────────────────────────────────────────────────────────────────────
theme = Theme({
    "brand": "bold #00D4FF",
    "compliant": "bold green",
    "non_compliant": "bold red",
    "conditional": "bold yellow",
    "critical": "bold red on dark_red",
    "high": "bold red",
    "medium": "bold yellow",
    "low": "bold green",
    "agent": "bold cyan",
    "citation": "italic #888888",
    "header": "bold white on #1a1a2e",
})
console = Console(theme=theme, width=120)
app = typer.Typer(help="FreightMind AI — Transportation Compliance Intelligence")


BANNER = """
[brand]
███████╗██████╗ ███████╗██╗ ██████╗ ██╗  ██╗████████╗███╗   ███╗██╗███╗   ██╗██████╗
██╔════╝██╔══██╗██╔════╝██║██╔════╝ ██║  ██║╚══██╔══╝████╗ ████║██║████╗  ██║██╔══██╗
█████╗  ██████╔╝█████╗  ██║██║  ███╗███████║   ██║   ██╔████╔██║██║██╔██╗ ██║██║  ██║
██╔══╝  ██╔══██╗██╔══╝  ██║██║   ██║██╔══██║   ██║   ██║╚██╔╝██║██║██║╚██╗██║██║  ██║
██║     ██║  ██║███████╗██║╚██████╔╝██║  ██║   ██║   ██║ ╚═╝ ██║██║██║ ╚████║██████╔╝
╚═╝     ╚═╝  ╚═╝╚══════╝╚═╝ ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚═╝     ╚═╝╚═╝╚═╝  ╚═══╝╚═════╝
[/brand]
[dim]Multi-Agent Transportation Compliance Intelligence  ·  FMCSA · DOT · CSA · 49 CFR[/dim]
"""

DEMO_QUERIES = [
    {
        "title": "Carrier Vetting — Suspicious Carrier",
        "query": "Run a full safety check on carrier DOT 2345678. They want to haul hazmat for us.",
        "agent": "carrier_vetting",
        "why": "Tests: CSA alert detection, HM flag, conditional safety rating, crash history",
    },
    {
        "title": "Driver Qualification — Disqualified Driver",
        "query": "Check driver CDL-OH-005678 — can they drive today?",
        "agent": "driver_qualification",
        "why": "Tests: Clearinghouse PROHIBITED, positive drug test, expired medical cert, DQ file gaps",
    },
    {
        "title": "CSA Scoring — Corrective Action Plan",
        "query": "DOT 2345678 has HOS score 82.1 and vehicle maintenance 91.3. Give me an improvement plan.",
        "agent": "csa_scoring",
        "why": "Tests: Multi-BASIC alert interpretation, specific corrective actions, DataQs awareness",
    },
    {
        "title": "Regulation Oracle — HOS Question",
        "query": "A driver has been on duty for 13 hours and driven 10. Can they drive 2 more hours if there's bad weather?",
        "agent": "compliance_oracle",
        "why": "Tests: Adverse conditions exemption (49 CFR 395.1(b)(1)), multi-rule interaction",
    },
    {
        "title": "Risk Assessment — New Entrant",
        "query": "A new carrier with 5 trucks, unrated, and only 12 inspections wants to haul for us. How do I evaluate them?",
        "agent": "compliance_oracle",
        "why": "Tests: New entrant risk framework, uncertainty handling, due diligence guidance",
    },
]


def _print_banner():
    console.print(BANNER)
    console.print()


def _print_architecture():
    table = Table(title="System Architecture", box=box.ROUNDED, border_style="brand")
    table.add_column("Layer", style="bold cyan", width=25)
    table.add_column("Component", width=30)
    table.add_column("Purpose", width=55)

    table.add_row(
        "System of Understanding",
        "ChromaDB + RegulationLoader",
        "FMCSA/DOT regulations as semantic knowledge graph. RAG over 49 CFR.",
    )
    table.add_row(
        "System of Velocity",
        "LangGraph + 4 Claude Agents",
        "Router → specialist agents → synthesizer. Ship in a day, change tomorrow.",
    )
    table.add_row(
        "System of Velocity",
        "FastAPI (/v1/compliance/query)",
        "Sub-second compliance checks via REST. Composable, observable.",
    )
    table.add_row(
        "System of Continuous Improvement",
        "EvalHarness (25 test cases)",
        "Every response scored. Pass rate tracked. Failures surfaced immediately.",
    )
    table.add_row(
        "System of Continuous Improvement",
        "AgentTracer (JSONL)",
        "Every tool call logged. Latency, tokens, reasoning — all observable.",
    )
    console.print(table)
    console.print()


def _print_agents():
    agents = [
        Panel(
            "[agent]ComplianceOracle[/agent]\n[dim]Model: claude-opus-4-7[/dim]\n\nRegulatory Q&A with full CFR citation. Semantic search over FMCSA/DOT knowledge base.",
            title="[bold]Regulation Oracle[/bold]",
            border_style="cyan",
            width=55,
        ),
        Panel(
            "[agent]CarrierVetting[/agent]\n[dim]Model: claude-sonnet-4-6[/dim]\n\nOperating authority, insurance, CSA scores, crash history, OOS rates.",
            title="[bold]Carrier Vetting[/bold]",
            border_style="cyan",
            width=55,
        ),
        Panel(
            "[agent]DriverQualification[/agent]\n[dim]Model: claude-sonnet-4-6[/dim]\n\nCDL/medical cert validity, Clearinghouse status, DQ file completeness (49 CFR 391).",
            title="[bold]Driver Qual[/bold]",
            border_style="cyan",
            width=55,
        ),
        Panel(
            "[agent]CSAScoring[/agent]\n[dim]Model: claude-sonnet-4-6[/dim]\n\nBASIC score interpretation, intervention thresholds, corrective action plans.",
            title="[bold]CSA Scoring[/bold]",
            border_style="cyan",
            width=55,
        ),
    ]
    console.print(Columns(agents[:2]))
    console.print(Columns(agents[2:]))
    console.print()


def _run_query_demo(query_info: dict, orchestrator: "FreightMindOrchestrator") -> None:
    console.rule(f"[bold]{query_info['title']}[/bold]")
    console.print(f"[dim]Testing: {query_info['why']}[/dim]")
    console.print()

    console.print(Panel(query_info["query"], title="[bold]Query[/bold]", border_style="white"))

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task(f"[cyan]Routing → {query_info['agent']} agent...", total=None)
        t0 = time.perf_counter()
        result = orchestrator.invoke(query_info["query"])
        latency = (time.perf_counter() - t0) * 1000
        progress.update(task, description=f"[green]Done ({latency:.0f}ms)")

    intent = result.get("intent")
    agent_used = result.get("metadata", {}).get("agent", "unknown")
    meta_table = Table(box=None, show_header=False, padding=(0, 2))
    meta_table.add_column(style="dim")
    meta_table.add_column()
    meta_table.add_row("Intent detected:", f"[bold]{intent.value if intent else 'N/A'}[/bold]")
    meta_table.add_row("Agent dispatched:", f"[agent]{agent_used}[/agent]")
    meta_table.add_row("Latency:", f"{latency:.0f}ms")
    console.print(meta_table)
    console.print()

    response = result.get("response", "")
    console.print(Panel(Markdown(response), title="[bold]Compliance Response[/bold]", border_style="green"))
    console.print()


@app.command()
def demo():
    """Run the full scripted demo sequence (5 queries, all agent types)."""
    _print_banner()
    _print_architecture()

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        console.print("[red]ERROR: ANTHROPIC_API_KEY not set. Copy .env.example to .env and add your key.[/red]")
        console.print("[dim]Without an API key, the demo runs in preview mode showing architecture only.[/dim]")
        _print_agents()
        return

    from src.graph.orchestrator import FreightMindOrchestrator
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console, transient=True) as p:
        t = p.add_task("[cyan]Initializing FreightMind AI (loading knowledge base)...", total=None)
        orchestrator = FreightMindOrchestrator()
        p.update(t, description="[green]System ready")

    _print_agents()

    console.print(Panel(
        f"Running [bold]{len(DEMO_QUERIES)}[/bold] demo queries across all agent types.\n"
        "Each query exercises a different compliance domain.",
        title="[bold]Demo Sequence[/bold]",
        border_style="brand",
    ))
    console.print()

    for i, query_info in enumerate(DEMO_QUERIES, 1):
        console.print(f"\n[dim]Query {i}/{len(DEMO_QUERIES)}[/dim]")
        _run_query_demo(query_info, orchestrator)
        if i < len(DEMO_QUERIES):
            console.input("[dim]Press Enter for next query...[/dim]")

    # Show observability stats at end
    from src.observability.tracer import get_tracer
    stats = get_tracer().session_stats()
    stats_table = Table(title="Session Observability", box=box.ROUNDED, border_style="brand")
    stats_table.add_column("Metric", style="bold")
    stats_table.add_column("Value", style="cyan")
    stats_table.add_row("Total agent calls", str(stats.get("total_calls", 0)))
    stats_table.add_row("Avg latency", f"{stats.get('avg_latency_ms', 0):.0f}ms")
    stats_table.add_row("Input tokens used", str(stats.get("total_input_tokens", 0)))
    stats_table.add_row("Output tokens used", str(stats.get("total_output_tokens", 0)))
    stats_table.add_row("Error rate", stats.get("error_rate", "0.0%"))
    console.print(stats_table)


@app.command()
def eval(
    category: str = typer.Option(None, help="Filter by category: carrier_vetting, driver_qualification, csa_scoring, regulation_lookup, risk_assessment"),
    n: int = typer.Option(None, help="Number of cases to run"),
):
    """Run the evaluation harness against the live system."""
    _print_banner()
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        console.print("[red]ANTHROPIC_API_KEY not set.[/red]")
        raise typer.Exit(1)

    from src.graph.orchestrator import FreightMindOrchestrator
    from src.eval.harness import EvalHarness
    from src.eval.test_cases import EVAL_SUITE
    from src.models.domain import QueryIntent

    console.print("[cyan]Loading FreightMind AI...[/cyan]")
    orchestrator = FreightMindOrchestrator()
    harness = EvalHarness(invoke_fn=orchestrator.invoke)

    cat_filter = None
    if category:
        try:
            cat_filter = QueryIntent(category)
        except ValueError:
            console.print(f"[red]Unknown category: {category}[/red]")
            raise typer.Exit(1)

    cases = EVAL_SUITE
    if cat_filter:
        cases = [c for c in cases if c.category == cat_filter]
    if n:
        cases = cases[:n]

    console.print(f"[cyan]Running {len(cases)} eval cases...[/cyan]\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        console=console,
    ) as progress:
        task = progress.add_task("Running evals...", total=len(cases))
        results_list = []
        for case in cases:
            progress.update(task, description=f"[cyan]{case.id}: {case.description[:40]}...")
            import time as _time
            from src.eval.harness import EvalHarness as _EH
            t0 = _time.perf_counter()
            result = harness._run_single(case)
            results_list.append((case, result))
            progress.advance(task)

    summary = harness._compute_summary(
        [r for _, r in results_list],
        [c for c, _ in results_list],
    )

    # Results table
    result_table = Table(title="Eval Results", box=box.ROUNDED)
    result_table.add_column("ID", style="bold", width=10)
    result_table.add_column("Description", width=45)
    result_table.add_column("Score", width=8)
    result_table.add_column("Latency", width=10)
    result_table.add_column("Status", width=10)

    for case, result in results_list:
        status = "[compliant]PASS[/compliant]" if result.passed else "[non_compliant]FAIL[/non_compliant]"
        score_color = "green" if result.score >= 0.8 else "yellow" if result.score >= 0.6 else "red"
        result_table.add_row(
            result.case_id,
            case.description,
            f"[{score_color}]{result.score:.2f}[/{score_color}]",
            f"{result.latency_ms:.0f}ms",
            status,
        )
    console.print(result_table)

    # Summary panel
    passed = summary["passed"]
    total = summary["total_cases"]
    pass_pct = passed / total * 100 if total else 0
    color = "green" if pass_pct >= 80 else "yellow" if pass_pct >= 60 else "red"
    console.print(Panel(
        f"[{color}]{summary['pass_rate']}[/{color}]  ·  Avg score: {summary['avg_score']}  ·  Avg latency: {summary['avg_latency_ms']}ms",
        title="[bold]Summary[/bold]",
        border_style=color,
    ))

    if summary["failed_cases"]:
        console.print("\n[bold red]Failed cases:[/bold red]")
        for fc in summary["failed_cases"]:
            console.print(f"  [red]✗[/red] {fc['id']} (score={fc['score']:.2f}) — missing: {fc.get('keyword_misses', [])}")


@app.command()
def query(q: str = typer.Argument(..., help="Compliance question to ask")):
    """Run a single compliance query."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        console.print("[red]ANTHROPIC_API_KEY not set.[/red]")
        raise typer.Exit(1)

    from src.graph.orchestrator import FreightMindOrchestrator
    console.print("[dim]Loading...[/dim]")
    orchestrator = FreightMindOrchestrator()
    t0 = time.perf_counter()
    result = orchestrator.invoke(q)
    latency = (time.perf_counter() - t0) * 1000
    console.print(Panel(Markdown(result["response"]), title=f"[bold]{q[:60]}[/bold]", border_style="cyan"))
    console.print(f"[dim]Intent: {result.get('intent')} | Latency: {latency:.0f}ms[/dim]")


@app.command()
def interactive():
    """Start an interactive compliance Q&A session."""
    _print_banner()
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        console.print("[red]ANTHROPIC_API_KEY not set. See .env.example.[/red]")
        raise typer.Exit(1)

    from src.graph.orchestrator import FreightMindOrchestrator
    console.print("[cyan]Loading FreightMind AI...[/cyan]")
    orchestrator = FreightMindOrchestrator()
    console.print("[green]Ready. Type your compliance question or 'exit' to quit.[/green]\n")

    while True:
        try:
            q = console.input("[bold cyan]freightmind>[/bold cyan] ").strip()
            if q.lower() in ("exit", "quit", "q"):
                break
            if not q:
                continue
            t0 = time.perf_counter()
            result = orchestrator.invoke(q)
            latency = (time.perf_counter() - t0) * 1000
            console.print(Panel(
                Markdown(result["response"]),
                title=f"[dim]{result.get('intent', {}).value if result.get('intent') else 'response'} · {latency:.0f}ms[/dim]",
                border_style="green",
            ))
        except (KeyboardInterrupt, EOFError):
            break
    console.print("[dim]Goodbye.[/dim]")


if __name__ == "__main__":
    app()
