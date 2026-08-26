# Managing init.d (SysV) Services

On older hosts without systemd, services are managed by **init.d** (SysV init)
scripts under `/etc/init.d/` and the `service` command. Pass `--initd` to manage
such a service instead of a systemd unit:

```bash
# Monitor a local init.d service
remote-svc-ctrl "XF:28ID1-CT{SVC-MyApp:1}" my-app --initd

# Monitor an init.d service on a remote host via SSH
remote-svc-ctrl "XF:28ID1-CT{SVC-MyApp:1}" my-app --host user@server --initd
```

Note that the service name has no `.service` suffix — it is the init.d script
name (e.g. `my-app` for `/etc/init.d/my-app`).

## What Gets Monitored

init.d exposes far less structured information than systemd, so the IOC derives
each PV from a combination of `service <name> status`, the process PID, and the
init.d script:

| PV | Source |
|----|--------|
| `ActiveState` / `SubState` | keywords in `service <name> status`, falling back to the LSB exit code (0 = running, 3 = stopped) |
| `Enabled` | `chkconfig <name>` (on/off for the current runlevel) |
| `UnitFile` | the script path, `/etc/init.d/<name>` |
| `Desc` | the LSB `Description` / `Short-Description` header parsed from the init.d script |
| `MainPID` | a `pid` value reported in the status output |
| `Mem` / `MemPeak` / `MemSwap` | `/proc/<pid>/status` (`VmRSS`, `VmHWM`, `VmSwap`) |
| `CPU` / `Tasks` | `ps -o cputime=,nlwp=` for the PID |
| `Since` / `Duration` | the process start time from `ps -o lstart=` |
| `Logs` | see [Logs](#logs) below |

Fields that systemd provides but init.d cannot (`Result`, `ExitInfo`, memory
swap-peak) are left empty.

Memory, CPU, uptime and log stats are only available when the service reports a
PID in its status output. init.d scripts that print only "running" without a PID
will leave those PVs at zero.

## Logs

init.d has no journal. The IOC populates the `Logs` PV in one of two ways:

1. **A log file you specify** with `--log-file`, tailed to `--log-lines` lines
   (default 20):

   ```bash
   remote-svc-ctrl "XF:...{SVC-MyApp:1}" my-app --initd \
       --log-file /var/log/my-app.log --log-lines 100
   ```

2. **The process's own stdout/stderr**, followed via `/proc/<pid>/fd/1` and
   `/proc/<pid>/fd/2` when they point at regular files. This is best-effort:
   pipes, sockets and `/dev/null` are skipped, and reading another user's fds
   or a root-owned log file may require appropriate permissions.

If a `--log-file` is given it always takes precedence.

## Non-root Control with sudoers

systemd has [polkit](polkit.md) to authorize non-root service control, but
init.d has no equivalent. If the IOC runs as a non-root user (locally, or as the
remote SSH user), starting/stopping/restarting a service requires a **sudoers**
rule, and you must pass `--sudo` to allow it:

```bash
remote-svc-ctrl "XF:...{SVC-MyApp:1}" my-app --initd --sudo
```

sudo is used **only when absolutely necessary**: the IOC inspects the effective
service user — the ssh username in `user@host`, or the local user when the host
has no `user@` part or the service is local. If that user is **root**, sudo is
never used. If the user is non-root, `sudo -n` is applied to `start`, `stop` and
`restart` only. Read-only monitoring (`status`, `ps`, `chkconfig`, reading the
script) is never elevated.

Grant the IOC user (here `softioc-tst`) password-less permission to run the
`service` command for the specific service by creating
`/etc/sudoers.d/remote-svc-ctrl-my-app`:

```sudoers
softioc-tst ALL=(root) NOPASSWD: /usr/sbin/service my-app start, /usr/sbin/service my-app stop, /usr/sbin/service my-app restart
```

Install it with the correct ownership and mode, and validate the syntax before
saving:

```bash
sudo visudo -cf /etc/sudoers.d/remote-svc-ctrl-my-app   # check syntax
sudo chown root:root /etc/sudoers.d/remote-svc-ctrl-my-app
sudo chmod 440 /etc/sudoers.d/remote-svc-ctrl-my-app
```

> The `-n` (non-interactive) flag makes `sudo` fail immediately instead of
> prompting for a password, so the sudoers rule **must** be `NOPASSWD`. Verify
> the exact `service` path with `command -v service` on the target host, and
> point the sudoers rule at it.

### Verifying

As the IOC user on the target host:

```bash
sudo -n service my-app restart
service my-app status
```

If the restart runs without a password prompt, the sudoers rule is active.

## Requirements

- `service` and `chkconfig` available on the target host
- For non-root control: a `NOPASSWD` sudoers rule and the `--sudo` flag
- SSH key-based auth configured for remote hosts (see [ssh-setup.md](ssh-setup.md))
