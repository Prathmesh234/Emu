# Coworker Mode Setup — Complete Summary

## What Was Done

### ✅ Folder Structure Created

```
frontend/
├── coworker-driver/              # Specs & skills (documentation hub)
│   ├── SPEC.md                   # Implementation blueprint (1,002 lines)
│   ├── SKILL.md                  # Claude Code skill reference (886 lines)
│   ├── WEB_APPS.md               # Browser/Electron patterns (470 lines)
│   ├── TESTS.md                  # Test cases & runbooks (232 lines)
│   ├── RECORDING.md              # Trajectory recording (114 lines)
│   ├── README.md                 # Developer guide
│   └── SUMMARY.md                # Consolidated reference
│
└── coworker-mode/                # Fork management & emu-driver source
    ├── FORK_MANAGEMENT.md        # Quick-start fork sync guide
    ├── emu-driver/               # Forked cua-driver (Swift source)
    │   ├── Sources/              # Swift implementation
    │   ├── Tests/                # Test suite
    │   ├── Skills/               # Claude Code skills
    │   ├── docs/                 # Documentation
    │   ├── scripts/              # Build/install/test
    │   ├── Package.swift         # Swift package manifest
    │   ├── README.md             # cua-driver overview
    │   ├── FORK_SYNC.md          # Detailed sync strategy ← PRIMARY
    │   └── UPSTREAM_CHANGES.md   # Divergence log ← TRACK HERE
    │
    └── (Note: emu-driver will be initialized as separate git repo)
```

---

## Git Setup

### Emu Main Repo

**Status:** ✅ Ready

```bash
# Commits
7218c1c Add emu-driver fork (cua-driver) to frontend/coworker-mode
08ded3c Add coworker-driver folder with specs and skill documentation
e4eded7 coworker mode spec created

# Current user
Prathmesh234 <ppbhatt500@gmail.com>

# Origin
https://github.com/Prathmesh234/Emu.git
```

### Emu-Driver (Separate Fork)

**Status:** 🔲 Awaiting first init + push

```bash
# Location
frontend/coworker-mode/emu-driver/

# Setup (when ready)
cd frontend/coworker-mode/emu-driver
git init
git remote add upstream https://github.com/trycua/cua.git
git remote add origin https://github.com/Prathmesh234/emu-driver.git  # create on GitHub first

# First push
git add -A
git commit -m "Initial: fork of cua-driver from trycua/cua@main"
git push origin main
```

---

## Sync Strategy (Recommended)

### For Regular Updates

**Approach:** Cherry-pick critical fixes + periodic full rebases

```bash
cd frontend/coworker-mode/emu-driver

# 1. Fetch upstream
git fetch upstream main --depth=1

# 2. Review what changed
git log --oneline HEAD..upstream/main | head -20

# 3. Cherry-pick specific fixes (bug fixes, stability)
git cherry-pick abc1234

# 4. OR full rebase (major updates, new features)
git checkout -b sync/upstream-<date>
git rebase upstream/main
# Resolve conflicts (keep Emu branding variants)
git checkout main
git merge sync/upstream-<date>
```

### For Emu-Specific Changes

**Approach:** Document in UPSTREAM_CHANGES.md before/after

```bash
# 1. Make change in Sources/
# 2. Commit with status tag
git commit -m "swift: fix calendar focus (EMU-SPECIFIC)"

# 3. Update UPSTREAM_CHANGES.md
# Add section with:
# - Files modified
# - Rationale
# - Status (LOCAL ONLY / CANDIDATE FOR UPSTREAM / MERGED)

# 4. Guard code with comment
// EMU-SPECIFIC: reason
// See UPSTREAM_CHANGES.md
```

### Merge Conflict Resolution

**Conflict pattern:** Branding strings

```swift
<<<<<<< HEAD (Emu)
"Emu requires Accessibility permission"
=======
"cua-driver requires Accessibility permission"  // upstream
>>>>>>> upstream/main
```

**Fix:** Keep HEAD (Emu version)

---

## Documentation Map

| Document | Purpose | Audience |
|---|---|---|
| **coworker-driver/SPEC.md** | Implementation blueprint | Implementation team |
| **coworker-driver/SKILL.md** | Operational manual | Model/agent developers |
| **coworker-driver/WEB_APPS.md** | Browser patterns | Debugging web issues |
| **coworker-driver/TESTS.md** | Test cases | QA/validation |
| **coworker-driver/RECORDING.md** | Trajectory capture | Demos/training data |
| **coworker-driver/SUMMARY.md** | Quick reference | Everyone |
| **coworker-mode/FORK_MANAGEMENT.md** | Fork sync workflow | Swift/maintainers |
| **emu-driver/FORK_SYNC.md** | Detailed sync guide | Maintainers |
| **emu-driver/UPSTREAM_CHANGES.md** | Divergence tracker | Maintainers |

---

## Next Steps

### Immediate (Dev Setup)

1. ✅ Documentation complete (SPEC, SKILL, WEB_APPS, TESTS, RECORDING)
2. ✅ Emu-driver fork copied and tracked
3. ✅ Sync strategy documented
4. 🔲 **Initialize emu-driver git repo locally**
   ```bash
   cd frontend/coworker-mode/emu-driver
   git init
   git remote add upstream https://github.com/trycua/cua.git
   ```
5. 🔲 **Create fork on GitHub** (Prathmesh234/emu-driver)
6. 🔲 **First push:**
   ```bash
   git remote add origin https://github.com/Prathmesh234/emu-driver.git
   git add -A
   git commit -m "Initial: fork of cua-driver from trycua/cua@main"
   git push origin main
   ```

### Implementation (From SPEC §14)

1. Install cua-driver locally, verify `cua-driver mcp` works
2. Implement `frontend/process/cuaDriverProcess.js`
3. Implement `frontend/cua-driver-commands/` (actionProxy.js + index.js)
4. Modify `frontend/actions/executor.js` (branch on agentMode)
5. Add `frontend/services/captureForStep.js`
6. Backend: coworker_system_prompt.py + build_system_prompt plumbing
7. Backend: raise_app JSON return + list_running_apps tool
8. Extend action models (pid/window_id/element_index fields)
9. Wire IPC in main.js (lifecycle)
10. End-to-end test + packaging

### Public Release (Phase 2, Deferred)

- Notarization for Emu.app
- Entitlements for bundled emu-driver
- Sign emu-driver binary independently

---

## Fork Rationale (Copy in Commit)

**Why fork instead of using cua-driver directly:**

1. **Permission Branding** — Surface permissions as "Emu needs..." not "cua-driver needs..."
2. **Swift App Fixes** — Direct ownership of platform stability (known issues on Calendar, Mail, etc.)
3. **Emu-Specific Optimizations** — Session-scoped element coherence, model-optimized targeting
4. **Velocity** — Ship fixes without upstream coordination (cherry-pick when useful)

**Sync approach:**
- Cherry-pick critical bug fixes from upstream
- Maintain divergence log in UPSTREAM_CHANGES.md
- Contribute back to upstream when fixes benefit everyone
- Full rebase periodically to stay in sync

---

## Key Files & Responsibilities

### Documentation (No Code Changes Needed)
- `coworker-driver/SPEC.md` — Implementation roadmap
- `coworker-driver/SKILL.md` — Operational reference
- `coworker-mode/FORK_MANAGEMENT.md` — Fork sync workflow

### To Implement (From SPEC)
- `frontend/process/cuaDriverProcess.js` (298 lines)
- `frontend/cua-driver-commands/actionProxy.js` (102 lines)
- `frontend/cua-driver-commands/index.js` (43 lines)
- `frontend/services/captureForStep.js` (21 lines)
- `backend/prompts/coworker_system_prompt.py` (46 lines)
- `backend/tools/list_running_apps.py` (9 lines)
- Modify: executor.js, build_system_prompt, context.py, raise_app.py, dispatcher.py, response.py

### To Maintain (Fork)
- `frontend/coworker-mode/emu-driver/FORK_SYNC.md` — Keep updated
- `frontend/coworker-mode/emu-driver/UPSTREAM_CHANGES.md` — Track divergences
- Cherry-pick upstream fixes periodically

---

## Verification Checklist

- ✅ `frontend/coworker-driver/` has all documentation files
- ✅ `frontend/coworker-mode/emu-driver/` contains full cua-driver source
- ✅ `FORK_SYNC.md` explains sync workflow
- ✅ `UPSTREAM_CHANGES.md` ready for tracking divergences
- ✅ `FORK_MANAGEMENT.md` provides quick-start guide
- ✅ Git commits in Emu repo document the change
- 🔲 emu-driver git repo not yet initialized (pending first use)
- 🔲 emu-driver fork not yet pushed to GitHub (create repo first)

---

## Resources

**cua-driver:**
- Repo: https://github.com/trycua/cua/tree/main/libs/cua-driver
- Docs: https://cua.ai/docs/cua-driver
- Install: https://raw.githubusercontent.com/trycua/cua/main/libs/cua-driver/scripts/install.sh
- Blog: https://github.com/trycua/cua/blob/main/blog/inside-macos-window-internals.md

**Emu fork:**
- Emu-driver location: `frontend/coworker-mode/emu-driver/`
- Sync guide: `frontend/coworker-mode/emu-driver/FORK_SYNC.md`
- Divergence tracker: `frontend/coworker-mode/emu-driver/UPSTREAM_CHANGES.md`

---

## Status

| Component | Status | Notes |
|---|---|---|
| Documentation | ✅ Complete | All 7 docs in coworker-driver/ |
| Fork copied | ✅ Complete | emu-driver/ contains full source |
| Git setup (Emu) | ✅ Complete | Commits pushed, ready to integrate |
| Git setup (emu-driver) | 🔲 Pending | Awaits `git init` + GitHub repo creation |
| Sync strategy | ✅ Documented | FORK_SYNC.md + FORK_MANAGEMENT.md |
| Implementation | 🔲 Ready | Can begin with roadmap step 1 |

**Next action:** Begin implementation per SPEC §14, OR initialize emu-driver git repo (whichever is your next priority).
