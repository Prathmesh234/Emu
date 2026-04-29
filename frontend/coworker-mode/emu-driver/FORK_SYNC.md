# EMU-DRIVER — Fork Sync Strategy

This is an Emu-specific fork of `cua-driver` from https://github.com/trycua/cua (specifically the `libs/cua-driver` folder).

## Why Fork?

1. **Permission Branding** — Surface permissions as "Emu needs..." (not "cua-driver needs...")
2. **Swift App Fixes** — Direct ownership of platform stability issues
3. **Emu-Specific Optimizations** — Computer-use-specific features (session coherence, window targeting)
4. **Velocity** — Ship fixes without upstream coordination

## Folder Structure

```
frontend/coworker-mode/emu-driver/
├── Sources/          # Swift source code
├── Tests/            # Test suite
├── Skills/           # Claude Code skill definitions
├── docs/             # Documentation
├── Package.swift     # Swift package manifest
├── FORK_SYNC.md      # This file
└── UPSTREAM_CHANGES.md  # Log of divergences
```

---

## Sync Strategy

### Local Development (Current)

This fork is **not yet pushed** to GitHub. Current state:

- ✅ Copied from trycua/cua@main (libs/cua-driver)
- ✅ Local git repo initialized with upstream tracking
- 🔲 Awaiting first push to Prathmesh234/emu-driver (or similar)

### Regular Upstream Sync

#### Check for Updates

```bash
cd frontend/coworker-mode/emu-driver

# Fetch upstream changes (main only, shallow)
git fetch upstream main --depth=1

# Compare against our HEAD
git log --oneline HEAD..upstream/main | head -10
```

#### Cherry-Pick Critical Fixes

For **bug fixes and stability** (high-priority):

```bash
# Find the commit hash from trycua/cua
git log upstream/main --oneline --grep="Swift app" | head -5

# Cherry-pick it
git cherry-pick <commit-hash>
```

#### Full Rebase (Major Update)

For **feature updates or major refactors** (lower-priority):

```bash
# Create a new branch
git checkout -b sync/upstream-<date>

# Rebase on latest upstream
git rebase upstream/main

# Resolve conflicts manually (likely in permission strings, branding)
# Then merge back to your working branch
git checkout main
git merge sync/upstream-<date>
```

### Tracking Divergences

**Before merging upstream changes, log local customizations** in `UPSTREAM_CHANGES.md`:

```markdown
## Divergence Log

### 1. Permission Branding (Permission*.swift)
**Status:** LOCAL ONLY (don't upstream)
- Changed error strings from "cua-driver" → "Emu"
- Commit: emu@abc1234

### 2. Swift App Focus Fix (FocusWithoutRaise.swift)
**Status:** CANDIDATE FOR UPSTREAM
- Fixed delayed window activation on certain Swift apps
- Commit: emu@def5678
- Upstream issue: trycua/cua#1234

### 3. Element Cache Coherence (ElementState.swift)
**Status:** EMU-SPECIFIC (don't upstream)
- Session-scoped element index persistence
- Commit: emu@ghi9012
```

---

## Workflow: Fix a Bug

### Bug in Both Emu and cua-driver

Example: "Swift app focus steal on click"

1. **Fix locally** in `Sources/*/Focus.swift`
2. **Test** in Emu coworker mode
3. **Upstream submission**:
   ```bash
   # Ensure it's cleanly isolated
   git log --oneline -n 1
   
   # Fork trycua/cua on GitHub
   # Push to your fork
   git push https://github.com/<your-username>/cua main
   
   # Open PR against trycua/cua
   ```
4. **Merge locally** after trycua accepts it:
   ```bash
   git fetch upstream main
   git merge upstream/main
   ```

### Bug Only in Emu's Context

Example: "Emu's model outputs element indices differently"

1. **Fix locally**, no upstream submission
2. **Document in UPSTREAM_CHANGES.md** under EMU-SPECIFIC
3. **Guard against rebase clobbering** with clear comments:
   ```swift
   // EMU-SPECIFIC: Emu-model element index format (do not upstream)
   // See UPSTREAM_CHANGES.md for rationale
   let emuFormat = translateElementIndexFormat(coreIndex)
   ```

---

## GitHub Setup (When Ready)

Once you're ready to push this fork:

```bash
# Create repo: Prathmesh234/emu-driver (or under organization)

# Push initial commit
cd frontend/coworker-mode/emu-driver
git add -A
git commit -m "Initial fork of cua-driver from trycua/cua@main

- Fork rationale: permission branding, Swift app fixes, Emu optimizations
- Tracking upstream at: https://github.com/trycua/cua
- Sync strategy documented in FORK_SYNC.md

Co-authored-by: trycua/cua contributors"

git remote set-url origin https://github.com/Prathmesh234/emu-driver.git
git push origin main
```

### Upstream Remote

Keep the remote for easy sync:

```bash
git remote -v
# origin    https://github.com/Prathmesh234/emu-driver.git (push/fetch)
# upstream  https://github.com/trycua/cua.git (fetch only)
```

---

## Version Tracking

### Binary Versioning

cua-driver's `Package.swift` has a version. Track Emu's customizations separately:

**Sources/CuaDriverCore/Version.swift:**

```swift
public let coreVersion = "1.0.0"  // from upstream
public let emuVersion = "1.0.0-emu.1"  // Emu custom build
```

**Bump strategy:**

- `1.0.0-emu.1` — First Emu customization on top of upstream 1.0.0
- `1.0.0-emu.2` — Additional Emu fixes on upstream 1.0.0
- `1.1.0` — Upstream major bump; merge, test, bump to 1.1.0-emu.1

---

## Testing After Sync

After pulling upstream changes or cherry-picking commits:

```bash
# Run cua-driver's test suite
swift test

# If Emu builds against this:
cd /Applications/Emu
npm run build  # or electron build
```

---

## Merge Conflict Resolution

**Most likely conflict:** Permission strings, branding text, entitlements.

```swift
<<<<<<< HEAD (emu local)
return "Emu requires Accessibility permission"
=======
return "cua-driver requires Accessibility permission"  // upstream
>>>>>>> upstream/main
```

**Resolution:** Keep Emu variant (HEAD).

---

## Checklist: New Emu Customization

- [ ] Write the code (e.g., new focus behavior)
- [ ] Add test (if applicable)
- [ ] Document in UPSTREAM_CHANGES.md (EMU-SPECIFIC or CANDIDATE?)
- [ ] If CANDIDATE, open issue at trycua/cua for feedback
- [ ] Commit with clear message: "swift: fix focus on mini windows (EMU-SPECIFIC)"
- [ ] Tag if this is a release: `git tag emu-v1.0.0-rc1`

---

## Resources

- **Upstream:** https://github.com/trycua/cua
- **Upstream tracking:** `git remote show upstream`
- **Emu main:** `/Applications/Emu` (frontend/coworker-mode/emu-driver)
- **cua-driver docs:** https://cua.ai/docs/cua-driver
