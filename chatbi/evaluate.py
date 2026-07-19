from __future__ import annotations

import argparse

from config import settings
from evaluator import Evaluator
from main import ChatBISystem
from models import QueryOptions
from prompt_builder import build_prompt


def options_for_mode(mode: str) -> QueryOptions:
    if mode == "baseline":
        return QueryOptions(
            use_few_shot=True,
            use_rules=True,
            use_guards=True,
            use_indicator_knowledge=True,
            use_schema_linking=False,
            use_indicator_rag=False,
        )
    if mode == "schema":
        return QueryOptions(
            use_few_shot=True,
            use_rules=True,
            use_guards=True,
            use_indicator_knowledge=True,
            use_schema_linking=True,
            use_indicator_rag=False,
        )
    return QueryOptions()


def main() -> None:
    parser = argparse.ArgumentParser(description="ChatBI Execution Accuracy 离线评估")
    parser.add_argument("--mode", choices=("baseline", "schema", "full"), default="full")
    parser.add_argument("--cases", default="test_cases.json")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    system = ChatBISystem(settings)
    evaluator = Evaluator(system.db)
    options = options_for_mode(args.mode)

    def generate(question: str) -> str:
        runtime = system.runtime
        linking = (
            runtime.schema_linker.link(question)
            if options.use_schema_linking
            else system._full_schema_fallback()
        )
        _, indicator_block, _ = system._resolve_indicator_context(
            runtime,
            question,
            options.use_indicator_knowledge,
            options.use_indicator_rag,
        )
        system_msg, prompt = build_prompt(
            question,
            linking["schema_context"],
            indicator_block,
            options.use_few_shot,
            options.use_rules,
            options.use_guards,
        )
        return runtime.llm.generate_sql(system_msg, prompt)

    try:
        cases = evaluator.load_test_cases(args.cases)
        if args.limit > 0:
            cases = cases[: args.limit]
        results = evaluator.evaluate_all(cases, generate)
        print(evaluator.generate_report(results))
        raise SystemExit(0 if all(item["execution_match"] for item in results) else 1)
    finally:
        system.close()


if __name__ == "__main__":
    main()
