# remote-svc-ctrl

An EPICS soft IOC that monitors and controls systemd services, exposing their status as Process Variables (PVs). Supports both local and remote (via SSH) service management.

## Features

- Poll `systemctl status` and publish service state as EPICS PVs
- Start, stop, and restart services via Channel Access
- Monitor over SSH for services running on remote hosts
- Phoebus operator screen included

## PVs

Given a prefix like `XF:28ID-CT{Svc:MyApp}`, the IOC exposes:

| PV Suffix | Type | Description |
|-----------|------|-------------|
| `Unit` | stringIn | Systemd unit name |
| `Desc` | stringIn | Unit description |
| `LoadState` | stringIn | Load state (loaded, not-found, etc.) |
| `UnitFile` | stringIn | Path to the unit file |
| `Enabled` | stringIn | Whether the unit is enabled |
| `ActiveState` | stringIn | Active state (active, inactive, failed) |
| `SubState` | stringIn | Sub-state (running, dead, exited, etc.) |
| `Since` | stringIn | Timestamp when the service entered its current state |
| `MainPID` | longIn | Main process ID |
| `Tasks` | longIn | Number of tasks |
| `Memory` | stringIn | Memory usage |
| `CPU` | stringIn | CPU usage |
| `CGroup` | stringIn | Control group |
| `Start` | boolOut | Write `1` to start the service |
| `Stop` | boolOut | Write `1` to stop the service |
| `Restart` | boolOut | Write `1` to restart the service |

## Usage

```bash
# Monitor a local service
remote-svc-ctrl "XF:28ID-CT{Svc:MyApp}" my-app.service

# Monitor a service on a remote host via SSH
remote-svc-ctrl "XF:28ID-CT{Svc:MyApp}" my-app.service --host user@server
```

## Operator Screen

A Phoebus `.bob` screen is provided in [`op/service_ctrl.bob`](op/service_ctrl.bob). Open it with the macro `PREFIX` set to your IOC's PV prefix.

## Development

```bash
uv sync
pytest
```

## Requirements

- Python >= 3.11
- [pythonSoftIOC](https://github.com/dls-controls/pythonSoftIOC) >= 4.7.0
- `systemctl` available on the target host
- SSH key-based auth configured for remote hosts
