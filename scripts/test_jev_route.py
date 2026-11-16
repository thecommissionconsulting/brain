"""Cases for jev_route.py, run from the repo root: python scripts/test_jev_route.py

No case reaches TypeSafe. The network call is replaced with a fake wherever a case
needs one, and the decision log is replaced with a recorder, so no case writes to
_local/. The key cases use the placeholder "test-key" and check that it never
appears in what the script prints, because a key in a log is a leaked key.
"""
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("jev_route", ROOT / "scripts" / "jev_route.py")
jr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jr)
sys.path.insert(0, str(ROOT / "scripts"))
import jev_client as jc  # noqa: E402  the same module jev_route imports

FAILS = [0]
RAN = [0]
META = {"mode": "meta"}
OFF = {"mode": "off"}
LOGGED = []


def record_log(use, sent_text, answers, cut, log_dir=None, ms=None):
    """Stands in for jev_client.log_decision: keeps only what it would write, never _local/.

    The text itself is not kept: the real log stores only its SHA-256, and that is
    tested against a temporary folder in test_jev_client.py.
    """
    LOGGED.append((use, sorted(answers), cut))


REAL_LOG = jc.log_decision
jc.log_decision = record_log


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


def answer(choice, confidence):
    return {"answers": {"skill": {"choice": choice, "confidence": confidence,
                                  "probabilities": {choice: confidence}}}}


def run_main(argv, env_key=None, fake=None, policy=None):
    """Run main with a controlled key, policy and fake network call; return (code, stdout, stderr)."""
    real_call = jr.call_jev
    real_policy = getattr(jr, "load_policy", None)
    saved = os.environ.pop("TYPESAFE_API_KEY", None)
    if env_key is not None:
        os.environ["TYPESAFE_API_KEY"] = env_key
    if fake is not None:
        jr.call_jev = fake
    chosen = policy if policy is not None else META
    jr.load_policy = lambda path=None: dict(chosen)
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = jr.main(argv)
            except SystemExit as stop:
                code = stop.code
    finally:
        jr.call_jev = real_call
        if real_policy is not None:
            jr.load_policy = real_policy
        os.environ.pop("TYPESAFE_API_KEY", None)
        if saved is not None:
            os.environ["TYPESAFE_API_KEY"] = saved
    return code, out.getvalue(), err.getvalue()


def run_hook_main(stdin_bytes, env_key=None, fake=None):
    """Run main(["--hook"]) with real bytes on stdin; return (code, stdout, stderr)."""
    real_stdin = sys.stdin
    sys.stdin = io.TextIOWrapper(io.BytesIO(stdin_bytes), encoding="utf-8")
    try:
        return run_main(["--hook"], env_key=env_key, fake=fake)
    finally:
        sys.stdin = real_stdin


def recording_fake(answer_payload, calls):
    def fake(payload, key, timeout=30):
        calls.append(payload)
        return answer_payload
    return fake


def main():
    req = jr.build_request("  Add a CSV export to the reports page  ")
    case("the text goes in state", req["state"], "Add a CSV export to the reports page")
    case("the model is named", req["model"], jr.MODEL)

    criteria = req["questions"]["skill"]["criteria"]
    case("criteria keys are the skills in order", list(criteria), list(jr.SKILLS))
    case("there are seven skills", len(criteria), 7)

    long_text = "x" * (jr.MAX_CHARS + 500)
    case("a long summary is cut to MAX_CHARS", len(jr.build_request(long_text)["state"]), jr.MAX_CHARS)

    case("empty text raises ValueError", raised(jr.build_request, ""), ValueError)
    case("whitespace-only text raises ValueError", raised(jr.build_request, " \n\t "), ValueError)

    good = jr.parse_response(answer("systematic-debugging", 0.9))
    case("a confident answer returns the choice", good["skill"], "systematic-debugging")
    case("and does not ask the user", good["ask_user"], False)

    unsure = jr.parse_response(answer("writing-plans", 0.4))
    case("a low-confidence answer asks the user", unsure["ask_user"], True)

    unknown = jr.parse_response(answer("made-up-skill", 0.9))
    case("an unknown choice gives no skill", unknown["skill"], None)
    case("and asks the user", unknown["ask_user"], True)

    case("a response with no answers raises ValueError",
         raised(jr.parse_response, {}), ValueError)

    code, out, err = run_main(["--text", "x"])
    case("no key exits 2", code, 2)
    case("and says where to set it", "TYPESAFE_API_KEY is not set" in err, True)

    def fake_ok(payload, key, timeout=30):
        return answer("brainstorming", 0.8)

    code, out, err = run_main(["--text", "Plan the new export"], env_key="test-key", fake=fake_ok)
    case("a routed Build exits 0", code, 0)
    case("the answer is printed as JSON", '"skill": "brainstorming"' in out, True)
    case("the key is never printed", "test-key" in out or "test-key" in err, False)

    def fake_down(payload, key, timeout=30):
        raise urllib.error.URLError("connection refused")

    code, out, err = run_main(["--text", "Plan the new export"], env_key="test-key", fake=fake_down)
    case("a failed call exits 3", code, 3)
    case("the failure names the error type", "Jev call failed: URLError" in err, True)
    case("the key is never in the error", "test-key" in err or "test-key" in out, False)

    def fake_slow(payload, key, timeout=30):
        raise TimeoutError("slow")

    code, out, err = run_main(["--text", "Plan the new export"], env_key="test-key", fake=fake_slow)
    case("a call past the deadline exits 3", code, 3)
    case("and names TimeoutError", "Jev call failed: TimeoutError" in err, True)

    code, out, err = run_main([])
    case("no file and no --text exits 2", code, 2)

    code, out, err = run_main(["--text", "x", "also-a-file.md"])
    case("both a file and --text exits 2", code, 2)

    # --- policy and the egress gate on the Build path ---
    build_calls = []
    code, out, err = run_main(["--text", "Plan the new export"], env_key="test-key",
                              fake=recording_fake(answer("brainstorming", 0.8), build_calls),
                              policy=OFF)
    case("build: policy off exits 2", code, 2)
    case("build: policy off names the policy file",
         "Jev disabled by policy (_local/jev-policy.json)" in err, True)
    case("build: policy off never calls Jev", len(build_calls), 0)

    code, out, err = run_main(["--text", "Mail a@b.com about it"], env_key="test-key",
                              fake=recording_fake(answer("brainstorming", 0.8), build_calls),
                              policy=META)
    case("build: personal data exits 2", code, 2)
    case("build: personal data names the reason", "personal data" in err, True)
    case("build: personal data never calls Jev", len(build_calls), 0)

    del LOGGED[:]
    code, out, err = run_main(["--text", "Plan the new export"], env_key="test-key",
                              fake=recording_fake(answer("brainstorming", 0.8), build_calls))
    case("build: a routed call is logged as build", [entry[0] for entry in LOGGED], ["build"])
    case("build: the log gets the answer's questions", LOGGED[0][1] if LOGGED else None, ["skill"])
    case("build: the log gets the cut flag as False", LOGGED[0][2] if LOGGED else None, False)

    # --- the send path goes through jev_client ---
    case("ENDPOINT is the client's endpoint", jr.ENDPOINT, jc.DEFAULT_ENDPOINT)
    case("the old CENTRAL path is gone", hasattr(jr, "CENTRAL"), False)
    case("jev_route has no urlopen of its own", "urlopen(" in pathlib.Path(jr.__file__).read_text(encoding="utf-8"), False)

    seen = {}

    def fake_post(payload, key, timeout, endpoint):
        seen["endpoint"] = endpoint
        seen["timeout"] = timeout
        return answer("task", 0.9)

    def no_network(*args, **kwargs):
        raise AssertionError("a test reached the network")

    real_post = jc.post_json
    real_urlopen = urllib.request.urlopen
    jc.post_json = fake_post
    urllib.request.urlopen = no_network
    try:
        jr.call_jev({"state": "x"}, "test-key", timeout=7)
    except AssertionError:
        pass
    finally:
        jc.post_json = real_post
        urllib.request.urlopen = real_urlopen
    case("call_jev sends to the client's endpoint", seen.get("endpoint"), jc.DEFAULT_ENDPOINT)
    case("call_jev passes its timeout on", seen.get("timeout"), 7)

    # --- classify: build_classify_request ---
    creq = jr.build_classify_request("  What time is it in Auckland?  ")
    case("classify: the question key is kind", "kind" in creq["questions"], True)
    case("classify: criteria keys are the kinds", list(creq["questions"]["kind"]["criteria"]), list(jr.KINDS))
    case("classify: the result keys are exact", set(creq), {"state", "model", "questions"})
    case("classify: the text is stripped", creq["state"], "What time is it in Auckland?")
    case("classify: a long prompt is cut to HOOK_MAX_CHARS",
         len(jr.build_classify_request("x" * (jr.HOOK_MAX_CHARS + 500))["state"]), jr.HOOK_MAX_CHARS)
    case("classify: empty text raises ValueError", raised(jr.build_classify_request, "  "), ValueError)

    # --- classify: parse_classify_response ---
    def kind_answer(choice, confidence):
        return {"answers": {"kind": {"choice": choice, "confidence": confidence,
                                     "probabilities": {choice: confidence}}}}

    cbuild = jr.parse_classify_response(kind_answer("build", 0.9))
    case("classify parse: a confident build gives kind build", cbuild["kind"], "build")
    case("classify parse: and does not ask the user", cbuild["ask_user"], False)
    ctask = jr.parse_classify_response(kind_answer("task", 0.4))
    case("classify parse: a low-confidence task asks the user", ctask["ask_user"], True)
    cunknown = jr.parse_classify_response(kind_answer("made-up-kind", 0.9))
    case("classify parse: an unknown kind gives None", cunknown["kind"], None)
    case("classify parse: and asks the user", cunknown["ask_user"], True)
    case("classify parse: an empty response raises ValueError",
         raised(jr.parse_classify_response, {}), ValueError)

    # --- classify: hook_context ---
    case("hook context: a confident build",
         jr.hook_context({"kind": "build", "confidence": 0.82, "ask_user": False}),
         "Jev labels this prompt a Build (confidence 0.82). Treat it as a hint; you decide.")
    case("hook context: an unsure task names its best guess",
         jr.hook_context({"kind": "task", "confidence": 0.41, "ask_user": True}),
         "Jev is unsure about this prompt (best guess: Task, confidence 0.41). Classify it yourself.")
    case("hook context: no usable label",
         jr.hook_context({"kind": None, "confidence": 0.9, "ask_user": True}),
         "Jev gave no usable label for this prompt. Classify it yourself.")

    # --- classify: should_send ---
    case("should_send: empty prompt", jr.should_send("", scan=lambda t: [], policy=META), (False, "empty"))
    case("should_send: slash command", jr.should_send("/help", scan=lambda t: [], policy=META),
         (False, "slash command"))
    case("should_send: personal data found",
         jr.should_send("hello", scan=lambda t: [("email address", 0, 5)], policy=META),
         (False, "personal data"))
    def scan_broken(t):
        raise RuntimeError("boom")
    case("should_send: a broken scan fails closed",
         jr.should_send("hello", scan=scan_broken, policy=META), (False, "PII scan unavailable"))
    case("should_send: clean prompt", jr.should_send("hello", scan=lambda t: [], policy=META), (True, "ok"))
    case("should_send: policy off sends nothing",
         jr.should_send("hello", scan=lambda t: [], policy=OFF), (False, "policy off"))
    case("should_send: real scan finds an email",
         jr.should_send("email someone@client-domain.com please", policy=META), (False, "personal data"))

    # --- classify: run_hook ---
    clean = lambda t: []
    calls = []
    out = jr.run_hook(json.dumps({"prompt": "What time is it in Auckland?"}),
                      {"TYPESAFE_API_KEY": "test-key"},
                      call=recording_fake(kind_answer("question", 0.9), calls), scan=clean, policy=META)
    case("run_hook: the context is in the output", "additionalContext" in out, True)
    case("run_hook: the label is a Question", "a Question" in out, True)
    case("run_hook: the request has exactly the three keys",
         set(calls[0]) if calls else None, {"state", "model", "questions"})
    case("run_hook: the request state is the prompt",
         calls[0]["state"] if calls else None, "What time is it in Auckland?")

    calls = []
    jr.run_hook(json.dumps({"prompt": "What time is it in Auckland?", "session_id": "sess-secret",
                            "transcript_path": "/x/y"}),
                {"TYPESAFE_API_KEY": "test-key"},
                call=recording_fake(kind_answer("question", 0.9), calls), scan=clean, policy=META)
    sent_text = json.dumps(calls[0]) if calls else ""
    case("run_hook: the session id never leaves", "sess-secret" in sent_text, False)
    case("run_hook: the transcript path never leaves", "/x/y" in sent_text, False)

    calls = []
    out = jr.run_hook(json.dumps({"prompt": "What time is it in Auckland?"}), {},
                      call=recording_fake(kind_answer("question", 0.9), calls), scan=clean, policy=META)
    case("run_hook: no key gives no output", out, "")
    case("run_hook: no key never calls Jev", len(calls), 0)

    calls = []
    out = jr.run_hook(json.dumps({"prompt": "Email someone@client-domain.com"}),
                      {"TYPESAFE_API_KEY": "test-key"},
                      call=recording_fake(kind_answer("question", 0.9), calls),
                      scan=lambda t: [("email address", 0, 5)], policy=META)
    case("run_hook: personal data gives no output", out, "")
    case("run_hook: personal data never calls Jev", len(calls), 0)

    calls = []
    out = jr.run_hook(json.dumps({"prompt": "What time is it in Auckland?"}),
                      {"TYPESAFE_API_KEY": "test-key"},
                      call=recording_fake(kind_answer("question", 0.9), calls), scan=clean, policy=OFF)
    case("run_hook: policy off gives no output", out, "")
    case("run_hook: policy off never calls Jev", len(calls), 0)

    def fake_refused(payload, key, timeout=30):
        raise urllib.error.URLError("refused")

    out = jr.run_hook(json.dumps({"prompt": "What time is it in Auckland?"}),
                      {"TYPESAFE_API_KEY": "test-key"}, call=fake_refused, scan=clean, policy=META)
    case("run_hook: a failed call names the error type", "Jev classify failed: URLError" in out, True)
    case("run_hook: the failure has no key", "test-key" in out, False)
    case("run_hook: the failure has no prompt text", "What time" in out, False)

    def fake_timeout(payload, key, timeout=30):
        raise TimeoutError("slow")

    out = jr.run_hook(json.dumps({"prompt": "What time is it in Auckland?"}),
                      {"TYPESAFE_API_KEY": "test-key"}, call=fake_timeout, scan=clean, policy=META)
    case("run_hook: a timeout names TimeoutError", out.count("Jev classify failed: TimeoutError") == 1, True)

    del LOGGED[:]
    jr.run_hook(json.dumps({"prompt": "What time is it in Auckland?"}),
                {"TYPESAFE_API_KEY": "test-key"},
                call=recording_fake(kind_answer("question", 0.9), []), scan=clean, policy=META)
    case("run_hook: a routed prompt is logged as prompt", [entry[0] for entry in LOGGED], ["prompt"])

    # --- classify: main --hook ---
    code, out, err = run_hook_main(b"not json")
    case("main --hook: bad stdin exits 0", code, 0)
    case("main --hook: bad stdin prints nothing", out, "")

    def fake_question(payload, key, timeout=30):
        return kind_answer("question", 0.9)

    code, out, err = run_hook_main(b'{"prompt": "What time is it in Auckland?"}',
                                   env_key="test-key", fake=fake_question)
    case("main --hook: a valid prompt exits 0", code, 0)
    case("main --hook: the context is printed", "additionalContext" in out, True)

    code, out, err = run_main(["--hook", "--text", "x"])
    case("main --hook with --text exits 2", code, 2)

    # --- timing: the hook records how long the Jev call took (R-67) ---
    timed_dir = pathlib.Path(tempfile.mkdtemp(prefix="jev-route-ms-"))

    def timed_log(use, sent_text, answers, cut, log_dir=None, ms=None):
        REAL_LOG(use, sent_text, answers, cut, timed_dir, ms=ms)

    def slow_question(payload, key, timeout=30):
        time.sleep(0.01)
        return kind_answer("question", 0.9)

    try:
        jc.log_decision = timed_log
        jr.run_hook(json.dumps({"prompt": "What time is it in Auckland?"}),
                    {"TYPESAFE_API_KEY": "test-key"}, call=slow_question, scan=clean, policy=META)
        records = [json.loads(line) for f in sorted(timed_dir.glob("*.jsonl"))
                   for line in f.read_text(encoding="utf-8").splitlines()]
        case("hook_logs_ms: one record written", len(records), 1)
        case("hook_logs_ms: ms >= 10", records[0].get("ms", -1) >= 10 if records else False, True)
    finally:
        jc.log_decision = record_log
        shutil.rmtree(timed_dir, ignore_errors=True)

    print("\ntest_jev_route: " + str(RAN[0] - FAILS[0]) + " passed, " + str(FAILS[0]) + " failed.")
    return 1 if FAILS[0] else 0


if __name__ == "__main__":
    sys.exit(main())
