"""CEO Work Lab bridge (Phase 7, optional): lets the dashboard's "Agents ko abhi chalao"
button start the Research Director in **Claude Code's official headless mode** on this PC.

    Start_CEO_Bridge.bat   or   python -m ci_api.ceo_bridge   (CI_API_URL, default :8000)

What it does, and nothing more:

* every few seconds it tells the API it is alive (the page shows "bridge on");
* when the CEO requests a run, it claims it and starts ``claude -p`` (Claude Code CLI,
  the owner's own login) in the project folder, with the Director's instructions from
  ``.claude/commands/ceo-run.md`` on stdin, the project's MCP servers, and **only** the
  MCP tools the Director and the four agents are allowed (``--allowedTools``, taken from
  their definition files — no Bash, no file edits);
* if the CEO pauses or cancels the mission, it stops the process; it also stops it after
  ``CI_CEO_RUN_HOURS`` (default 3);
* it stores what Claude Code reports at the end (turns, tokens, notional cost) with the run.

It is opt-in: the owner starts it; nothing starts it automatically. It needs the Claude Code
CLI (``npm install -g @anthropic-ai/claude-code``, then ``claude`` once to sign in). Runs use
the owner's plan and count against its usage limits; the app never sees credentials.
Without the bridge, ``/ceo-run`` in Claude Code does the same thing by hand.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from typing import Any

from candle_intel.config.settings import PROJECT_ROOT

from .research_mcp import _call, _q

log = logging.getLogger("ci-ceo-bridge")

COMMAND = PROJECT_ROOT / ".claude" / "commands" / "ceo-run.md"
AGENTS = PROJECT_ROOT / ".claude" / "agents"
POLL_S = 5
WATCH_S = 15
MAX_TURNS = 200
HEADLESS_NOTE = (
    "You are running headless, started by the CEO from the dashboard through the local bridge. "
    "Nobody reads this terminal: talk to the CEO only with post_message and the final report.\n\n"
)


def _frontmatter(text: str) -> tuple[dict[str, str], str]:
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text.replace("\r\n", "\n"), re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip()
    return meta, m.group(2)


def allowed_tools() -> list[str]:
    """The Director's tools plus every specialist's — exactly what their files grant."""
    meta, _ = _frontmatter(COMMAND.read_text(encoding="utf-8"))
    tools = [t.strip() for t in meta.get("allowed-tools", "").split(",") if t.strip()]
    for f in sorted(AGENTS.glob("*.md")):
        m, _ = _frontmatter(f.read_text(encoding="utf-8"))
        tools += [t.strip() for t in m.get("tools", "").split(",") if t.strip()]
    out = list(dict.fromkeys(tools))
    bad = [t for t in out if t in ("Bash", "Write", "Edit", "NotebookEdit", "WebFetch")]
    if bad:
        raise RuntimeError(f"agent definitions grant disallowed tools: {bad}")
    return out


def director_prompt(mission_id: str) -> str:
    _, body = _frontmatter(COMMAND.read_text(encoding="utf-8"))
    return HEADLESS_NOTE + body.replace("$ARGUMENTS", mission_id)


def claude_cli() -> str | None:
    return os.environ.get("CI_CEO_CLAUDE_CMD") or shutil.which("claude")


def build_command(cli: str) -> list[str]:
    return [
        cli,
        "-p",
        "--output-format",
        "json",
        "--mcp-config",
        str(PROJECT_ROOT / ".mcp.json"),
        "--strict-mcp-config",
        "--max-turns",
        str(MAX_TURNS),
        "--allowedTools",
        ",".join(allowed_tools()),
    ]


def parse_usage(stdout: str) -> dict[str, Any]:
    """Claude Code's ``--output-format json`` result → the numbers we keep (if present)."""
    try:
        doc = json.loads(stdout.strip().splitlines()[-1]) if stdout.strip() else {}
    except (json.JSONDecodeError, IndexError):
        return {}
    u = doc.get("usage") or {}
    out = {
        "input_tokens": (u.get("input_tokens") or 0)
        + (u.get("cache_read_input_tokens") or 0)
        + (u.get("cache_creation_input_tokens") or 0),
        "output_tokens": u.get("output_tokens") or 0,
        "cost_usd": doc.get("total_cost_usd"),
        "turns": doc.get("num_turns"),
        "duration_s": round((doc.get("duration_ms") or 0) / 1000, 1),
        "is_error": doc.get("is_error"),
    }
    return {k: v for k, v in out.items() if v is not None}


def _mission_status(mission_id: str) -> str | None:
    m = _call("GET", f"/api/ceo/missions/{_q(mission_id)}")
    return m.get("status") if isinstance(m, dict) else None


def run_one(run: dict[str, Any], cli: str, hours: float, beat) -> dict[str, Any]:
    """Start the Director for one mission and follow it until it ends or must stop."""
    mid = run["mission_id"]
    proc = subprocess.Popen(  # noqa: S603 - fixed argv, owner-installed CLI, no shell
        build_command(cli),
        cwd=PROJECT_ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    chunks: list[str] = []
    reader = threading.Thread(target=lambda: chunks.extend(proc.stdout or []), daemon=True)
    reader.start()
    assert proc.stdin is not None
    proc.stdin.write(director_prompt(mid))
    proc.stdin.close()
    deadline = time.monotonic() + hours * 3600
    status = "done"
    while True:
        try:
            proc.wait(timeout=WATCH_S)
            break
        except subprocess.TimeoutExpired:
            beat()
            ms = _mission_status(mid)
            if ms in ("paused", "cancelled", "failed") or time.monotonic() > deadline:
                log.info("stopping run %s (mission %s, %s)", run["run_id"], mid, ms or "time limit")
                proc.terminate()
                try:
                    proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    proc.kill()
                status = "cancelled"
                break
    reader.join(timeout=5)
    out = "".join(chunks)
    code = proc.returncode
    if status == "done" and code != 0:
        status = "failed"
    return {"status": status, "exit_code": code, "usage": parse_usage(out) or None, "tail": out[-4000:]}


def serve(once: bool = False) -> None:
    hours = float(os.environ.get("CI_CEO_RUN_HOURS", "3"))
    cli = claude_cli()
    version = None
    if cli:
        try:
            version = subprocess.run(  # noqa: S603
                [cli, "--version"], capture_output=True, text=True, timeout=30
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError) as e:
            log.warning("claude CLI not usable: %s", e)
            cli = None
    info = {"cli": cli, "cli_version": version, "pid": os.getpid(), "run_hours": hours}
    if not cli:
        log.warning("Claude Code CLI not found. Install: npm install -g @anthropic-ai/claude-code")

    def beat(extra: dict[str, Any] | None = None) -> None:
        _call("POST", "/api/ceo/bridge/heartbeat", info | (extra or {}))

    log.info("CEO bridge up (cli=%s)", cli or "missing")
    while True:
        beat({"busy": None})
        if cli:
            run = _call("POST", "/api/ceo/bridge/claim", {})
            if isinstance(run, dict) and run.get("run"):
                r = run["run"]
                beat({"busy": r["mission_id"]})
                log.info("run %s for mission %s", r["run_id"], r["mission_id"])
                try:
                    res = run_one(r, cli, hours, lambda mid=r["mission_id"]: beat({"busy": mid}))
                except Exception as e:  # noqa: BLE001 - report every failure on the dashboard
                    res = {"status": "failed", "exit_code": None, "usage": None, "tail": repr(e)}
                _call("POST", f"/api/ceo/runs/{_q(r['run_id'])}/finish", res)
                log.info("run %s → %s", r["run_id"], res["status"])
        if once:
            return
        time.sleep(POLL_S)


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(message)s")
    try:
        serve()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
