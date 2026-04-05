---
name: file-manager
description: "Manage files and folders via shell commands. Use when: user asks to create, move, copy, rename, delete, find, or organize files and directories. Also for reading file contents, checking disk usage, or comparing files. NOT for: editing code (use the editor directly)."
---

## File Manager

Handle file operations efficiently using shell commands instead of GUI navigation.

### Core commands

| Task | Command |
|------|---------|
| List files | `Get-ChildItem` or `ls` (PowerShell alias) |
| Find files | `Get-ChildItem -Recurse -Filter "pattern"` or `Get-ChildItem -Path . -Recurse -Include "*.py"` |
| Create dir | `New-Item -ItemType Directory -Path "path\to\dir" -Force` |
| Copy | `Copy-Item -Recurse source dest` (use -Recurse for directories) |
| Move/rename | `Move-Item source dest` |
| Delete | `Remove-Item file` or `Remove-Item -Recurse dir` (ALWAYS confirm with user first) |
| Read file | `Get-Content file` or `Get-Content file -TotalCount 50` for previews |
| File size | `(Get-Item path).Length` or `Get-ChildItem path | Measure-Object -Property Length -Sum` |
| Disk usage | `Get-PSDrive -PSProvider FileSystem` |
| Compare | `Compare-Object (Get-Content file1) (Get-Content file2)` |
| Search content | `Select-String -Recurse -Pattern "pattern" -Path "path\*"` |
| Count lines | `(Get-Content file | Measure-Object -Line).Lines` |

### Safety rules

- **NEVER** run `Remove-Item -Recurse` without explicit user confirmation
- Always use `Get-ChildItem` to verify paths before destructive operations
- For moves/copies of important files, verify the destination exists
- When deleting, prefer moving to Recycle Bin over permanent deletion if available
- Show the user what will be affected before batch operations

### Tips

- Use `shell_exec` for all file operations — it's faster and more
  reliable than navigating File Explorer with mouse clicks.
- Chain commands with `;` or use pipelines for multi-step operations.
- Use `tree /F` for a quick directory overview.
- Prefer absolute paths to avoid working-directory confusion.
