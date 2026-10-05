import json
from dataclasses import dataclass

from src.config import EVAL_QUESTIONS_PATH, ROUTING_PROBE_PATH
from src.evaluation.evaluator import load_questions
from src.routing.router import RouteResult, decide_route

GENERAL_SOURCE = "general"  # benchmark questions that should be answered without retrieval
COUNTERS = ("questions", "classifier_yes", "probe_overruled", "expect_retrieval", "reached",
            "right_source", "expect_none", "wrongly_retrieved")


@dataclass
class ReportRow:
    group: str
    query: str
    expected_source: str | None  # None: the question should be answered without retrieval
    route: RouteResult

    @property
    def ok(self) -> bool:
        if self.expected_source is None:
            return not self.route.needs_retrieval
        return self.route.needs_retrieval and self.route.source == self.expected_source


def load_benchmark_items(questions_path: str = EVAL_QUESTIONS_PATH) -> list[tuple[str, str, str | None]]:
    """Return (group, query, expected source or None) for every benchmark question."""
    items = []
    for q in load_questions(questions_path):
        source = q.get("source_doc")
        items.append(("benchmark", q["query"], None if source in (None, GENERAL_SOURCE) else source))
    return items


def load_probe_questions(questions_path: str = EVAL_QUESTIONS_PATH,
                         probe_path: str = ROUTING_PROBE_PATH) -> list[tuple[str, str, str | None]]:
    """Return (group, query, expected source or None) for the benchmark and every group of the probe fixture."""
    items = load_benchmark_items(questions_path)
    with open(probe_path, "r", encoding="utf-8") as f:
        for group, questions in json.load(f).items():
            items.extend((group, q["query"], q.get("source_doc")) for q in questions)
    return items


def run_routing_report(vectorstore, items) -> list[ReportRow]:
    """Route every question with the same decide_route() that /query uses. Makes no LLM calls."""
    embed = vectorstore._embedding_function.embed_query
    return [ReportRow(group, query, expected, decide_route(embed(query), vectorstore, query))
            for group, query, expected in items]


def benchmark_routing_failures(vectorstore, questions_path: str = EVAL_QUESTIONS_PATH) -> list[str]:
    """Benchmark questions the router no longer handles as expected, one readable line each.

    The publish guard of ingest-batch: a question with a source must still be retrieved from that source,
    and the general one must still be answered without retrieval. These are the questions the live-eval gate asks.
    """
    rows = run_routing_report(vectorstore, load_benchmark_items(questions_path))
    return [f"'{row.query}': expected {row.expected_source or 'no retrieval'}, "
            f"routed to {row.route.source} ({row.route.reason})" for row in rows if not row.ok]


def summarize(rows: list[ReportRow]) -> dict[str, dict[str, int]]:
    """Count per group: the votes, then retrieval reached and right source for questions with a source,
    and wrong retrievals for questions without one."""
    summary = {}
    for row in rows:
        s = summary.setdefault(row.group, dict.fromkeys(COUNTERS, 0))
        s["questions"] += 1
        s["classifier_yes"] += int(row.route.reason == "classifier")
        s["probe_overruled"] += int(row.route.reason == "probe")
        if row.expected_source is None:
            s["expect_none"] += 1
            s["wrongly_retrieved"] += int(row.route.needs_retrieval)
        else:
            s["expect_retrieval"] += 1
            s["reached"] += int(row.route.needs_retrieval)
            s["right_source"] += int(row.ok)
    return summary


def format_report(rows: list[ReportRow]) -> str:
    """One line per question (misses name what was expected), then one summary line per group."""
    lines = [f"{'group':<13} {'':<4} {'reason':<12} {'conf':>5} {'probe':>5}  {'routed to':<30} question"]
    for row in rows:
        r = row.route
        probe = "-" if r.probe_similarity is None else f"{r.probe_similarity:.2f}"
        miss = "" if row.ok else f"  [expected {row.expected_source or 'no retrieval'}]"
        lines.append(f"{row.group:<13} {'OK' if row.ok else 'MISS':<4} {r.reason:<12} {r.confidence:>5.2f} "
                     f"{probe:>5}  {r.source:<30} {row.query}{miss}")

    lines.append("")
    for group, s in summarize(rows).items():
        parts = [f"{s['questions']} questions", f"classifier yes {s['classifier_yes']}",
                 f"probe overruled {s['probe_overruled']}"]
        if s["expect_retrieval"]:
            parts += [f"reached {s['reached']}/{s['expect_retrieval']}",
                      f"right source {s['right_source']}/{s['expect_retrieval']}"]
        if s["expect_none"]:
            parts.append(f"wrongly retrieved {s['wrongly_retrieved']}/{s['expect_none']}")
        lines.append(f"{group:<13} " + ", ".join(parts))
    return "\n".join(lines)
