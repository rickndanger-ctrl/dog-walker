"""Run one authored step at a time; never replay an interrupted turn silently."""
import asyncio
import json
import subprocess
from pathlib import Path
from .workflow import WalkerError, inside
from .storage import digest, git, scrub
from .judge import LocalJudge, classify
from .worker import CodexWorker


def run_checks(checks, root, result, commands, hashes):
    rows = []
    for i, check in enumerate(checks):
        typ = check["type"]
        row = {"id": check.get("id", f"{typ}-{i + 1}"), "type": typ, "pass": False, "detail": ""}
        try:
            if typ == "command":
                import os, signal
                from .worker import environment
                proc = subprocess.Popen(check["argv"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, env=environment(), start_new_session=True)
                try:
                    output, _ = proc.communicate(timeout=check.get("timeout", 60))
                    row.update({"pass": proc.returncode == 0, "exit_code": proc.returncode, "detail": output[-4000:]})
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.communicate()
                    row["detail"] = "Verification command timed out"
            elif typ == "file_exists":
                row["pass"] = inside(root, check["path"]).is_file()
            elif typ == "file_contains":
                row["pass"] = check["text"] in inside(root, check["path"]).read_text()
            elif typ == "unchanged":
                sha = hashes.get(check["path"])
                row["pass"] = sha is not None and sha == digest(inside(root, check["path"]))
            elif typ == "response_contains":
                row["pass"] = check["text"].lower() in json.dumps(result).lower()
            elif typ == "command_executed":
                row["pass"] = any(check["text"] in c.get("command", "") and c.get("exit_code") == 0 for c in commands)
            elif typ == "no_changes":
                row["pass"] = not git(root, "status", "--porcelain")
            if not row["detail"]:
                row["detail"] = f"{typ}: {'passed' if row['pass'] else 'failed'}"
        except (OSError, ValueError, WalkerError) as exc:
            row["detail"] = str(exc)
        rows.append(row)
    return scrub(rows)


class Engine:
    def __init__(self, store, emit, ask, no_start=False, worker_factory=CodexWorker, judge=None):
        self.store, self.emit, self.ask = store, emit, ask
        self.workflow = store.workflow()
        self.worker = worker_factory(store, emit, no_start)
        self.judge = judge or LocalJudge()
        self.cancelled = False
        self.edit = None

    def log(self, text):
        self.emit(scrub(str(text)))

    def pause(self, reason):
        self.store.save(status="paused", reason=reason)
        self.store.event("paused", reason=reason)
        self.log(f"Paused: {reason}\nResume: dog-walker resume {self.store.state['id']}")

    def advance(self, outcome="passed"):
        s = self.store.state
        history = [*s["history"], {"step": s["step"], "outcome": outcome, "attempts": s["attempts"], "turn": s["turns"]}]
        target = self.workflow.steps[s["step"]]["on_pass"]
        self.store.event("step_finished", step=s["step"], outcome=outcome, next=target)
        self.store.save(step=target, history=history, attempts=0, phase="pending", evaluation=None,
                        status="running", previous_result=s.get("result"), result=None, failed_checks=[])

    async def evaluate(self, spec, result, commands):
        self.log("Checking actual project files and test results…")
        checks = await asyncio.to_thread(run_checks, spec["checks"], Path(self.store.state["root"]), result, commands, self.store.state["hashes"])
        for row in checks:
            self.log(f"{'PASS' if row['pass'] else 'FAIL'} {row['id']}: {row['detail']}")
        failures = [c["id"] for c in checks if not c["pass"]]
        if result["status"] == "blocked" or result["blockers"]:
            return {"decision": "review", "failed": failures + result["blockers"] or ["Worker blocked"], "checks": checks, "judge": None}
        if failures:
            return {"decision": "retry", "failed": failures, "checks": checks, "judge": None}
        if not spec["questions"]:
            return {"decision": "pass" if checks else "review", "failed": [] if checks else ["Step has no automated acceptance checks"], "checks": checks, "judge": None}
        self.log("Local Laya judge is evaluating this checkpoint…")
        state = {"summary": result["summary"], "evidence": result["evidence"],
                 "verified_checks": [{"id": c["id"], "pass": c["pass"]} for c in checks], "blockers": result["blockers"]}
        try:
            answer = await asyncio.to_thread(self.judge.decide, state, spec["questions"])
            decision, failed = classify(spec["questions"], answer)
            self.log(json.dumps(answer["answers"], indent=2))
        except Exception as exc:
            answer, decision, failed = None, "review", [f"Local judge unavailable: {exc}"]
        # A semantic-only pass remains subject to human review until there is project-specific evidence.
        if decision == "pass" and not checks:
            decision, failed = "review", ["Semantic-only checkpoint requires human review"]
        return {"decision": decision, "failed": failed, "checks": checks, "judge": answer}

    async def choose(self, reason, passed=False):
        s = self.store.state
        self.log(reason)
        choice = await self.ask(reason, passed)
        if choice.startswith("edit:"):
            self.edit = choice[5:]
            return "retry"
        return choice

    async def run(self):
        self.store.acquire()
        try:
            s = self.store.state
            if s["status"] in {"completed", "aborted"}:
                self.log(f"Run already {s['status']}")
                return
            self.log(f"Dog Walker • {s['name']}\nRun: {s['id']}\nWorkspace: {s['root']}\nJudge: Laya on CPU • offline\nMode: {'automatic' if s['auto'] else 'supervised'}")
            if s["phase"] in {"running", "interrupted"}:
                choice = await self.choose("Previous turn was interrupted. Review partial work; Retry continues the saved session.")
                if choice == "abort":
                    self.store.save(status="aborted")
                    return
                if choice != "retry":
                    self.pause("Interrupted turn needs an explicit retry")
                    return
                self.store.save(phase="pending", interrupted_retry=True)
            elif s["phase"] == "reviewing":
                # Project files may have changed while the run was paused. Recheck without replaying the worker.
                self.store.save(phase="evaluating")
            self.store.save(status="running")
            await self.worker.ready()
            while not self.cancelled:
                ident = s["step"]
                if ident == "complete":
                    if any(h["outcome"] == "skipped" for h in s["history"]):
                        self.store.save(status="completed", completion="with_skips")
                    elif any(h["outcome"] == "accepted_manually" for h in s["history"]):
                        self.store.save(status="completed", completion="with_manual_acceptance")
                    elif any(h["outcome"] == "exhausted" for h in s["history"]):
                        self.store.save(status="completed", completion="with_recovery_branch")
                    else:
                        self.store.save(status="completed", completion="all_passed")
                    self.store.event("completed", history=s["history"])
                    self.log(f"Workflow complete ({s['completion']}).\nReview the changes in {s['root']}\nRun log: {self.store.path}")
                    return
                if ident == "pause":
                    self.pause("Workflow reached its pause transition")
                    return
                spec = self.workflow.steps[ident]
                if s["phase"] == "pending":
                    if s["turns"] >= self.workflow.data.get("max_turns", 40):
                        self.pause("Global turn limit reached")
                        return
                    failed = s.get("failed_checks", [])
                    prompt = self.edit or self.workflow.prompt(ident, project_root=s["root"], step_id=ident,
                        previous_result=json.dumps(s.get("previous_result") or {}, ensure_ascii=False),
                        failed_checks="\n".join(failed))
                    self.edit = None
                    prompt += "\n\nReturn only this JSON shape: {\"status\":\"completed\" or \"blocked\",\"summary\":\"concise summary\",\"evidence\":[\"actual evidence\"],\"files_changed\":[\"paths\"],\"blockers\":[]}. Keep the summary under 1400 characters."
                    self.store.save(phase="running", turns=s["turns"] + 1, attempts=s["attempts"] + 1, reason=None)
                    self.log(f"\nStep: {ident} • attempt {s['attempts']}\n{prompt}")
                    try:
                        result, commands = await self.worker.turn(prompt, spec["timeout"])
                    except Exception as exc:
                        self.store.save(phase="interrupted")
                        self.pause(str(exc))
                        return
                    self.store.save(phase="evaluating", result=result, commands=commands)
                if s["phase"] == "evaluating":
                    evaluation = await self.evaluate(spec, s["result"], s.get("commands", []))
                    self.store.event("evaluation", step=ident, evaluation=evaluation)
                    self.store.save(evaluation=evaluation, phase="reviewing")
                evaluation = s["evaluation"]
                decision = evaluation["decision"]
                if decision == "pass":
                    if s["auto"] and not spec["approval"]:
                        self.advance()
                        continue
                    choice = await self.choose(f"{ident}: checkpoint passed. Approve to move to the next step.", passed=True)
                    if choice == "approve":
                        self.advance()
                        continue
                elif decision == "retry" and s["attempts"] <= spec["max_retries"] and spec.get("retry_prompt"):
                    if s["auto"]:
                        choice = "retry"
                        self.log("Checkpoint failed; sending the authored correction prompt.")
                    else:
                        choice = await self.choose(f"{ident}: failed {evaluation['failed']}. Retry uses the authored correction prompt.")
                elif decision == "retry" and s["attempts"] > spec["max_retries"] and spec["on_exhausted"] != "pause":
                    self.store.event("exhausted", step=ident, next=spec["on_exhausted"])
                    history = [*s["history"], {"step": ident, "outcome": "exhausted", "attempts": s["attempts"], "turn": s["turns"]}]
                    self.store.save(step=spec["on_exhausted"], phase="pending", attempts=0, failed_checks=[], history=history)
                    continue
                else:
                    choice = await self.choose(f"{ident}: review needed — {evaluation['failed']}.")
                if choice == "retry":
                    if s["attempts"] > spec["max_retries"]:
                        self.pause("Retry limit reached. Edit the workflow for a new run or explicitly skip this step.")
                        return
                    self.store.save(phase="pending", failed_checks=evaluation["failed"], previous_result=s["result"])
                elif choice == "approve":
                    # Manual acceptance is recorded separately and cannot hide a failed deterministic check.
                    if any(not c["pass"] for c in evaluation["checks"]):
                        self.pause("A deterministic check failed; Retry or Skip is required")
                        return
                    self.advance("accepted_manually")
                elif choice == "skip":
                    self.advance("skipped")
                elif choice == "abort":
                    self.store.save(status="aborted")
                    self.store.event("aborted")
                    self.log("Run aborted; project files and worktree retained.")
                    return
                else:
                    self.pause("Paused by user or headless review gate")
                    return
            self.pause("Paused by user")
        except asyncio.CancelledError:
            if self.store.state["phase"] == "running":
                self.store.save(phase="interrupted")
            self.pause("Interrupted; partial work retained")
            raise
        except Exception as exc:
            self.pause(str(exc))
        finally:
            self.store.release()
