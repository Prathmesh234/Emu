# Emu-Driver Upstream Divergence Log

Track local customizations and their relationship to upstream (trycua/cua).

---

## Format

```markdown
### N. <Change Title>
**File(s):** Path(s) to modified files
**Status:** LOCAL ONLY | CANDIDATE FOR UPSTREAM | MERGED UPSTREAM
**Priority:** Critical | High | Medium | Low
**Rationale:** Why this change is needed in Emu's context

**Code/Commit:**
- Commit hash (when committed)
- Brief description of change

**Upstream Equivalent:**
- Issue/PR link (if applicable)
- Status of upstream discussion
```

---

## Log

### 1. Permission Branding
**File(s):** Sources/CuaDriverCore/Permission.swift, Sources/CuaDriverServer/Tools/*.swift
**Status:** LOCAL ONLY
**Priority:** High
**Rationale:** Error messages and permission prompts should say "Emu" not "cua-driver" for user trust & brand consistency

**Code/Commit:**
- TBD (when first Emu customization is committed)

**Upstream Equivalent:**
- None — this is Emu-specific UX

---

### 2. Swift App Focus Fixes
**File(s):** Sources/CuaDriverCore/Input/FocusWithoutRaise.swift (planned)
**Status:** CANDIDATE FOR UPSTREAM
**Priority:** High
**Rationale:** Some Swift apps (Apple Calendar, Mail) have delayed window state updates on click. Emu needs reliable backgrounded interaction.

**Code/Commit:**
- TBD (when implemented)
- Expected changes: retry logic, timing adjustments

**Upstream Equivalent:**
- Potential upstream issue (monitor trycua/cua for similar reports)

---

### 3. Element Index Cache Persistence
**File(s):** Sources/CuaDriverServer/ElementCache.swift (planned)
**Status:** EMU-SPECIFIC
**Priority:** Medium
**Rationale:** Emu's session-scoped MCP client maintains element coherence across multiple action calls. Different from cua-driver's per-daemon approach.

**Code/Commit:**
- TBD (when session architecture is implemented)

**Upstream Equivalent:**
- Not applicable (Emu's session model is distinct)

---

### 4. Binary Entitlements (Signing)
**File(s):** .entitlements (when building for notarization)
**Status:** LOCAL ONLY
**Priority:** Medium (deferred to public release — Phase 2)
**Rationale:** Emu's notarized binary may need different entitlements than generic cua-driver

**Code/Commit:**
- TBD (Phase 2: first public DMG release)

**Upstream Equivalent:**
- cua-driver uses ad-hoc signing today; not an upstream concern yet

---

## Merge Conflict Patterns

### Pattern 1: Permission Strings
**When syncing upstream, keep Emu's variant:**

```
<<<<<<< HEAD (Emu)
"Emu requires Accessibility permission"
=======
"cua-driver requires Accessibility permission"  // upstream
>>>>>>> upstream/main
```

**Resolution:** Keep HEAD (Emu variant)

---

### Pattern 2: Error Messages
**Any user-facing text mentioning the app name:**

```
<<<<<<< HEAD (Emu)
"Emu detected Chromium AX tree is sparse"
=======
"cua-driver detected Chromium AX tree is sparse"  // upstream
>>>>>>> upstream/main
```

**Resolution:** Keep HEAD (Emu variant)

---

## Next Steps (For Implementers)

1. **Before merging from upstream**, review this log
2. **After local customizations**, add a section above
3. **Before pushing to public repo**, ensure divergences are documented
4. **On upstream bump**, re-check this log for conflicts

---

## Resources

- **FORK_SYNC.md** — How to sync and cherry-pick
- **Upstream:** https://github.com/trycua/cua/tree/main/libs/cua-driver
- **This fork:** frontend/coworker-mode/emu-driver/
