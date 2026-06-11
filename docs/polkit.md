# Configuring Polkit for Service Control

By default, non-root users cannot start, stop, or restart systemd services.
To allow the IOC process (running as a non-root user such as `softioc-tst`) to manage a specific
service without a password, you need to create a polkit rule.

## Example: Allowing `xspd.service` Control

The `xspd` service is used for remote control of X-Spectrum detectors, so we'll use it as an example. The service runs on an X-Spectrum provided server,
with a factory created operator account named `xspadmin`. We want to allow the IOC running as `softioc-tst` on the controls server to manage the `xspd.service` on the X-Spectrum server via SSH.

First, we need to allow the `xspadmin` user on the X-Spectrum server to manage the `xspd.service` without a password. To do this, create the file `/etc/polkit-1/rules.d/50-allow-xspd.rules` on the X-Spectrum server with the following contents:

```javascript
polkit.addRule(function(action, subject) {
    if (action.id == "org.freedesktop.systemd1.manage-units" &&
        action.lookup("unit") == "xspd.service" &&
        subject.user == "xspadmin") {
        return polkit.Result.YES;
    }
});
```

This allows the `xspadmin` user to manage the `xspd.service` unit without
authentication.

Then, you can enable ssh access to the server for the `softioc-tst` user on the controls server by setting up SSH keys as described in [ssh-setup.md](docs/ssh-setup.md). The IOC can then control the remote service via SSH without any password prompts.

## Allowing Multiple Services with a Pattern

To allow control of all services matching a pattern (e.g. all soft IOC services
named `softioc-*.service`), create `/etc/polkit-1/rules.d/50-allow-softioc-services.rules`
with a prefix match:

```javascript
polkit.addRule(function(action, subject) {
    if (action.id == "org.freedesktop.systemd1.manage-units" &&
        subject.user == "softioc-tst" &&
        action.lookup("unit").indexOf("softioc-") == 0 &&
        action.lookup("unit").endsWith(".service")) {
        return polkit.Result.YES;
    }
});
```

This allows the `softioc-tst` user to manage and monitor any service whose name starts with
`softioc-` (e.g. `softioc-lambda-det1.service`, `softioc-mc01.service`).

## Verifying

After creating the rule, test without `sudo`:

```bash
systemctl restart xspd.service
systemctl status xspd.service
```

If it works without prompting for a password, the rule is active. No reboot or
daemon reload is required — polkit picks up new rules immediately.

## Security Notes

- Only grant access to the specific service(s) needed.
- Only grant access to the specific user account that needs to manage the service (either same account as the one running the IOC for local services, or whichever remote account is used when managing a service over ssh).
- Avoid using wildcard matches on unit names in production.
- The rule file must be owned by root with mode `644`.
