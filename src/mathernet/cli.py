from __future__ import annotations

import argparse
import errno
import json
import shutil
import sys
from pathlib import Path

from .api import create_server
from .config import Settings
from .errors import MathernetError
from .evaluation import evaluate_graph, load_gold_cases, persistence_check
from .models import EdgeRelation, FormulaStatus, VerificationStatus
from .normalization import latex_to_ascii
from .repository import GraphRepository
from .services import build_service


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mathernet",
        description="Build a source-backed personal formula knowledge graph.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="create local data and configuration files")
    subparsers.add_parser("doctor", help="check local setup without exposing secrets")
    subparsers.add_parser("list", help="list formula cards")

    lookup = subparsers.add_parser("lookup", help="look up a local formula")
    lookup.add_argument("query")

    learn = subparsers.add_parser("learn", help="retrieve, synthesize, and save a formula")
    learn.add_argument("query")

    show = subparsers.add_parser("show", help="show a formula card and its sources")
    show.add_argument("formula")

    graph = subparsers.add_parser("graph", help="show a formula's local graph neighbourhood")
    graph.add_argument("formula")

    note = subparsers.add_parser("note", help="replace the personal note for a formula")
    note.add_argument("formula")
    note.add_argument("text")

    status = subparsers.add_parser("status", help="set a learner-managed study status")
    status.add_argument("formula")
    status.add_argument("value", choices=[item.value for item in FormulaStatus])

    edge = subparsers.add_parser("edge", help="manage dependency edges")
    edge_subparsers = edge.add_subparsers(dest="edge_command", required=True)
    propose = edge_subparsers.add_parser("propose", help="add an AI-suggested edge manually")
    propose.add_argument("source", help="prerequisite formula")
    propose.add_argument("target", help="dependent formula")
    propose.add_argument("--relation", choices=[item.value for item in EdgeRelation], required=True)
    propose.add_argument("--rationale", required=True)
    propose.add_argument("--source-id", action="append", default=[], dest="source_ids")
    for action in ("confirm", "reject"):
        command = edge_subparsers.add_parser(action, help=f"{action} an edge")
        command.add_argument("edge_id")
    edit = edge_subparsers.add_parser("edit", help="edit and mark an edge user-edited")
    edit.add_argument("edge_id")
    edit.add_argument("--relation", choices=[item.value for item in EdgeRelation], required=True)
    edit.add_argument("--rationale", required=True)
    edit.add_argument("--source-id", action="append", default=[], dest="source_ids")

    export = subparsers.add_parser("export", help="export a JSON graph copy")
    export.add_argument("destination")

    evaluate = subparsers.add_parser("evaluate", help="run the frozen acceptance suite")
    evaluate.add_argument(
        "--gold",
        required=True,
        help="path to the frozen gold-case JSON",
    )
    evaluate.add_argument(
        "--output",
        default="output/evaluation.json",
        help="path for the machine-readable evaluation report",
    )

    start = subparsers.add_parser("start", help="start the Mathernet web application")
    start.add_argument("--host", default="127.0.0.1")
    start.add_argument("--port", type=int, default=8765)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return dispatch(args)
    except MathernetError as error:
        label = "Refused" if error.__class__.__name__ == "RefusalError" else "Error"
        print(f"{label}: {error}", file=sys.stderr)
        return 2


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "init":
        return initialize()
    if args.command == "start":
        initialize(quiet=True)
        return start_api(
            Settings.from_env(),
            host=args.host,
            port=args.port,
        )

    settings = Settings.from_env()
    repository = GraphRepository(settings.data_path)
    if args.command == "doctor":
        return doctor(settings)
    if args.command == "list":
        return list_formulas(repository)
    if args.command == "lookup":
        node = repository.find_formula(args.query)
        if node is None:
            print("Not found in the local library.")
            return 1
        print(f"{node.id}  {node.name}  [{node.status.value}]")
        return 0
    if args.command == "show":
        node = repository.find_formula(args.formula)
        if node is None:
            raise MathernetError("formula was not found in the local library")
        return show_formula(repository, node.id)
    if args.command == "graph":
        node = repository.find_formula(args.formula)
        if node is None:
            raise MathernetError("formula was not found in the local library")
        return show_graph(repository, node.id)
    if args.command == "note":
        node = repository.find_formula(args.formula)
        if node is None:
            raise MathernetError("formula was not found in the local library")
        repository.update_user_module(node.id, args.text)
        repository.save()
        print("Personal note saved in the User Module.")
        return 0
    if args.command == "status":
        node = repository.find_formula(args.formula)
        if node is None:
            raise MathernetError("formula was not found in the local library")
        repository.set_formula_status(node.id, FormulaStatus(args.value))
        repository.save()
        print("Study status saved. This label records study activity, not mastery.")
        return 0
    if args.command == "edge":
        return manage_edge(repository, args)
    if args.command == "export":
        repository.export(args.destination)
        print(f"Exported local graph to {Path(args.destination).expanduser()}")
        return 0
    if args.command == "evaluate":
        return run_evaluation(repository, args.gold, args.output)
    if args.command == "learn":
        learned = build_service(settings).learn(args.query)
        result_node = learned["formula"]["formula"]
        action = "Created" if learned["created"] else "Found existing"
        print(f"{action}: {result_node['name']} ({result_node['id']})")
        print(f"Display: {latex_to_ascii(result_node['latex'])}")
        print(f"Sources: {len(result_node['sources'])}")
        for edge in learned["suggested_edges"]:
            print(
                f"Suggested edge: {edge['source_id']} -> {edge['target_id']} "
                f"[{edge['verification_status']}]"
            )
        for name in learned["unresolved_dependencies"]:
            print(f"Unresolved prerequisite: {name}")
        for warning in learned["warnings"]:
            print(f"Note: {warning}")
        return 0
    raise MathernetError("unknown command")


def initialize(*, quiet: bool = False) -> int:
    Path("data").mkdir(exist_ok=True)
    if not Path(".env").exists() and Path(".env.example").exists():
        shutil.copyfile(".env.example", ".env")
    settings = Settings.from_env()
    settings.data_path.parent.mkdir(parents=True, exist_ok=True)
    GraphRepository(settings.data_path).save()
    if quiet:
        return 0
    print("Mathernet is initialized.")
    return 0


def doctor(settings: Settings) -> int:
    if settings.mcp_transport == "stdio":
        mcp_ready = bool(settings.mcp_command)
        mcp_detail = "stdio configured" if mcp_ready else "stdio command not configured"
    elif settings.mcp_transport == "http":
        mcp_ready = bool(settings.mcp_http_url)
        mcp_detail = "http configured" if mcp_ready else "http URL not configured"
    else:
        mcp_ready = False
        mcp_detail = "transport must be stdio or http"

    checks = [
        ("Python", True, sys.version.split()[0]),
        ("Local data path", True, str(settings.data_path.expanduser())),
        ("MCP Web Search", mcp_ready, mcp_detail),
        (
            "Language model key",
            True,
            "configured"
            if settings.openai_api_key
            else "not configured; offline synthesis enabled",
        ),
        ("Approved publishers", bool(settings.approved_publishers), str(len(settings.approved_publishers))),
    ]
    for name, ok, detail in checks:
        print(f"[{'OK' if ok else 'CHECK'}] {name}: {detail}")
    return 0 if all(item[1] for item in checks) else 1


def start_api(settings: Settings, *, host: str, port: int) -> int:
    if not 0 <= port <= 65535:
        raise MathernetError("port must be between 0 and 65535")
    service = build_service(settings)
    server = None
    last_error = None
    candidates = [port] if port == 0 else range(port, min(port + 20, 65536))
    for candidate in candidates:
        try:
            server = create_server(service, host, candidate)
            break
        except OSError as error:
            last_error = error
            if error.errno != errno.EADDRINUSE:
                raise MathernetError(f"could not start Mathernet: {error}") from error
    if server is None:
        raise MathernetError(
            f"could not find an available port near {port}: {last_error or 'unknown error'}"
        )

    address, actual_port = server.server_address[:2]
    display_host = "127.0.0.1" if address in {"0.0.0.0", "::"} else address
    print("Mathernet is running.")
    print(f"URL: http://{display_host}:{actual_port}")
    print(f"Port: {actual_port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nMathernet stopped.")
    finally:
        server.server_close()
    return 0


def run_evaluation(repository: GraphRepository, gold_path: str, output_path: str) -> int:
    gold_cases = load_gold_cases(Path(gold_path).expanduser())
    persistence_pass = persistence_check(repository.store.path)
    report = evaluate_graph(repository.document, gold_cases, persistence_pass=persistence_pass)
    destination = Path(output_path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print("Frozen acceptance evaluation")
    print(f"- Dependency edges: {report.edge_matches}/{report.expected_edges} ({report.edge_match_rate:.0%})")
    print(f"- Formula lookup: {report.lookup_correct}/{report.lookup_total} ({report.lookup_accuracy:.0%})")
    print(f"- Source traceability: {report.source_cards_pass}/{report.source_cards_total}")
    print(f"- Safety cases: {report.safety_pass}/{report.safety_total}")
    print(f"- Persistence and dual modules: {'pass' if report.persistence_pass else 'fail'}")
    print(f"- Overall: {'PASS' if report.overall_pass else 'FAIL'}")
    print(f"Report: {destination}")
    return 0 if report.overall_pass else 1


def list_formulas(repository: GraphRepository) -> int:
    nodes = repository.list_formulas()
    if not nodes:
        print("The local formula library is empty.")
        return 0
    for node in nodes:
        print(f"{node.id}  {node.name}  [{node.status.value}]")
    return 0


def show_formula(repository: GraphRepository, formula_id: str) -> int:
    node = repository.get_formula(formula_id)
    print(f"{node.name} ({node.id})")
    print(f"LaTeX: {node.latex}")
    print(f"Display: {latex_to_ascii(node.latex)}")
    print(f"Status: {node.status.value} (study label only, not proof of mastery)")
    print(f"Topics: {', '.join(node.topic_tags) or 'none'}")
    print("\nAI Module")
    print(f"Summary: {node.ai_module.summary}")
    print(f"Explanation: {node.ai_module.explanation}")
    if node.ai_module.examples:
        print("Examples:")
        for example in node.ai_module.examples:
            print(f"- {example}")
    print("\nUser Module")
    print(node.user_module.notes or "(no personal note)")
    print("\nSources")
    for source_id in node.sources:
        source = repository.get_source(source_id)
        print(f"- {source.title} | {source.publisher} | {source.url}")
        print(f"  Retrieved: {source.retrieved_at}")
    return 0


def show_graph(repository: GraphRepository, formula_id: str) -> int:
    node = repository.get_formula(formula_id)
    incoming, outgoing = repository.neighbours(formula_id)
    print(f"Graph neighbourhood for {node.name}")
    print("Incoming dependencies:")
    for edge in incoming:
        source = repository.get_formula(edge.source_id)
        print(f"- {source.name} -> {node.name} [{edge.verification_status.value}] {edge.relation.value}")
        print(f"  Rationale: {edge.rationale}")
    print("Outgoing dependencies:")
    for edge in outgoing:
        target = repository.get_formula(edge.target_id)
        print(f"- {node.name} -> {target.name} [{edge.verification_status.value}] {edge.relation.value}")
        print(f"  Rationale: {edge.rationale}")
    return 0


def manage_edge(repository: GraphRepository, args: argparse.Namespace) -> int:
    if args.edge_command == "propose":
        source = repository.find_formula(args.source)
        target = repository.find_formula(args.target)
        if source is None or target is None:
            raise MathernetError("both formulas must already exist before creating an edge")
        edge_id = f"edge_manual_{len(repository.document.edges) + 1:04d}"
        edge = repository.add_edge(
            edge_id=edge_id,
            source_id=source.id,
            target_id=target.id,
            relation=EdgeRelation(args.relation),
            rationale=args.rationale,
            sources=args.source_ids,
        )
    elif args.edge_command == "confirm":
        edge = repository.verify_edge(args.edge_id)
    elif args.edge_command == "reject":
        edge = repository.reject_edge(args.edge_id)
    else:
        edge = repository.edit_edge(
            args.edge_id,
            relation=EdgeRelation(args.relation),
            rationale=args.rationale,
            sources=args.source_ids,
        )
    repository.save()
    print(f"{edge.id}: {edge.source_id} -> {edge.target_id} [{edge.verification_status.value}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
