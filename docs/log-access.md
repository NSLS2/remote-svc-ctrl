# Enabling Log Access for Services

By default, systemd services log their stdout/stderr to the **journal** (systemd's
built-in logging system). The IOC reads these journal entries from the output of
`systemctl status` and displays them via the `Logs` PV.

For this to work, the user that interacts with the service must have permission
to read the journal. For local services, this is the user running the IOC. For
remote services, this is the remote user that the IOC connects to over SSH.
This page covers how to grant access, as well as alternative logging approaches
that avoid the journal entirely.

## Option 1: Grant Journal Read Access (Recommended)

The simplest approach is to add the user to the `systemd-journal` group
on the host running the service:

```bash
sudo usermod -aG systemd-journal xspadmin
```

The user must start a new login session for the group change to take effect (no
reboot required).

After this, `systemctl status <service>` will include journal log lines in its
output, and the IOC's `Logs` PV will be populated automatically.

> **Note:** This grants read access to *all* journal entries, not just those
> for one service. If isolation is required, see Options 2 or 3 below.

## Option 2: Log to a Dedicated File

Instead of using the journal, you can direct the service's output to a file
in `/var/log/`. This avoids journal permission issues entirely.

In the unit file, use `StandardOutput=append:` and `StandardError=append:`:

```ini
[Service]
Type=simple
StandardOutput=append:/var/log/xspd.log
StandardError=append:/var/log/xspd.log
ExecStart=/usr/sbin/xspd
```

Then create the file with appropriate ownership so the user can read it:

```bash
sudo touch /var/log/xspd.log
sudo chown root:xspadmin /var/log/xspd.log
sudo chmod 640 /var/log/xspd.log
sudo systemctl daemon-reload
sudo systemctl restart xspd
```

> **Tip:** Once the service logs to a file, you can have the IOC tail that file
> directly instead of parsing the journal out of `systemctl status`. Pass
> `--log-file` (and optionally `--log-lines N`, default 20). This works for
> systemd services just as it does for init.d, and sidesteps journal
> permissions entirely:
>
> ```bash
> remote-svc-ctrl "XF:28ID1-CT{SVC-Xspd:1}" xspd.service --host xspadmin@xspserver \
>     --log-file /var/log/xspd.log --log-lines 100
> ```
>
> When `--log-file` is set it takes precedence over the journal lines from
> `systemctl status`.

### Log Rotation

For long-running services, configure logrotate to prevent the file from growing
unbounded. Create `/etc/logrotate.d/xspd`:

```
/var/log/xspd.log {
    weekly
    rotate 4
    compress
    missingok
    notifempty
    copytruncate
}
```

## Option 3: Log to Syslog (`/var/log/messages`)

You can route the service's output to the system syslog, which typically writes
to `/var/log/messages` or `/var/log/syslog` depending on the distribution.

In the unit file, set:

```ini
[Service]
StandardOutput=journal+console
SyslogIdentifier=xspd
```

Then add a rsyslog rule to write messages from this identifier to syslog.
Create `/etc/rsyslog.d/xspd.conf`:

```
:programname, isequal, "xspd" /var/log/messages
```

Restart rsyslog:

```bash
sudo systemctl restart rsyslog
```

The logs will now appear in `/var/log/messages` (readable by users in the `adm`
group on most systems).

## Verifying Log Access

After configuring one of the options above, verify that the remote user can see
the logs:

```bash
# For Option 1 (journal):
ssh xspadmin@xspserver systemctl status xspd

# For Option 2 (file):
ssh xspadmin@xspserver cat /var/log/xspd.log

# For Option 3 (syslog):
ssh xspadmin@xspserver grep xspd /var/log/messages
```

If `systemctl status` shows log lines in the output, the IOC will display
them in the `Logs` PV without any additional configuration.
