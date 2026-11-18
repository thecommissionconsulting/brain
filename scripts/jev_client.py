"""The one module that talks to Jev, run from the repo root or imported by a hook.

Policy: _local/jev-policy.json, machine-local and gitignored. A missing or malformed
file means mode "off": nothing is sent. Modes: "off" sends nothing, "meta" sends only
metadata Claude wrote about its own work. No note text leaves the machine: any other
mode, "full" included, reads as "off". The endpoint is fixed (DEFAULT_ENDPOINT); the
JEV_ENDPOINT variable is not read.

Every call is masked first: each patterns.scan match becomes a `[PII:<label>]` tag and is
never sent raw. The API key comes only from the
TYPESAFE_API_KEY environment variable and is never printed, logged or written to a file.
send() enforces a total deadline. The "never the text itself" rule applies to log_decision,
which logs a SHA-256 of the sent text. log_pii stores the masked text that was sent, in
_local/jev-pii/, for a prompt Jev flags as still holding personal data. Logging never raises.

Enforces R-56 for every call to Jev: the policy mode decides, and the PII sweep masks the text first and fails closed.
"""
import datetime
import hashlib
import json
import pathlib
import threading
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
POLICY_PATH = ROOT / "_local" / "jev-policy.json"
LOG_DIR = ROOT / "_local" / "jev-log"
PII_DIR = ROOT / "_local" / "jev-pii"
MODES = {
    "off": set(),
    "meta": {"meta"},
}


def load_policy(path=POLICY_PATH):
    """{"mode": "off" | "meta"}. Any read or parse problem, or any other mode, gives "off"."""
    off = {"mode": "off"}
    try:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except Exception:
        return off
    if not isinstance(data, dict) or data.get("mode") not in MODES:
        return off
    return {"mode": data["mode"]}


def mask(text, scan=None):
    """(masked text, labels replaced, in text order). Each scan span becomes [PII:<label>].

    scan=None uses patterns.scan. Any exception from the scan is raised to the caller.
    """
    if scan is None:
        from patterns import scan
    spans = sorted(scan(text), key=lambda hit: hit[1])
    parts, labels, pos = [], [], 0
    for label, start, end in spans:
        start = max(start, pos)
        if end <= start:
            continue
        parts.append(text[pos:start])
        parts.append("[PII:" + label + "]")
        labels.append(label)
        pos = end
    parts.append(text[pos:])
    return "".join(parts), labels


def prepare(text, zone, policy, scan=None):
    """(allowed, reason, masked, tags). Reasons: ok, empty, policy off, zone not allowed,
    PII scan unavailable. masked is "" and tags is [] when not allowed."""
    if policy.get("mode") not in MODES or not MODES[policy["mode"]]:
        return False, "policy off", "", []
    if not text.strip():
        return False, "empty", "", []
    if zone not in MODES[policy["mode"]]:
        return False, "zone not allowed", "", []
    try:
        masked, tags = mask(text, scan)
    except Exception:
        return False, "PII scan unavailable", "", []
    return True, "ok", masked, tags


def cut(text, limit):
    """text cut to limit characters. A tag cut off by the limit is dropped whole: if the
    result ends inside a [PII: tag (or a partial "[PII:" prefix), it is cut back before it."""
    out = text[:limit]
    start = out.rfind("[")
    if start != -1:
        tail = out[start:]
        if "]" not in tail and ("[PII:".startswith(tail) or tail.startswith("[PII:")):
            out = out[:start]
    return out


def post_json(payload, key, timeout, endpoint):
    """POST the payload to Jev and return the parsed JSON. The key is never in an error."""
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def send(payload, env, timeout=4, call=None):
    """Send the payload with a total deadline of `timeout` seconds.

    Raises KeyError naming only TYPESAFE_API_KEY when no key is set, and TimeoutError
    when the call has not returned in time. The call runs in a daemon thread, so a
    stalled socket cannot hold the hook past its deadline.
    """
    key = (env.get("TYPESAFE_API_KEY") or "").strip()
    if not key:
        raise KeyError("TYPESAFE_API_KEY")
    endpoint = DEFAULT_ENDPOINT
    call = call or post_json
    box = {}

    def worker():
        try:
            box["ok"] = call(payload, key, timeout=timeout, endpoint=endpoint)
        except BaseException as err:
            box["err"] = err

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise TimeoutError("Jev did not answer within the time limit")
    if "err" in box:
        raise box["err"]
    return box["ok"]


def log_decision(use, sent_text, answers, cut, log_dir=LOG_DIR, ms=None):
    """Append one JSON line to log_dir/YYYY-MM-DD.jsonl. Never raises; never stores the text.

    ms, when given, is the wall time of the Jev call in milliseconds (R-67).
    """
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        top = {}
        for question, answer in answers.items():
            probs = answer.get("probabilities") or {}
            top[question] = max((float(v) for v in probs.values()), default=None)
        record = {
            "time": now.isoformat(timespec="seconds"),
            "use": use,
            "questions": sorted(answers),
            "choices": {q: a.get("choice") for q, a in answers.items()},
            "confidences": {q: a.get("confidence") for q, a in answers.items()},
            "top_probability": top,
            "sha256": hashlib.sha256(sent_text.encode("utf-8")).hexdigest(),
            "cut": bool(cut),
        }
        if ms is not None:
            record["ms"] = ms
        directory = pathlib.Path(log_dir)
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / (now.strftime("%Y-%m-%d") + ".jsonl")).open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass


def log_pii(use, masked_text, tags, confidence, log_dir=PII_DIR):
    """Append one JSON line to log_dir/YYYY-MM-DD.jsonl for a prompt Jev flagged as still
    holding personal data (R-65). The line keeps the masked text: the owner chose that.
    Never raises.
    """
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        record = {
            "time": now.isoformat(timespec="seconds"),
            "use": use,
            "confidence": confidence,
            "tags": list(tags),
            "sha256": hashlib.sha256(masked_text.encode("utf-8")).hexdigest(),
            "text": masked_text,
        }
        directory = pathlib.Path(log_dir)
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / (now.strftime("%Y-%m-%d") + ".jsonl")).open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass


def error_label(err):
    """The error type and, for HTTP errors, the status. Never the key, the message or the text."""
    status = getattr(err, "code", None)
    return type(err).__name__ + (" " + str(status) if status is not None else "")
