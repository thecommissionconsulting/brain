"""Cases for jev_client.py, run from the repo root: python3 scripts/test_jev_client.py

No case reaches TypeSafe. Every network call is a fake. The key is the placeholder
"test-key". Policy files and decision logs go to temporary directories that the
script removes at the end.
"""
import hashlib
import importlib.util
import json
import pathlib
import shutil
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("jev_client", ROOT / "scripts" / "jev_client.py")
jc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jc)

FAILS = [0]
RAN = [0]
CREATED = []
KEY_ENV = {"TYPESAFE_API_KEY": "test-key"}
OFF = {"mode": "off"}


def case(name, got, want):
    ok = got == want
    RAN[0] += 1
    FAILS[0] += not ok
    print("  " + ("ok  " if ok else "FAIL") + "  " + name.ljust(46) +
          "want " + str(want)[:28].ljust(28) + " got " + str(got)[:28])


def raised(fn, *args):
    """The exception type fn raises with these arguments, or None."""
    try:
        fn(*args)
    except Exception as err:
        return type(err)
    return None


def elapsed(fn):
    """Seconds that fn takes to return."""
    start = time.monotonic()
    fn()
    return time.monotonic() - start


def tmp():
    """A new temporary directory, removed by remove_tmp()."""
    d = pathlib.Path(tempfile.mkdtemp(prefix="jev-client-test-"))
    CREATED.append(d)
    return d


def remove_tmp():
    for d in CREATED:
        shutil.rmtree(d, ignore_errors=True)


def write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


def readonly_dir():
    """A path that cannot be made into a log directory: a plain file sits where the folder would go.

    Works the same for a root user, who can write into a read-only folder.
    """
    base = tmp()
    blocker = base / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    return blocker


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_log(log_dir):
    """All decision-log lines written into log_dir, as one string."""
    return "".join(f.read_text(encoding="utf-8") for f in sorted(log_dir.glob("*.jsonl")))


def after_logging(text, ms=None):
    """Write one decision for text into a fresh log directory; return that directory."""
    log_dir = tmp()
    answers = {"kind": {"choice": "task", "confidence": 0.9, "probabilities": {"task": 0.9}}}
    jc.log_decision("classify", text, answers, False, log_dir, ms=ms)
    return log_dir


def clean(text):
    """A PII scan that finds nothing."""
    return []


def hit(text):
    """A PII scan that always finds one hit."""
    return [("email address", 0, len(text))]


def boom(text):
    """A PII scan that cannot run."""
    raise RuntimeError("scan broke")


def fake_ok(payload, key, timeout=0, endpoint=""):
    return {"answers": {}}


def fake_sleeps(seconds):
    def call(payload, key, timeout=0, endpoint=""):
        time.sleep(seconds)
        return {"answers": {}}
    return call


def captured_endpoint(env):
    seen = []

    def call(payload, key, timeout=0, endpoint=""):
        seen.append(endpoint)
        return {"answers": {}}

    jc.send({}, env, 4, call)
    return seen[0]


def main():
    tmp_dir = tmp()

    print("policy")
    case("policy: missing file is off", jc.load_policy(tmp_dir / "nope.json"), OFF)
    case("policy: bad JSON is off", jc.load_policy(write(tmp_dir / "bad.json", "{")), OFF)
    case("policy: unknown mode is off",
         jc.load_policy(write(tmp_dir / "m.json", '{"mode": "max"}'))["mode"], "off")
    case("policy: full mode reads as off",
         jc.load_policy(write(tmp_dir / "f.json", '{"mode": "full"}'))["mode"], "off")

    print("may_send")
    case("may_send: off sends nothing", jc.may_send("hello", "meta", OFF, scan=clean), (False, "policy off"))
    case("may_send: meta allows meta", jc.may_send("hello", "meta", {"mode": "meta"}, scan=clean), (True, "ok"))
    case("may_send: meta blocks wiki", jc.may_send("hello", "wiki", {"mode": "meta"}, scan=clean),
         (False, "zone not allowed"))
    case("may_send: client zone blocked under meta",
         jc.may_send("x", "client", {"mode": "meta"}, scan=clean), (False, "zone not allowed"))
    case("may_send: PII hit blocks", jc.may_send("a@b.com", "meta", {"mode": "meta"}, scan=hit),
         (False, "personal data"))
    case("may_send: scan error blocks", jc.may_send("x", "meta", {"mode": "meta"}, scan=boom),
         (False, "PII scan unavailable"))

    print("send")
    case("send: endpoint fixed despite env",
         captured_endpoint(env={"JEV_ENDPOINT": "https://evil.example", "TYPESAFE_API_KEY": "test-key"}),
         jc.DEFAULT_ENDPOINT)
    case("send: default endpoint", captured_endpoint(env={"TYPESAFE_API_KEY": "test-key"}),
         "https://api.typesafe.ai/v1/systemone")
    case("send: no key raises KeyError", raised(jc.send, {}, {}, 4, fake_ok), KeyError)
    case("send: slow call hits the deadline", raised(jc.send, {}, KEY_ENV, 0.2, fake_sleeps(2)), TimeoutError)
    case("send: deadline returns fast", elapsed(lambda: raised(jc.send, {}, KEY_ENV, 0.2, fake_sleeps(2))) < 0.5,
         True)

    print("log")
    case("log: no text in the log", "secret words" in read_log(after_logging("secret words")), False)
    case("log: hash is in the log", sha256("secret words") in read_log(after_logging("secret words")), True)
    case("log: unwritable dir does not raise", raised(jc.log_decision, "t", "x", {}, False, readonly_dir()), None)

    print("log ms")
    case("log_decision_ms: ms=12 is written", json.loads(read_log(after_logging("x", ms=12)))["ms"], 12)
    case("log_decision_ms: no ms, no key", "ms" in json.loads(read_log(after_logging("x"))), False)

    remove_tmp()
    print("\ntest_jev_client: " + str(RAN[0] - FAILS[0]) + " passed, " + str(FAILS[0]) + " failed.")
    return 1 if FAILS[0] else 0


if __name__ == "__main__":
    sys.exit(main())
