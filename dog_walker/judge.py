"""One small local decision model. No remote provider or fallback."""
import hashlib
import json
import math
import os
from pathlib import Path
from .storage import DATA, atomic_json
from .workflow import WalkerError

MODEL_ID = "convaiinnovations/laya-typed-decisions"
REVISION = "e929ae5cf69bc34259cd2f95c9e91145b818b1f0"
MODEL_DIR = DATA / "judge" / REVISION
FILES = ("config.json", "encoder/config.json", "model.safetensors", "rl_agent_config.json", "tokenizer/tokenizer.json", "tokenizer/tokenizer_config.json")


def prepare():
    """Explicit one-time download; normal execution cannot download anything."""
    from huggingface_hub import snapshot_download, HfApi
    MODEL_DIR.parent.mkdir(parents=True, exist_ok=True)
    info = HfApi().model_info(MODEL_ID, revision=REVISION, files_metadata=True)
    hashes = {f.rfilename: f.lfs.sha256 for f in info.siblings if f.lfs}
    snapshot_download(MODEL_ID, revision=REVISION, allow_patterns=list(FILES), local_dir=MODEL_DIR)
    manifest = {}
    for name in FILES:
        path = MODEL_DIR / name
        with path.open("rb") as handle:
            sha = hashlib.file_digest(handle, "sha256").hexdigest()
        if name in hashes and sha != hashes[name]:
            raise WalkerError(f"Downloaded judge checksum mismatch: {name}")
        manifest[name] = sha
    atomic_json(MODEL_DIR / "dog-walker-manifest.json", {"repo": MODEL_ID, "revision": REVISION, "sha256": manifest})
    return MODEL_DIR


class LocalJudge:
    def __init__(self):
        self.agent = None

    def load(self):
        if self.agent is not None:
            return
        manifest = MODEL_DIR / "dog-walker-manifest.json"
        if not manifest.is_file():
            raise WalkerError("Offline judge is missing. Run: dog-walker setup-local-judge")
        os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", USE_TF="0", TOKENIZERS_PARALLELISM="false")
        import torch
        import laya
        torch.set_num_threads(2)
        self.agent = laya.load(str(MODEL_DIR), device="cpu", backend="eager", expected_sha256=json.loads(manifest.read_text())["sha256"])

    def decide(self, state, questions):
        if not questions:
            return {"answers": {}, "model": MODEL_ID, "revision": REVISION}
        self.load()
        wire = {k: {a: b for a, b in q.items() if a in {"type", "instructions", "criteria"}} for k, q in questions.items()}
        serialized = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
        # Refuse truncation: a discarded blocker could otherwise become a false pass.
        state_tokens = len(self.agent.tok.encode(serialized, add_special_tokens=False))
        for q in wire.values():
            head_tokens = len(self.agent.tok.encode(json.dumps(q, ensure_ascii=False), add_special_tokens=False))
            if head_tokens > 200 or state_tokens + head_tokens + 32 > 1000:
                raise WalkerError("Judge evidence exceeds its context budget; shorten StepResult or review this step manually.")
        answer = self.agent.predict(state, wire)
        usage = answer.get("usage", {})
        if usage.get("truncated") or usage.get("state_tokens_dropped", 0) or usage.get("truncated_questions"):
            raise WalkerError("Local judge truncated its input; manual review is required")
        answer["model"] = MODEL_ID
        answer["revision"] = REVISION
        return answer


def classify(questions, response):
    """Return pass/retry/review. Confidence is model-specific and is not a correctness guarantee."""
    failures, uncertain = [], []
    answers = response.get("answers", {})
    for name, q in questions.items():
        a = answers.get(name, {})
        threshold = q.get("threshold", 0.85)
        typ = q["type"]
        try:
            if typ == "noul":
                value = float(a["noul"])
                if not math.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError("invalid probability")
                support = value if q.get("expected", True) else 1 - value
                if support >= threshold:
                    continue
                (failures if support <= 1 - threshold else uncertain).append(name)
            else:
                probabilities = a.get("probabilities")
                if isinstance(probabilities, dict):
                    expected_keys = list(q["criteria"]) if typ == "choice" else [str(i) for i in range(len(q["criteria"]))]
                    if set(probabilities) != set(expected_keys):
                        raise ValueError("unexpected distribution keys")
                    probabilities = [probabilities[k] for k in expected_keys]
                if not isinstance(probabilities, list) or not probabilities:
                    raise ValueError("missing probability distribution")
                if not all(isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 1 for v in probabilities) or abs(sum(probabilities) - 1) > .02:
                    raise ValueError("invalid distribution")
                if typ == "choice":
                    keys = list(q["criteria"])
                    if len(probabilities) != len(keys) or a.get("choice") not in keys:
                        raise ValueError("invalid choice")
                    support = probabilities[keys.index(q["expected"])]
                else:
                    if len(probabilities) != len(q["criteria"]):
                        raise ValueError("invalid score distribution")
                    support = sum(probabilities[q["minimum"]:])
                if support >= threshold:
                    continue
                (failures if support <= 1 - threshold else uncertain).append(name)
        except (ValueError, KeyError, TypeError, IndexError):
            uncertain.append(f"{name}: invalid judge answer")
    if uncertain:
        return "review", uncertain + failures
    return ("retry", failures) if failures else ("pass", [])
