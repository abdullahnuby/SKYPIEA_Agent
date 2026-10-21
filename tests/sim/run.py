"""مشغّل المحاكاة: يولّد السيناريوهات، يوزّعها على العمّال، ويطلع تقرير.

الاستخدام:
    python tests/sim/run.py --n 100000 --workers 8
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

from tests.sim.gen import build  # noqa: E402

_AGENT = None  # type: ignore[var-annotated]


def _worker_init() -> None:
    global _AGENT
    if _AGENT is None:
        from tests.sim.simcore import SimAgent

        _AGENT = SimAgent(0)


def _contains(text: str, needle: str) -> bool:
    from agent.text import normalize

    return normalize(str(needle), lower=True) in normalize(str(text or ""), lower=True)


def _evaluate(cat: str, rec: dict[str, Any], exp: dict[str, Any], facts: list[dict[str, Any]], chat: int) -> list[tuple[str, str]]:
    fails: list[tuple[str, str]] = []
    tool = rec["tool"]
    decision = rec["decision"]
    reply = rec["reply"] or ""
    args = rec["args"] or {}

    if rec["error"]:
        fails.append(("crash", rec["error"]))

    if exp.get("no_tool"):
        if tool and decision != "deny":
            fails.append(("tool_unexpected", f"{tool} ({decision})"))

    if "tool" in exp:
        allowed = exp["tool"] if isinstance(exp["tool"], list) else [exp["tool"]]
        if tool not in allowed:
            fails.append(("tool_missing", f"متوقع {allowed} — طلع {tool}"))

    if "target_contains" in exp and tool == "open_target":
        target = str(rec.get("resolved") or args.get("target") or "")
        if not _contains(target, exp["target_contains"]):
            fails.append(("target", f"متوقع {exp['target_contains']} — طلع {target}"))

    if "command_has" in exp and tool == "shell":
        command = str(args.get("command", ""))
        if not _contains(command, exp["command_has"]):
            fails.append(("command", f"مفيش {exp['command_has']} في الأمر"))

    if "query_has" in exp and tool == "search_web":
        query = str(args.get("query", ""))
        if not _contains(query, exp["query_has"]):
            fails.append(("query", f"مفيش {exp['query_has']} — الاستعلام: {query}"))
        for bad in exp.get("query_not", []):
            if _contains(query, bad):
                fails.append(("query", f"الاستعلام فيه زيادة: {bad}"))

    if "decision" in exp and decision != exp["decision"]:
        fails.append(("decision", f"متوقع {exp['decision']} — طلع {decision}"))

    if "decision_in" in exp and decision not in exp["decision_in"]:
        fails.append(("decision", f"متوقع {exp['decision_in']} — طلع {decision}"))

    if "reply_has" in exp:
        if not any(_contains(reply, s) for s in exp["reply_has"]):
            fails.append(("reply", f"الرد مفيهوش أي من {exp['reply_has']} — {reply[:120]}"))

    if "reply_has_all" in exp:
        missing = [s for s in exp["reply_has_all"] if not _contains(reply, s)]
        if missing:
            fails.append(("reply", f"الرد ناقص {missing}"))

    if "reply_regex" in exp and not re.search(exp["reply_regex"], reply):
        fails.append(("reply", f"الرد مش مطابق {exp['reply_regex']} — {reply[:120]}"))

    if "reply_not" in exp:
        for bad in exp["reply_not"]:
            if _contains(reply, bad):
                fails.append(("reply", f"الرد فيه حاجة مرفوضة: {bad}"))

    if "fact" in exp:
        for key, value in exp["fact"]:
            if not any(f["key"] == key and _contains(f["value"], value) for f in facts):
                fails.append(("fact_missing", f"مفيش {key}={value}"))

    if "fact_absent" in exp:
        for key in exp["fact_absent"]:
            if any(f["key"] == key for f in facts):
                fails.append(("fact_extra", f"{key} لسه موجود"))

    if exp.get("no_new_facts") and rec["new_facts"]:
        fails.append(("fact_unexpected", str(rec["new_facts"])))

    if cat.startswith("commands_") and rec["new_facts"]:
        fails.append(("fact_unexpected", str(rec["new_facts"])))

    return fails


def _run_chunk(items: list[tuple[int, dict[str, Any]]]) -> dict[str, Any]:
    global _AGENT
    _worker_init()
    assert _AGENT is not None

    out: dict[str, Any] = {
        "turns": 0,
        "failed_turns": 0,
        "failed_scenarios": 0,
        "categories": defaultdict(lambda: {"scenarios": 0, "failed": 0, "turns": 0}),
        "kinds": Counter(),
        "failures": [],
    }

    for idx, sc in items:
        chat = idx + 1
        _AGENT.chat_id = chat
        for key, value in sc.get("seed", []):
            _AGENT.memory.save_fact(chat, key, value, "seed")
        for msg in sc.get("seed_messages", []):
            _AGENT.memory.add_message(chat, {"role": "user", "content": msg})

        cat_stats = out["categories"][sc["cat"]]
        cat_stats["scenarios"] += 1
        scenario_failed = False

        for t_index, item in enumerate(sc["turns"]):
            rec = _AGENT.step(item["text"])
            facts = _AGENT.facts()
            out["turns"] += 1
            cat_stats["turns"] += 1
            fails = _evaluate(sc["cat"], rec, item["exp"], facts, chat)
            if not fails:
                continue

            scenario_failed = True
            out["failed_turns"] += 1
            for kind, detail in fails:
                out["kinds"][kind] += 1
                if len(out["failures"]) < 4000:
                    out["failures"].append(
                        {
                            "id": sc["id"],
                            "cat": sc["cat"],
                            "turn": t_index,
                            "kind": kind,
                            "detail": detail,
                            "text": item["text"][:220],
                            "reply": (rec["reply"] or "")[:200],
                            "tool": rec["tool"],
                            "decision": rec["decision"],
                            "model": rec["model"],
                            "facts": [(f["key"], f["value"]) for f in facts][:12],
                        }
                    )

        if scenario_failed:
            out["failed_scenarios"] += 1
            cat_stats["failed"] += 1

    out["categories"] = {k: v for k, v in out["categories"].items()}
    out["kinds"] = dict(out["kinds"])
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=100000)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 4))
    parser.add_argument("--chunk", type=int, default=400)
    parser.add_argument("--report", type=str, default="data/sim_report")
    parser.add_argument("--keep-failures", type=int, default=600)
    args = parser.parse_args()

    print(f"توليد {args.n} سيناريو (seed={args.seed}) ...")
    scenarios = build(args.n, args.seed)
    print(f"تم توليد {len(scenarios)} — التوزيع: {dict(Counter(s['cat'] for s in scenarios))}")

    indexed = list(enumerate(scenarios))
    chunks = [indexed[i : i + args.chunk] for i in range(0, len(indexed), args.chunk)]

    started = time.time()
    results = []
    with ProcessPoolExecutor(max_workers=args.workers, initializer=_worker_init) as pool:
        for done, result in enumerate(pool.map(_run_chunk, chunks), 1):
            results.append(result)
            if done % 20 == 0 or done == len(chunks):
                elapsed = time.time() - started
                print(f"  {done}/{len(chunks)} دفعة — {elapsed:.0f}s")

    merged: dict[str, Any] = {
        "turns": 0,
        "failed_turns": 0,
        "failed_scenarios": 0,
        "categories": {},
        "kinds": Counter(),
        "failures": [],
    }
    categories: dict[str, dict[str, int]] = defaultdict(lambda: {"scenarios": 0, "failed": 0, "turns": 0})
    for result in results:
        merged["turns"] += result["turns"]
        merged["failed_turns"] += result["failed_turns"]
        merged["failed_scenarios"] += result["failed_scenarios"]
        merged["kinds"].update(result["kinds"])
        for cat, stats in result["categories"].items():
            for key, value in stats.items():
                categories[cat][key] += value
        merged["failures"].extend(result["failures"])

    merged["categories"] = dict(categories)
    merged["kinds"] = dict(merged["kinds"])
    merged["elapsed_sec"] = round(time.time() - started, 1)
    merged["n"] = args.n
    merged["seed"] = args.seed

    failures = merged["failures"]
    failures.sort(key=lambda f: (f["cat"], f["kind"]))
    merged["failures"] = failures[: args.keep_failures]

    report_base = Path(args.report)
    report_base.parent.mkdir(parents=True, exist_ok=True)
    (report_base.with_suffix(".json")).write_text(
        json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (report_base.with_suffix(".md")).write_text(_markdown(merged), encoding="utf-8")

    _print_summary(merged)
    print(f"\nالتقرير: {report_base.with_suffix('.md')}")
    return 0


def _markdown(data: dict[str, Any]) -> str:
    lines = [
        "# تقرير المحاكاة",
        "",
        f"- السيناريوهات: **{data['n']}**",
        f"- الأدوار: **{data['turns']}**",
        f"- أدوار فشلت: **{data['failed_turns']}**",
        f"- سيناريوهات فشلت: **{data['failed_scenarios']}**",
        f"- الزمن: **{data['elapsed_sec']}s**",
        "",
        "## حسب الفئة",
        "",
        "| الفئة | سيناريوهات | فشل | نسبة النجاح |",
        "|---|---|---|---|",
    ]
    for cat, stats in sorted(data["categories"].items(), key=lambda x: -x[1]["failed"]):
        ok = 100 * (1 - stats["failed"] / max(1, stats["scenarios"]))
        lines.append(f"| {cat} | {stats['scenarios']} | {stats['failed']} | {ok:.1f}% |")

    lines += ["", "## أنواع الفشل", "", "| النوع | العدد |", "|---|---|"]
    for kind, count in sorted(data["kinds"].items(), key=lambda x: -x[1]):
        lines.append(f"| {kind} | {count} |")

    lines += ["", "## أهم النماذج", ""]
    seen: Counter = Counter()
    for fail in data["failures"]:
        signature = (fail["cat"], fail["kind"], fail["detail"][:60])
        seen[signature] += 1
        if seen[signature] > 1:
            continue
        lines.append(f"### {fail['cat']} / {fail['kind']}")
        lines.append(f"- **الجملة:** {fail['text']}")
        lines.append(f"- **التفاصيل:** {fail['detail']}")
        lines.append(f"- **الرد:** {fail['reply']}")
        lines.append(f"- **الأداة:** {fail['tool']} / {fail['decision']}")
        lines.append("")
    return "\n".join(lines)


def _print_summary(data: dict[str, Any]) -> None:
    print("\n" + "=" * 60)
    print(f"الأدوار: {data['turns']} | فشلت: {data['failed_turns']}")
    print(f"السيناريوهات: {data['n']} | فشلت: {data['failed_scenarios']}")
    print("=" * 60)
    print(f"{'الفئة':<20} {'سيناريو':>8} {'فشل':>8} {'نجاح':>8}")
    for cat, stats in sorted(data["categories"].items(), key=lambda x: -x[1]["failed"]):
        ok = 100 * (1 - stats["failed"] / max(1, stats["scenarios"]))
        print(f"{cat:<20} {stats['scenarios']:>8} {stats['failed']:>8} {ok:>7.1f}%")
    print("=" * 60)
    for kind, count in sorted(data["kinds"].items(), key=lambda x: -x[1]):
        print(f"{kind:<24} {count}")


if __name__ == "__main__":
    raise SystemExit(main())
