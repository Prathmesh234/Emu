---
name: system-info
description: "Check system information, running processes, resource usage, and system health. Use when: user asks about CPU usage, memory, disk space, running processes, system specs, network status, or battery. Also for troubleshooting slow performance."
---

## System Info

Gather system information and diagnose performance issues via shell commands.

### Quick checks

| Info | Windows (PowerShell) | Linux |
|------|---------------------|-------|
| CPU usage | `Get-Counter '\Processor(_Total)\% Processor Time' -SampleInterval 1 -MaxSamples 1` | `top -bn1 | head -10` |
| Memory | `Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 10 Name,@{N='Mem(MB)';E={[math]::Round($_.WorkingSet64/1MB,1)}}` | `free -h` |
| Disk space | `Get-PSDrive -PSProvider FileSystem` | `df -h` |
| Running processes | `Get-Process | Sort-Object CPU -Descending | Select-Object -First 20` | `ps aux | head -20` |
| Network | `Get-NetIPAddress | Where-Object AddressFamily -eq 'IPv4'` | `ip addr` or `ifconfig` |
| System info | `Get-ComputerInfo | Select-Object WindowsVersion,OsName,CsProcessors,CsTotalPhysicalMemory` | `uname -a` |
| Battery | `Get-WmiObject Win32_Battery | Select-Object EstimatedChargeRemaining,BatteryStatus` | `cat /sys/class/power_supply/BAT0/capacity` |
| Uptime | `(Get-Date) - (Get-CimInstance Win32_OperatingSystem).LastBootUpTime` | `uptime` |
| Open ports | `Get-NetTCPConnection -State Listen` | `ss -tlnp` |

### Troubleshooting slow performance

1. Check CPU: `Get-Counter '\Processor(_Total)\% Processor Time'` — look for sustained high usage
2. Check memory: `Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 10` — is physical memory nearly full?
3. Check disk: `Get-PSDrive -PSProvider FileSystem` — is any partition >90% full?
4. List heavy processes: `Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 10 Name,@{N='Mem(MB)';E={[math]::Round($_.WorkingSet64/1MB,1)}}`
5. Report findings to user with specific recommendations

### Tips

- Use `shell_exec` for all system checks — faster than navigating
  Task Manager or Settings.
- Always report human-readable numbers (GB not bytes).
- If the user asks "why is my computer slow?", run CPU + memory +
  disk checks before answering.
