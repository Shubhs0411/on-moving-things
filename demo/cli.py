#!/usr/bin/env python3
"""
FreightMind AI — Interactive CLI Demo
Multi-agent transportation compliance intelligence.

Usage:
    python demo/cli.py                    # interactive mode
    python demo/cli.py demo               # run scripted demo sequence
    python demo/cli.py eval               # run eval harness
    python demo/cli.py query "..."        # single query
    python demo/cli.py status             # show system status
    python demo/cli.py graph DOT_NUMBER   # show carrier graph context
    python demo/cli.py ingest PATH        # ingest a PDF or text file
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

    # Observability stats at end
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
def status():
    """Show system status: API keys, knowledge base, graph, and FMCSA mode."""
    _print_banner()

    t = Table(title="System Status", box=box.ROUNDED, border_style="brand")
    t.add_column("Component", style="bold", width=28)
    t.add_column("Status", width=20)
    t.add_column("Detail", width=55)

    # API keys
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    fmcsa_key = os.getenv("FMCSA_WEB_KEY", "")
    t.add_row(
        "Anthropic API Key",
        "[green]SET[/green]" if api_key else "[red]NOT SET[/red]",
        f"...{api_key[-6:]}" if api_key else "Add to .env file",
    )
    t.add_row(
        "FMCSA Web Key",
        "[green]SET (live mode)[/green]" if fmcsa_key else "[yellow]NOT SET (mock)[/yellow]",
        f"...{fmcsa_key[-6:]}" if fmcsa_key else "Get free key at ai.fmcsa.dot.gov",
    )

    # Knowledge base
    try:
        from src.knowledge.vectorstore import FreightKnowledgeBase
        kb = FreightKnowledgeBase()
        kb.ingest()
        count = kb.count
        t.add_row("Vector Store (ChromaDB)", "[green]OK[/green]", f"{count} regulation chunks indexed")
    except Exception as e:
        t.add_row("Vector Store (ChromaDB)", "[red]ERROR[/red]", str(e)[:50])

    # Knowledge graph
    try:
        from src.knowledge.graph import get_graph
        g = get_graph()
        s = g.stats()
        by_type = s.get("by_type", {})
        t.add_row(
            "Knowledge Graph",
            "[green]OK[/green]",
            f"{s['nodes']} nodes · {s['edges']} edges · "
            f"{by_type.get('Carrier',0)} carriers · {by_type.get('Driver',0)} drivers · "
            f"{by_type.get('Violation',0)} violations",
        )
    except Exception as e:
        t.add_row("Knowledge Graph", "[red]ERROR[/red]", str(e)[:50])

    # FMCSA API
    try:
        from src.knowledge.fmcsa_api import FMCSAClient
        client = FMCSAClient()
        fs = client.status()
        t.add_row(
            "FMCSA API",
            "[green]LIVE[/green]" if client.is_live() else "[yellow]MOCK[/yellow]",
            f"{fs['mode']} · {fs['mock_carriers_loaded']} mock carriers loaded",
        )
    except Exception as e:
        t.add_row("FMCSA API", "[red]ERROR[/red]", str(e)[:50])

    # Docling
    try:
        import docling  # noqa: F401
        import importlib.metadata
        ver = importlib.metadata.version("docling")
        t.add_row("Docling (PDF parsing)", "[green]AVAILABLE[/green]", f"v{ver}")
    except Exception:
        t.add_row("Docling (PDF parsing)", "[yellow]NOT INSTALLED[/yellow]", "pip install docling  (optional)")

    console.print(t)

    # Top cited regulations from graph
    try:
        from src.knowledge.graph import get_graph
        g = get_graph()
        s = g.stats()
        top_regs = s.get("top_cited_regulations_overall", [])
        if top_regs:
            console.print()
            rt = Table(title="Most Cited Regulations (Graph-wide)", box=box.SIMPLE, border_style="dim")
            rt.add_column("CFR Citation", style="citation", width=35)
            rt.add_column("Times Cited", style="bold cyan", width=15)
            for r in top_regs:
                rt.add_row(r["citation"], str(r["total_citations"]))
            console.print(rt)
    except Exception:
        pass


@app.command()
def graph(
    dot: str = typer.Argument(..., help="DOT number to inspect (e.g. 2345678)"),
    mermaid: bool = typer.Option(False, "--mermaid", help="Output Mermaid diagram markup"),
):
    """Show knowledge graph context for a carrier DOT number."""
    from src.knowledge.graph import get_graph
    g = get_graph()

    if mermaid:
        console.print(g.export_mermaid(dot_number=dot))
        return

    ctx = g.get_graph_context_for_carrier(dot)
    violations = g.get_carrier_violation_history(dot)
    top_regs = g.get_top_cited_regulations(dot)

    console.print(Panel(Markdown(ctx), title=f"[bold]Graph: Carrier DOT {dot}[/bold]", border_style="cyan"))

    if violations:
        vt = Table(title="Violation History", box=box.SIMPLE_HEAVY)
        vt.add_column("Date", width=12)
        vt.add_column("Citation", style="citation", width=25)
        vt.add_column("Description", width=50)
        vt.add_column("Sev", width=5)
        vt.add_column("OOS", width=5)
        for v in violations[:15]:
            oos = "D+V" if v.get("oos_driver") and v.get("oos_vehicle") else (
                "Drv" if v.get("oos_driver") else ("Veh" if v.get("oos_vehicle") else ""))
            vt.add_row(
                str(v.get("date", ""))[:10],
                v.get("citation", ""),
                v.get("description", "")[:48],
                str(v.get("severity", "")),
                oos,
            )
        console.print(vt)

    if top_regs:
        rt = Table(title="Top Cited Regulations", box=box.SIMPLE)
        rt.add_column("Citation", style="citation", width=30)
        rt.add_column("Count", style="bold cyan", width=8)
        rt.add_column("Total Severity", width=15)
        for r in top_regs:
            rt.add_row(r["citation"], str(r["count"]), str(r["total_severity"]))
        console.print(rt)


@app.command()
def ingest(
    path: str = typer.Argument(..., help="Path to PDF or text file to ingest"),
    category: str = typer.Option("REGULATION", help="Category: REGULATION, INSPECTION, HOS, DQ, CSA"),
    title: str = typer.Option("", help="Document title (defaults to filename)"),
):
    """Ingest a PDF or text file into the knowledge base."""
    p = Path(path)
    if not p.exists():
        console.print(f"[red]File not found: {path}[/red]")
        raise typer.Exit(1)

    from src.knowledge.ingester import DocumentIngester
    from src.knowledge.graph import get_graph

    doc_title = title or p.stem
    graph = get_graph()
    ingester = DocumentIngester(graph=graph)

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  console=console, transient=True) as prog:
        task = prog.add_task(f"[cyan]Ingesting {p.name}...", total=None)
        if p.suffix.lower() == ".pdf":
            result = ingester.ingest_pdf(p, category=category)
        else:
            result = ingester.ingest_text(p.read_text(encoding="utf-8", errors="replace"),
                                          title=doc_title, category=category)
        prog.update(task, description="[green]Done")

    if "error" in result:
        console.print(f"[red]Error: {result['error']}[/red]")
        raise typer.Exit(1)

    console.print(Panel(
        f"[green]Ingested:[/green] {p.name}\n"
        f"Chunks added: [bold]{result.get('chunks_added', 0)}[/bold]\n"
        f"Category: {result.get('category', category)}\n"
        f"Source: {result.get('source', path)}",
        title="[bold]Ingest Complete[/bold]",
        border_style="green",
    ))


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

    results_list: list[tuple] = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        console=console,
    ) as progress:
        task = progress.add_task("Running evals...", total=len(cases))
        for case in cases:
            progress.update(task, description=f"[cyan]{case.id}: {case.description[:40]}...")
            result = harness._run_single(case)
            results_list.append((case, result))
            progress.advance(task)

    summary = harness._compute_summary(
        [r for _, r in results_list],
        [c for c, _ in results_list],
    )

    result_table = Table(title="Eval Results", box=box.ROUNDED)
    result_table.add_column("ID", style="bold", width=10)
    result_table.add_column("Description", width=45)
    result_table.add_column("Score", width=8)
    result_table.add_column("Latency", width=10)
    result_table.add_column("Status", width=10)

    for case, result in results_list:
        status_str = "[compliant]PASS[/compliant]" if result.passed else "[non_compliant]FAIL[/non_compliant]"
        score_color = "green" if result.score >= 0.8 else "yellow" if result.score >= 0.6 else "red"
        result_table.add_row(
            result.case_id,
            case.description,
            f"[{score_color}]{result.score:.2f}[/{score_color}]",
            f"{result.latency_ms:.0f}ms",
            status_str,
        )
    console.print(result_table)

    passed = summary["passed"]
    total = summary["total_cases"]
    pass_pct = passed / total * 100 if total else 0
    color = "green" if pass_pct >= 80 else "yellow" if pass_pct >= 60 else "red"
    console.print(Panel(
        f"[{color}]{summary['pass_rate']}[/{color}]  ·  Avg score: {summary['avg_score']}  ·  Avg latency: {summary['avg_latency_ms']}ms",
        title="[bold]Summary[/bold]",
        border_style=color,
    ))

    if summary.get("failed_cases"):
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
    intent = result.get("intent")
    console.print(Panel(Markdown(result["response"]), title=f"[bold]{q[:60]}[/bold]", border_style="cyan"))
    console.print(f"[dim]Intent: {intent.value if intent else 'N/A'} | Latency: {latency:.0f}ms[/dim]")


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
            intent = result.get("intent")
            console.print(Panel(
                Markdown(result["response"]),
                title=f"[dim]{intent.value if intent else 'response'} · {latency:.0f}ms[/dim]",
                border_style="green",
            ))
        except (KeyboardInterrupt, EOFError):
            break
    console.print("[dim]Goodbye.[/dim]")


if __name__ == "__main__":
    app()
