"""
training/synth.py

Take a REAL OSWorld agent trajectory (from data/real_trajs/, pulled via
dataset.py) and ask Claude to rewrite it as a synthetic EMU trajectory --
same task, same general action sequence, but in emu's exact format with
emu's scaffolding (plan.md, write_session_file, use_skill, compact_context,
invoke_hermes when appropriate).

Output: JSONL, one line per trajectory. Each line is harness-compatible
(emu system prompt + persona stitched in at write time).

Usage:
    uv run python synth.py --count 10
    uv run python synth.py --count 10 --out data/synthetic/run1.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv(Path(__file__).parent / ".env")

from buffer import Buffer
from harness import PERSONAS, build_full_system_prompt, get_skills_catalog

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5").strip()
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "8192"))
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.7"))

SYNTH_DIR = Path(__file__).parent / "data" / "synthetic"
SYNTH_DIR.mkdir(parents=True, exist_ok=True)


# ── skill routing ────────────────────────────────────────────────────────────
_APP_TO_SKILLS: dict[str, list[str]] = {
    "chrome":              ["google-chrome", "web-search"],
    "vscode":              ["vscode-open-repo", "file-manager"],
    "libreoffice_calc":    ["libreoffice-open", "microsoft-excel"],
    "libreoffice_writer":  ["libreoffice-open", "microsoft-word"],
    "libreoffice_impress": ["libreoffice-open", "microsoft-powerpoint"],
    "thunderbird":         ["microsoft-outlook", "gmail"],
    "vlc":                 ["vlc-play-file"],
    "gimp":                ["file-manager", "app-launcher"],
    "os":                  ["app-launcher", "system-info", "file-manager"],
    "multi_apps":          ["app-launcher"],
}


def relevant_skills_for(zip_or_path: str) -> list[str]:
    """The HF zip stem / step paths embed the OSWorld app folder; sniff it."""
    out: list[str] = []
    s = (zip_or_path or "").lower()
    for app, skills in _APP_TO_SKILLS.items():
        if app in s:
            out.extend(sk for sk in skills if sk not in out)
    if "app-launcher" not in out:
        out.append("app-launcher")
    return out


# ── emu tool catalog (must match backend/prompts/system_prompt.py) ───────────
EMU_TOOL_CATALOG = """\
EMU FUNCTION TOOLS (called via Anthropic tool_use blocks):
  - update_plan(content: str)              write/overwrite plan.md
  - read_plan()                            re-read plan.md
  - write_session_file(filename, content)  scratchpad notes
  - read_session_file(filename)            read a scratchpad
  - list_session_files()
  - read_memory(target, date?)             target in {long_term, preferences, daily_log}
  - use_skill(skill_name)                  load a skill's full body
  - compact_context(focus?)                compress chain when getting long
  - shell_exec(command)                    sandboxed shell INSIDE .emu (no curl/wget/sudo/rm -rf)
  - invoke_hermes(goal, context, file_paths?, output_target?, constraints?)
  - check_hermes(job_id, wait_s?)          MUST follow every invoke
  - list_hermes_jobs() / cancel_hermes(job_id)

EMU DESKTOP ACTIONS - returned as ONE assistant text block whose text is raw
JSON. Coordinates normalized [0,1]:
  {"action": {"type": "screenshot"}}
  {"action": {"type": "navigate_and_click", "coordinates": {"x": 0.45, "y": 0.32}}}
  {"action": {"type": "navigate_and_right_click", "coordinates": {...}}}
  {"action": {"type": "navigate_and_triple_click", "coordinates": {...}}}
  {"action": {"type": "left_click"}}        # at current cursor
  {"action": {"type": "double_click"}}
  {"action": {"type": "triple_click"}}
  {"action": {"type": "right_click"}}
  {"action": {"type": "mouse_move", "coordinates": {...}}}
  {"action": {"type": "type_text", "text": "..."}}
  {"action": {"type": "key_press", "key": "enter"}}
  {"action": {"type": "key_press", "key": "l", "modifiers": ["cmd"]}}
  {"action": {"type": "scroll", "direction": "down", "amount": 5}}
  {"action": {"type": "drag", "coordinates": {...}, "end_coordinates": {...}}}
  {"action": {"type": "wait", "ms": 1000}}
  {"action": {"type": "done"}, "done": true, "final_message": "..."}
Modifiers: cmd, ctrl, alt, shift (use "cmd" -- NOT meta/super/win).
"""


SYNTH_SYSTEM = f"""\
You are a synthetic-data author. You will be given a REAL agent trajectory
that solved an OSWorld task (recorded actions + reasoning from a different
computer-use agent). Your job is to rewrite it as a trajectory that looks
exactly like the **Emu desktop automation agent** produced it -- same task,
same overall action sequence, but in Emu's exact format with Emu's scaffolding.

{EMU_TOOL_CATALOG}

ACTION TRANSLATION (from the real trajectory's "computer" tool calls to emu):
  left_click [x,y]             -> navigate_and_click   {{x,y normalized}}
  right_click [x,y]            -> navigate_and_right_click
  double_click [x,y]           -> navigate_and_click then double_click
  left_click_drag [a]->[b]     -> drag {{coordinates: a, end_coordinates: b}}
  type "..."                   -> type_text
  key "Return"                 -> key_press {{"key": "enter"}}
  key "ctrl+c"                 -> key_press {{"key": "c", "modifiers": ["ctrl"]}}
  scroll                       -> scroll
  screenshot                   -> screenshot
Coords: divide by screen size 1920x1080 unless trajectory says otherwise.
Round to 3 decimal places.

EMU SCAFFOLDING TO ADD (the real trajectory does NOT have these -- weave in
4-7 of these naturally; do not oversaturate):
  1. update_plan(...) at the start for any 3+ step task. Then STOP and wait
     for plan approval (next user turn = "[PLAN APPROVED]") before any
     desktop action.
  2. read_memory(target="long_term") right at task start.
  3. use_skill(...) MUST appear at least once early (after read_memory,
     before the first desktop action). Pick from the SKILL CATALOG in the
     user prompt. tool_result is a short plausible markdown body.
  4. write_session_file when info is gathered (urls, names, prices).
  5. read_plan() / read_session_file when re-orienting.
  6. compact_context(focus="...") if real trajectory had 20+ steps.
  7. shell_exec for filesystem work inside .emu (open -a, mdfind, find,
     cat, python3 -c). Never curl/wget/sudo/rm -rf.
  8. invoke_hermes for HEAVY non-GUI work the real trajectory did with
     many GUI clicks. ALWAYS follow with check_hermes(job_id, wait_s=60).
  9. ANTI-LOOP: if real trajectory repeated a failing action, change
     strategy in your version.
 10. FOCUS SAFETY: click into the target app before any input.
 11. Mark plan steps [x] with another update_plan call as you progress.

OUTPUT FORMAT - RETURN ONE JSON OBJECT, NOTHING ELSE:

{{
  "task_id": "<the OSWorld task uuid>",
  "instruction": "<verbatim user instruction inferred from the real trajectory>",
  "messages": [
    {{"role": "user", "content": [{{"type": "text", "text": "<task instruction>"}}]}},
    {{"role": "assistant", "content": [
        {{"type": "text", "text": "<brief reasoning>"}},
        {{"type": "tool_use", "id": "toolu_001", "name": "read_memory",
         "input": {{"target": "long_term"}}}}
    ]}},
    {{"role": "user", "content": [
        {{"type": "tool_result", "tool_use_id": "toolu_001",
         "content": "<plausible memory contents>"}}
    ]}},
    ... continue alternating ...
    {{"role": "assistant", "content": [
        {{"type": "text", "text":
          "{{\\"action\\": {{\\"type\\": \\"navigate_and_click\\", \\"coordinates\\": {{\\"x\\": 0.225, \\"y\\": 0.218}}}}, \\"done\\": false}}"}}
    ]}},
    {{"role": "user", "content": [
        {{"type": "text", "text": "[ACTION OK] Clicked at (0.225, 0.218). <screenshot omitted>"}}
    ]}},
    ...
    {{"role": "assistant", "content": [
        {{"type": "text", "text":
          "{{\\"action\\": {{\\"type\\": \\"done\\"}}, \\"done\\": true, \\"final_message\\": \\"...\\"}}"}}
    ]}}
  ]
}}

HARD RULES:
  - Function tools (the 13 above) MUST be Anthropic tool_use / tool_result
    blocks. NEVER stringify them as desktop-action JSON.
  - Desktop actions MUST be a single assistant text block with raw JSON.
    NEVER as tool_use blocks.
  - Coordinates normalized [0,1], 3 decimals.
  - One desktop action per assistant message. Each is followed by an
    [ACTION OK] / [ACTION FAILED] user feedback turn.
  - Stay faithful to the real trajectory's action sequence -- do NOT
    invent a different solution path. You may compress repetitive
    consecutive identical actions.
  - Final assistant message MUST be a desktop "done" action with
    final_message.
  - Output ONLY the JSON object. No markdown fences, no commentary.
"""


def _summarize_step(step: dict) -> str:
    """Compact one-line summary of a real-trajectory step for the prompt."""
    act = step.get("action", {}) or {}
    inp = act.get("input", {}) or {}
    name = inp.get("action") or act.get("name") or "?"
    parts = [f"#{step.get('step_num', '?')} {name}"]
    for k in ("coordinate", "start_coordinate", "text", "key", "scroll_direction"):
        if k in inp:
            v = inp[k]
            if isinstance(v, str) and len(v) > 80:
                v = v[:80] + "..."
            parts.append(f"{k}={v}")
    resp = (step.get("response") or "").strip().replace("\n", " ")
    if resp:
        parts.append(f"// {resp[:140]}")
    return " ".join(parts)


def build_user_prompt(real: dict) -> str:
    skills = relevant_skills_for(real.get("zip", ""))
    catalog = get_skills_catalog()
    desc_by_name = {n: d for n, d in catalog}
    skills_block = "\n".join(
        f"  - {n} -- {desc_by_name.get(n, '(custom user skill)')}" for n in skills
    )

    steps = real.get("steps", [])
    instruction = ""
    if steps:
        first_resp = steps[0].get("response", "") or ""
        raw = (steps[0].get("action", {}) or {}).get("raw_response", "") or ""
        for hay in (raw, first_resp):
            if "user wants" in hay.lower() or "user asked" in hay.lower():
                instruction = hay.strip().split("\n", 1)[0][:400]
                break

    step_lines = "\n".join(_summarize_step(s) for s in steps)

    return f"""\
Rewrite this REAL OSWorld trajectory as an EMU trajectory.

TASK ID: {real.get('task_id')}
SOURCE RUN (HF zip): {real.get('zip')}
RESULT (1=passed evaluator): {real.get('result')}
INSTRUCTION (inferred from agent's first reasoning, refine if needed):
{instruction or '(infer from action sequence below)'}

REAL ACTION SEQUENCE ({len(steps)} steps):
{step_lines}

SKILL CATALOG (relevant -- pick at least one to use_skill on early):
{skills_block}

Now produce the JSON emu trajectory object as specified.
"""


def _strip_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s.rsplit("```", 1)[0]
    return s.strip()


def _extract_json(text: str) -> dict:
    text = _strip_fences(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


def generate_one(client: Anthropic, real: dict) -> dict:
    resp = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        system=SYNTH_SYSTEM,
        messages=[{"role": "user", "content": build_user_prompt(real)}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    traj = _extract_json(text)
    traj.setdefault("task_id", real.get("task_id"))
    traj["_meta"] = {
        "model": ANTHROPIC_MODEL,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "source_zip": real.get("zip"),
        "source_steps": len(real.get("steps", [])),
        "source_result": real.get("result"),
    }
    return traj


def attach_harness_prompt(traj: dict, persona_idx: int) -> dict:
    traj["system"] = build_full_system_prompt(persona_idx=persona_idx)
    traj.setdefault("_meta", {})
    traj["_meta"]["persona_idx"] = persona_idx
    traj["_meta"]["persona_name"] = (
        PERSONAS[persona_idx % len(PERSONAS)]["USER.md"]
        .splitlines()[1].split(":", 1)[-1].strip()
    )
    return traj


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    if not ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY not set in training/.env", file=sys.stderr)
        sys.exit(1)

    out_path = args.out or (SYNTH_DIR / f"synth-{datetime.utcnow():%Y%m%dT%H%M%S}.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    buf = Buffer()
    added = buf.scan()
    if added:
        print(f"[synth] indexed {added} new real trajectories")

    written = 0
    with open(out_path, "a", encoding="utf-8") as f:
        pbar = tqdm(total=args.count, desc="synth")
        while written < args.count:
            entry = buf.next()
            if entry is None:
                print("[synth] no pending real trajectories -- run dataset.py fetch first",
                      file=sys.stderr)
                break
            try:
                traj = generate_one(client, entry["real"])
                traj = attach_harness_prompt(traj, persona_idx=written)
                f.write(json.dumps(traj, ensure_ascii=False) + "\n")
                f.flush()
                buf.mark_done(entry["task_id"])
                written += 1
                pbar.update(1)
            except Exception as e:
                print(f"[synth] {entry['task_id']} failed: {e}", file=sys.stderr)
                buf.mark_failed(entry["task_id"], str(e))
                time.sleep(2)
        pbar.close()

    print(f"\n[synth] wrote {written} trajectories -> {out_path}")


if __name__ == "__main__":
    main()
