# PV Reference

Given a prefix like `XF:28ID1-CT{SVC-XSPD:1}`, the IOC exposes the following PVs:

## Status PVs (read-only)

| PV Suffix | Type | Description |
|-----------|------|-------------|
| `Unit` | stringin | Systemd unit name |
| `Desc` | stringin | Unit description |
| `LoadState` | mbbi | Load state (loaded, not-found, masked, error, bad-setting) |
| `UnitFile` | stringin | Path to the unit file |
| `Enabled` | mbbi | Enable state (enabled, disabled, static, masked, ...) |
| `ActiveState` | mbbi | Active state (active, reloading, inactive, failed, ...) |
| `SubState` | mbbi | Sub-state (running, dead, exited, failed, ...) |
| `Since` | stringin | Uptime / time since entering current state (e.g. "3d 2h 15m 10s") |
| `Duration` | ai | Duration the process ran before exiting (seconds) |
| `Result` | stringin | Exit result (e.g. "signal", "exit-code") — empty when active |
| `ExitInfo` | stringin | Exit details (e.g. "code=killed, signal=SEGV") — empty when active |
| `MainPID` | longin | Main process ID |
| `Tasks` | ai | Number of tasks |
| `Mem` | ai | Current memory usage (EGU auto-scales: KB, MB, GB) |
| `MemPeak` | ai | Peak memory usage (EGU auto-scales: KB, MB, GB) |
| `MemSwap` | ai | Swap memory usage (EGU auto-scales: KB, MB, GB) |
| `MemSwapPeak` | ai | Peak swap memory usage (EGU auto-scales: KB, MB, GB) |
| `CPU` | ai | CPU time consumed (EGU auto-scales: ms, s, min, h) |
| `CGroup` | lsi | Control group path |
| `Logs` | lsi | Recent journal log entries |
| `StatusMessage` | lsi | Status/error messages with timestamp |

## Command PVs (write)

| PV Suffix | Type | Description |
|-----------|------|-------------|
| `Start` | bo | Write `1` to start the service |
| `Stop` | bo | Write `1` to stop the service |
| `Restart` | bo | Write `1` to restart the service |

## Alarms

The `LoadState`, `ActiveState`, and `SubState` PVs enter a **MAJOR** alarm when
the service is in a failure state:

- `LoadState`: not-found, error, bad-setting
- `ActiveState`: failed
- `SubState`: failed

## Status Messages

The `StatusMessage` PV provides timestamped updates:

- On IOC startup: reports the initial state (e.g. `[10:52:55] active(running) load=loaded enabled=enabled`)
- On state change: reports which states changed (e.g. `[10:53:12] inactive(dead)`)
- On command failure: reports the error (e.g. `[10:53:15] Start failed: Access denied`)
- If already running/stopped: reports accordingly (e.g. `[10:53:20] Service is already running`)

## Auto-scaling Units

The memory and CPU PVs automatically adjust their engineering units (EGU) field
based on the magnitude of the value:

**Memory** (`Mem`, `MemPeak`, `MemSwap`, `MemSwapPeak`):
- < 1 MB → displayed in **KB**
- 1 MB to 1 GB → displayed in **MB**
- ≥ 1 GB → displayed in **GB**

**CPU time** (`CPU`):
- < 1 s → displayed in **ms**
- 1 s to 60 s → displayed in **s**
- 60 s to 1 h → displayed in **min**
- ≥ 1 h → displayed in **h**
