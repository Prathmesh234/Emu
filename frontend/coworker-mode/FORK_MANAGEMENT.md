# Emu-Driver Fork Management

## Quick Reference

**Fork Location:** `frontend/coworker-mode/emu-driver/`

**Source (Upstream):** https://github.com/trycua/cua/tree/main/libs/cua-driver

**Documentation:**
- `emu-driver/FORK_SYNC.md` — Sync workflow & cherry-pick strategy
- `emu-driver/UPSTREAM_CHANGES.md` — Divergence log

---

## Setup (First Time)

### 1. Initialize Git Tracking in emu-driver

```bash
cd frontend/coworker-mode/emu-driver

# Initialize as separate repo
git init

# Add upstream as tracking remote (read-only)
git remote add upstream https://github.com/trycua/cua.git
git remote add origin https://github.com/trycua/cua.git  # temporary

# Fetch upstream main (will pull latest cua-driver)
git fetch upstream main --depth=1

# Set up branch tracking
git branch -u upstream/main
```

### 2. Push to Your Fork (When Ready)

```bash
# Create empty repo at https://github.com/Prathmesh234/emu-driver

cd frontend/coworker-mode/emu-driver

# Set to your fork
git remote set-url origin https://github.com/Prathmesh234/emu-driver.git

# Push
git add -A
git commit -m "Initial: fork of cua-driver from trycua/cua@main"
git push origin main
```

---

## Common Tasks

### Check for Upstream Updates

```bash
cd frontend/coworker-mode/emu-driver

# Fetch latest from upstream
git fetch upstream main --depth=1

# See what changed
git log --oneline HEAD..upstream/main | head -20
```

### Cherry-Pick a Bug Fix from Upstream

```bash
cd frontend/coworker-mode/emu-driver

# Find the commit
git log upstream/main --oneline --all | grep "Swift\|focus\|crash" | head -5

# Cherry-pick it
git cherry-pick abc1234def567

# If conflicts (branding strings), keep Emu variant:
# Edit the file, keep Emu text, then:
git add .
git cherry-pick --continue
```

### Full Rebase (Major Upstream Update)

```bash
cd frontend/coworker-mode/emu-driver

# Create branch
git checkout -b sync/upstream-2026-04

# Rebase on upstream
git rebase upstream/main

# Resolve conflicts (likely branding strings — keep Emu variants)
# Then go back to main and merge
git checkout main
git merge sync/upstream-2026-04

# Push to your fork
git push origin main
```

### Track a New Divergence

After making Emu-specific changes:

```bash
cd frontend/coworker-mode/emu-driver

# Commit your change
git add -A
git commit -m "swift: fix calendar focus issue (EMU-SPECIFIC)"

# Document in UPSTREAM_CHANGES.md
# Add a new section explaining the change, rationale, and status
```

---

## Merge Conflict Pattern

**When syncing from upstream, branding strings will conflict:**

```swift
<<<<<<< HEAD (Emu)
"Emu requires Accessibility permission"
=======
"cua-driver requires Accessibility permission"  // upstream
>>>>>>> upstream/main
```

**Resolution:** Keep HEAD (Emu's version). Edit and `git add .`, then continue.

---

## Folder Contents

```
emu-driver/
├── Sources/                 # Swift source (MCP server, tools, input)
├── Tests/                   # Test suite
├── Skills/                  # Claude Code skill definitions
├── App/                     # macOS app bundle structure
├── docs/                    # Documentation
├── scripts/                 # Build, install, test scripts
│   ├── install.sh          # Official installer
│   ├── install-local.sh    # Dev build + symlink
│   ├── build-app.sh        # Build CuaDriver.app
│   └── test.sh             # Run tests
├── Package.swift           # Swift package manifest
├── Package.resolved        # Dependency lock file
├── README.md               # cua-driver overview
├── FORK_SYNC.md            # ← Sync strategy (detailed)
├── UPSTREAM_CHANGES.md     # ← Divergence log
└── .gitignore              # Ignore build artifacts
```

---

## Build & Test (After Syncing)

### Local Dev Build

```bash
cd frontend/coworker-mode/emu-driver
./scripts/install-local.sh

# Verify
cua-driver list-tools
cua-driver check_permissions
```

### Integration with Emu

```bash
cd /Applications/Emu

# Rebuild frontend to include new emu-driver binary
npm run build

# Run Emu with bundled emu-driver
npm start
```

---

## Checklist: Sync from Upstream

- [ ] `git fetch upstream main --depth=1`
- [ ] `git log --oneline HEAD..upstream/main | head -10` (review changes)
- [ ] Decide: cherry-pick specific fixes OR full rebase?
- [ ] Cherry-pick: `git cherry-pick <hash>` for each fix
- [ ] Full rebase: `git rebase upstream/main`, resolve conflicts (keep Emu variants)
- [ ] `./scripts/test.sh` to verify build
- [ ] `npm run build` from Emu root to verify integration
- [ ] Update `UPSTREAM_CHANGES.md` with merge notes
- [ ] `git push origin main` to your fork

---

## Checklist: Make an Emu-Specific Change

- [ ] Write code in `Sources/`
- [ ] Add test (if applicable) in `Tests/`
- [ ] `./scripts/test.sh` passes
- [ ] Edit `UPSTREAM_CHANGES.md` (add new section or update existing)
- [ ] Mark status: LOCAL ONLY, CANDIDATE FOR UPSTREAM, or MERGED UPSTREAM
- [ ] Commit with clear message: `git commit -m "swift: <change> (EMU-SPECIFIC or UPSTREAM)"`
- [ ] If CANDIDATE, consider opening issue at https://github.com/trycua/cua

---

## Resources

- **cua-driver docs:** https://cua.ai/docs/cua-driver
- **cua-driver repo:** https://github.com/trycua/cua/tree/main/libs/cua-driver
- **Inside macOS internals:** https://github.com/trycua/cua/blob/main/blog/inside-macos-window-internals.md
- **This fork:** `frontend/coworker-mode/emu-driver/`
