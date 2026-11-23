"""Runs tests.json against the live agent API and prints a results table.

    python benchmark/run.py                      # uses the deployed API
    python benchmark/run.py http://localhost:7860

Only needs Python (no packages). Each run uses fresh user ids, so old
memory from earlier runs cannot affect the result.
"""
import json
import pathlib
import sys
import time
import urllib.request
import uuid

API = (sys.argv[1] if len(sys.argv) > 1 else "https://shopbot-api-vnny.onrender.com").rstrip("/")
ROOT = pathlib.Path(__file__).resolve().parent.parent
RUN = uuid.uuid4().hex[:6]
PRICE_IN, PRICE_OUT = 0.10, 0.50  # USD per million tokens, claude-haiku-5-5


def chat(user: str, thread: str, message: str) -> tuple[dict, float]:
    body = json.dumps({"user_id": f"bench-{RUN}-{user}", "thread_id": thread, "message": message}).encode()
    req = urllib.request.Request(API + "/chat", body, {"Content-Type": "application/json"})
    start = time.time()
    with urllib.request.urlopen(req, timeout=120) as res:
        return json.load(res), time.time() - start


def check(step: dict, out: dict) -> list[str]:
    """Returns the list of failed checks (empty = pass)."""
    reply = out["reply"].lower()
    tools = [t["name"] for t in out["tool_calls"]]
    fails = []
    fails += [f"missing tool {t}" for t in step.get("tools_include", []) if t not in tools]
    fails += [f"unexpected tool {t}" for t in step.get("tools_exclude", []) if t in tools]
    if "reply_any" in step and not any(s.lower() in reply for s in step["reply_any"]):
        fails.append(f"reply has none of {step['reply_any']}")
    fails += [f"reply lacks '{s}'" for s in step.get("reply_all", []) if s.lower() not in reply]
    fails += [f"reply contains '{s}'" for s in step.get("reply_none", []) if s.lower() in reply]
    if "max_tokens_in" in step and out["tokens"]["in"] > step["max_tokens_in"]:
        fails.append(f"used {out['tokens']['in']} input tokens")
    return fails


def main() -> None:
    tests = json.loads((ROOT / "tests.json").read_text(encoding="utf-8"))["tests"]
    urllib.request.urlopen(API + "/health", timeout=120).read()  # wake the server
    rows, passed, tok_in, tok_out, times, messages, to_model = [], 0, 0, 0, [], 0, 0
    for t in tests:
        fails, t_in, t_out, secs = [], 0, 0, 0.0
        for step in t["steps"]:
            try:
                out, took = chat(step["user"], step["thread"], step["message"])
            except Exception as e:  # a failed request fails the test
                fails.append(f"request failed: {e}")
                break
            fails += check(step, out)
            t_in += out["tokens"]["in"]; t_out += out["tokens"]["out"]; secs += took
            times.append(took); messages += 1; to_model += out["tokens"]["in"] > 0
        ok = not fails
        passed += ok; tok_in += t_in; tok_out += t_out
        rows.append(f"| {t['id']} | {t['category']} | {t['name']} | {'PASS' if ok else 'FAIL'} | {t_in} | {t_out} | {secs:.1f} |")
        print(("PASS " if ok else "FAIL ") + t["id"], t["name"], "" if ok else fails)
    cost = (tok_in * PRICE_IN + tok_out * PRICE_OUT) / 1_000_000
    times.sort()
    median = times[len(times) // 2] if times else 0
    table = "\n".join([
        "| Test | Category | What it checks | Result | Tokens in | Tokens out | Seconds |",
        "|---|---|---|---|---|---|---|", *rows, "",
        f"**Pass rate: {passed}/{len(tests)} ({100 * passed // len(tests)}%)**. "
        f"Total tokens: {tok_in:,} in, {tok_out:,} out. Cost of the whole run: ${cost:.4f}.",
    ])
    notes = "\n".join([
        f"- {messages} messages were sent. {messages - to_model} were answered by the guard node at 0 tokens.",
        f"- Response time per message: median {median:.1f} s, slowest {times[-1] if times else 0:.1f} s.",
        f"- Average cost per message that reached the model: ${cost / max(to_model, 1):.5f}.",
    ])
    (ROOT / "benchmark" / "results.md").write_text(table + "\n\n" + notes + "\n", encoding="utf-8")

    # Put the same results into the README, between the two BENCHMARK markers.
    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    start, end = "<!-- BENCHMARK -->", "<!-- /BENCHMARK -->"
    if start in text and end in text:
        block = (f"{start}\nRun on {time.strftime('%d %b %Y')} against the live API "
                 f"(Render free plan, `claude-haiku-5-5`).\n\n{table}\n\n{notes}\n{end}")
        text = text[:text.index(start)] + block + text[text.index(end) + len(end):]
        readme.write_text(text, encoding="utf-8")
        print("\nREADME.md and benchmark/results.md updated.")
    print("\n" + table + "\n\n" + notes)


if __name__ == "__main__":
    main()
