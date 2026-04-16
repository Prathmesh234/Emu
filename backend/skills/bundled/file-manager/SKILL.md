---
name: file-manager
description: "Manage files and folders via shell commands. Use when: user asks to create, move, copy, rename, delete, find, or organize files and directories. Also for reading file contents, checking disk usage, or comparing files. NOT for: editing code (use the editor directly)."
---

## File Manager

Handle file operations efficiently using shell commands instead of GUI navigation.

### Core commands

| Task | Command |
|------|---------|
| List files | `ls -la` or `ls -lah` for human-readable sizes |
| Find files | `find /path -name "pattern"` or `find . -type f -name "*.py"` |
| Create dir | `mkdir -p /path/to/dir` |
| Copy | `cp -r source dest` (use -r for directories) |
| Move/rename | `mv source dest` |
| Delete | `rm file` or `rm -rf dir` (ALWAYS confirm with user first) |
| Read file | `cat file` or `head -50 file` for previews |
| File size | `du -sh /path` |
| Disk usage | `df -h` |
| Compare | `diff file1 file2` |
| Search content | `grep -rn "pattern" /path` |
| Count lines | `wc -l file` |

### Safety rules

- **NEVER** run `rm -rf` without explicit user confirmation
- Always use `ls` to verify paths before destructive operations
- For moves/copies of important files, verify the destination exists
- When deleting, prefer `trash` command over `rm` if available
- Show the user what will be affected before batch operations

### Tips

- Use `shell_exec` for all file operations — it's faster and more
  reliable than navigating Finder/Files with mouse clicks.
- Chain commands with `&&` for multi-step operations.
- Use `tree -L 2` for a quick directory overview.
- Prefer absolute paths to avoid working-directory confusion.
