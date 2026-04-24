"""
training/dataset.py

Pull real OSWorld agent trajectories from Hugging Face
(xlangai/ubuntu_osworld_verified_trajs). These are real recorded action
sequences from running computer-use agents (Claude, GPT, etc.) on the
OSWorld benchmark — they're the skeletons that synth.py turns into
emu-format trajectories.

Streams individual files out of the multi-GB zips via HTTP range requests,
so we never download the full archives. Cache layout:

    data/real_trajs/<zip_stem>/<task_uuid>/
        traj.jsonl      one step per line (action + reasoning + reward)
        result.txt      "1" pass / "0" fail on the OSWorld evaluator
        runtime.log     env logs (ignored)
        _files.json     local manifest

Usage:
    uv run python dataset.py list-runs
    uv run python dataset.py inspect-zip <zip_name>
    uv run python dataset.py fetch --zip <zip_name> --limit 100
    uv run python dataset.py show <task_id>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv
from huggingface_hub import HfApi
from remotezip import RemoteZip
from tqdm import tqdm

load_dotenv(Path(__file__).parent / ".env")

HF_TOKEN = os.getenv("HF_TOKEN", "").strip()
HF_TRAJ_REPO = "xlangai/ubuntu_osworld_verified_trajs"

REAL_TRAJS_DIR = Path(__file__).parent / "data" / "real_trajs"
REAL_TRAJS_DIR.mkdir(parents=True, exist_ok=True)

_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _hf_session() -> requests.Session:
    s = requests.Session()
    if HF_TOKEN:
        s.headers["Authorization"] = f"Bearer {HF_TOKEN}"
    s.headers["User-Agent"] = "emu-training/0.1"
    return s


def _zip_url(zip_name: str) -> str:
    return f"https://huggingface.co/datasets/{HF_TRAJ_REPO}/resolve/main/{zip_name}"


def _open_zip(zip_name: str) -> RemoteZip:
    return RemoteZip(_zip_url(zip_name), session=_hf_session())


def list_runs() -> list[dict]:
    api = HfApi(token=HF_TOKEN or None)
    info = api.repo_info(repo_id=HF_TRAJ_REPO, repo_type="dataset", files_metadata=True)
    out = [
        {"name": f.rfilename, "size_mb": (f.size or 0) // (1024 * 1024)}
        for f in info.siblings if f.rfilename.endswith(".zip")
    ]
    out.sort(key=lambda r: r["size_mb"])
    return out


def inspect_zip(zip_name: str, n: int = 30) -> dict:
    with _open_zip(zip_name) as zf:
        names = zf.namelist()
    ext_count: dict[str, int] = {}
    for name in names:
        ext = Path(name).suffix.lower() or "(none)"
        ext_count[ext] = ext_count.get(ext, 0) + 1
    return {
        "zip": zip_name,
        "total_entries": len(names),
        "sample_entries": names[:n],
        "extensions": dict(sorted(ext_count.items(), key=lambda kv: -kv[1])),
    }


def _extract_one(zf: RemoteZip, zip_stem: str, task_id: str) -> Path:
    out_dir = REAL_TRAJS_DIR / zip_stem / task_id
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = [
        n for n in zf.namelist()
        if task_id in n
        and not n.endswith("/")
        and not n.lower().endswith((".png", ".jpg", ".jpeg", ".mp4"))
    ]
    pulled = []
    for entry in targets:
        try:
            data = zf.read(entry)
        except Exception as e:
            print(f"[hf] skip {entry}: {e}", file=sys.stderr)
            continue
        (out_dir / Path(entry).name).write_bytes(data)
        pulled.append(Path(entry).name)
    (out_dir / "_files.json").write_text(json.dumps(pulled, indent=2), encoding="utf-8")
    return out_dir


def fetch(zip_name: str, limit: int = 50) -> list[Path]:
    zip_stem = Path(zip_name).stem
    out: list[Path] = []
    with _open_zip(zip_name) as zf:
        seen: set[str] = set()
        ids: list[str] = []
        for name in zf.namelist():
            m = _UUID_RE.search(name)
            if m and m.group(0) not in seen:
                seen.add(m.group(0))
                ids.append(m.group(0))
        ids = ids[:limit]
        print(f"[hf] {zip_name}: {len(seen)} task IDs total, fetching {len(ids)}")
        for tid in tqdm(ids, desc="trajs"):
            try:
                out.append(_extract_one(zf, zip_stem, tid))
            except Exception as e:
                print(f"[hf] {tid}: {e}", file=sys.stderr)
    return out


def iter_cached() -> list[Path]:
    return [d for d in sorted(REAL_TRAJS_DIR.glob("*/*")) if d.is_dir()]


def load_traj(traj_dir: Path) -> dict:
    """Load one cached trajectory: {task_id, zip, steps, result}."""
    steps = []
    traj_path = traj_dir / "traj.jsonl"
    if traj_path.exists():
        for line in traj_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    steps.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    result = None
    rp = traj_dir / "result.txt"
    if rp.exists():
        try:
            result = float(rp.read_text(encoding="utf-8").strip() or "0")
        except ValueError:
            result = None
    return {
        "task_id": traj_dir.name,
        "zip": traj_dir.parent.name,
        "steps": steps,
        "result": result,
    }


def show(task_id: str):
    for d in iter_cached():
        if d.name.startswith(task_id):
            t = load_traj(d)
            print(f"=== {d} ===")
            print(f"  result: {t['result']}   steps: {len(t['steps'])}")
            for s in t["steps"][:3]:
                act = s.get("action", {})
                print(f"  step {s.get('step_num')}: {act.get('input', act)}")
            return
    print(f"trajectory '{task_id}' not found", file=sys.stderr)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list-runs")
    iz = sub.add_parser("inspect-zip"); iz.add_argument("zip_name"); iz.add_argument("--n", type=int, default=30)
    f = sub.add_parser("fetch"); f.add_argument("--zip", dest="zip_name", required=True); f.add_argument("--limit", type=int, default=50)
    s = sub.add_parser("show"); s.add_argument("task_id")
    args = ap.parse_args()

    if args.cmd == "list-runs":
        for r in list_runs():
            print(f"{r['size_mb']:>6} MB  {r['name']}")
    elif args.cmd == "inspect-zip":
        print(json.dumps(inspect_zip(args.zip_name, args.n), indent=2))
    elif args.cmd == "fetch":
        paths = fetch(args.zip_name, args.limit)
        print(f"\n[hf] cached {len(paths)} trajectories -> {REAL_TRAJS_DIR}")
    elif args.cmd == "show":
        show(args.task_id)


if __name__ == "__main__":
    main()
