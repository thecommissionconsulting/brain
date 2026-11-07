"""Cases for jev_route.py, run from the repo root: python scripts/test_jev_route.py

No case reaches TypeSafe. The network call is replaced with a fake wherever a case
needs one. The key cases use the placeholder "test-key" and check that it never
appears in what the script prints, because a key in a log is a leaked key.
"""
import contextlib
import importlib.util
import io
import os
import pathlib
import sys
import urllib.error

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("jev_route", ROOT / "scripts" / "jev_route.py")
jr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jr)

FAILS = [0]
RAN = [0]


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


def run_main(argv, env_key=None, fake=None):
    """Run main with a controlled key and fake network call; return (code, stdout, stderr)."""
    real_call = jr.call_jev
    saved = os.environ.pop("TYPESAFE_API_KEY", None)
    if env_key is not None:
        os.environ["TYPESAFE_API_KEY"] = env_key
    if fake is not None:
        jr.call_jev = fake
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = jr.main(argv)
            except SystemExit as stop:
                code = stop.code
    finally:
        jr.call_jev = real_call
        os.environ.pop("TYPESAFE_API_KEY", None)
        if saved is not None:
            os.environ["TYPESAFE_API_KEY"] = saved
    return code, out.getvalue(), err.getvalue()


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

    code, out, err = run_main([])
    case("no file and no --text exits 2", code, 2)

    code, out, err = run_main(["--text", "x", "also-a-file.md"])
    case("both a file and --text exits 2", code, 2)

    print("\ntest_jev_route: " + str(RAN[0] - FAILS[0]) + " passed, " + str(FAILS[0]) + " failed.")
    return 1 if FAILS[0] else 0


if __name__ == "__main__":
    sys.exit(main())
