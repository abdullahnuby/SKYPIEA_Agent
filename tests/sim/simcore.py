"""محرك المحاكاة الداخلي — نفس مسار العقل والذاكرة، بدون تنفيذ أدوات حقيقية.

بيستخدم قاعدة بيانات in-memory ومجلد عمل وهمي، وبيوقف عند حدود الأداة
(بيسجل اسمها ومعاملاتها وقرار السياسة) بدل ما ينفّذها على الجهاز.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.aliases import resolve
from agent.brain import Action, Brain
from agent.memory import Memory
from agent.personal import Personal
from agent.policy import Policy

BASE = Path(__file__).resolve().parents[2]
MODEL_PATH = BASE / "data" / "intent_model.npz"
SANDBOX = BASE / "data" / "sim_workspace"


class SimAgent:
    def __init__(self, chat_id: int) -> None:
        self.memory = Memory(Path(":memory:"))
        self.brain = Brain(self.memory, MODEL_PATH)
        self.personal = Personal(self.memory)
        self.policy = Policy(SANDBOX, "ask")
        self.chat_id = chat_id

    def facts(self) -> list[dict[str, Any]]:
        return self.memory.all_facts(self.chat_id)

    def step(self, text: str) -> dict[str, Any]:
        rec: dict[str, Any] = {
            "text": text,
            "reply": None,
            "personal": False,
            "tool": None,
            "args": {},
            "decision": None,
            "reason": "",
            "unmatched": False,
            "new_facts": [],
            "resolved": None,
            "model": None,
            "error": None,
        }
        try:
            self.memory.add_message(self.chat_id, {"role": "user", "content": text})
            prepared, followup = self.personal.plan(self.chat_id, text)
            if followup is not None:
                action = Action.from_dict(followup)
            else:
                action = self.brain.think(self.chat_id, prepared)

            if self.brain.model is not None:
                label, prob, margin = self.brain.model.predict(prepared)
                rec["model"] = (label, round(float(prob), 3), round(float(margin), 3))

            before = {(f["key"], f["value"]) for f in self.facts()}
            personal_reply = self.personal.handle(
                self.chat_id, prepared, is_command=action is not None
            )
            after = {(f["key"], f["value"]) for f in self.facts()}
            rec["new_facts"] = sorted(after - before)

            if personal_reply:
                rec["reply"] = personal_reply
                rec["personal"] = True
                return rec

            if action is None:
                rec["unmatched"] = True
                return rec

            rec["tool"] = action.tool
            rec["args"] = dict(action.args)
            self.personal.remember_action(self.chat_id, action.to_dict())
            if action.reply:
                rec["reply"] = self.personal.personalize(self.chat_id, action.reply)
            if action.tool:
                verdict = self.policy.check(action.tool, action.args)
                rec["decision"] = verdict.decision.value
                rec["reason"] = verdict.reason
                if action.tool == "open_target":
                    rec["resolved"] = resolve(str(action.args.get("target", "")))
        except Exception as exc:  # noqa: BLE001 — المحاكاة بتسجل أي انفجار
            rec["error"] = f"{type(exc).__name__}: {exc}"
        return rec
