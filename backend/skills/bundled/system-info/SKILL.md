---
name: system-info
description: "Check system information, running processes, resource usage, and system health. Use when: user asks about CPU usage, memory, disk space, running processes, system specs, network status, or battery. Also for troubleshooting slow performance."
---

## System Info

Gather system information and diagnose performance issues via shell commands.

### Quick checks

| Info | macOS | Linux |
|------|-------|-------|
| CPU usage | `top -l 1 | head -10` | `top -bn1 | head -10` |
| Memory | `vm_stat` or `top -l 1 | grep PhysMem` | `free -h` |
| Disk space | `df -h` | `df -h` |
| Running processes | `ps aux | head -20` | `ps aux | head -20` |
| Network | `ifconfig | grep inet` | `ip addr` or `ifconfig` |
| System info | `system_profiler SPSoftwareDataType` | `uname -a` |
| Battery | `pmset -g batt` | `cat /sys/class/power_supply/BAT0/capacity` |
| Uptime | `uptime` | `uptime` |
| Open ports | `lsof -i -P | grep LISTEN` | `ss -tlnp` |

### Troubleshooting slow performance

1. Check CPU: `top -l 1 | head -15` — look for processes using >50% CPU
2. Check memory: is physical memory nearly full? High swap usage?
3. Check disk: `df -h` — is any partition >90% full?
4. List heavy processes: `ps aux --sort=-%mem | head -10`
5. Report findings to user with specific recommendations

### Tips

- Use `shell_exec` for all system checks — faster than navigating
  Activity Monitor or System Settings.
- Always report human-readable numbers (GB not bytes).
- If the user asks "why is my computer slow?", run CPU + memory +
  disk checks before answering.
