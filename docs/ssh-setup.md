# SSH Key Setup for Remote Service Control

When managing a service on a remote host, the IOC uses `systemctl --host user@server`
which relies on SSH. This requires passwordless SSH authentication via key pairs.

> **Important:** All steps below should be performed as the user account that
> will run the IOC (e.g. `softioc-tst`). SSH keys are per-user, so they must exist
> in that user's `~/.ssh/` directory.

## Example: Managing `xspd.service` on a Remote X-Spectrum Server

In this example, the IOC runs on the controls server (`xf28id1-det3`) and manages
the `xspd` service running on the X-Spectrum detector control server (`xf28id1-lambda1`).

### 1. Generate an SSH Key Pair (on the IOC host)

Generate a dedicated key for the IOC process. Use no passphrase so the IOC can
connect without user interaction:

```bash
# As the user that will run the IOC (e.g. "softioc-tst")
ssh-keygen -t ed25519 -f ~/.ssh/id_xspd -N "" -C "remote-svc-ctrl IOC"
```

### 2. Copy the Public Key to the Remote Host

```bash
ssh-copy-id -i ~/.ssh/id_xspd.pub xspadmin@xf28id1-lambda1
```

Or manually append the public key to the remote `~/.ssh/authorized_keys` on the remote host.
You'll need to enter the password of the account on the remote host one last time for this step.

**Note** - The remote user (`xspadmin` in this example) must have permission to manage the target service (`xspd.service`). This may require a polkit rule on the remote host. See [polkit.md](docs/polkit.md) for details. In addition, the remote user and the local user do not necessarily have to be the same (e.g. you could allow `softioc-tst` on the IOC host to SSH as `xspadmin` on the remote host), but the SSH key must be set up for the remote user that will be used in the `--host` argument when running the IOC.

### 3. Configure SSH Client (Optional but Recommended)

Add an entry to `~/.ssh/config` to use the dedicated key automatically:

```
Host xf28id1-lambda1
    HostName xf28id1-lambda1
    User xspadmin
    IdentityFile ~/.ssh/id_xspd
    StrictHostKeyChecking accept-new
    BatchMode yes
```

The `BatchMode yes` option prevents SSH from ever prompting for a password,
which would hang the IOC process.

### 4. Test the Connection

```bash
systemctl --host xspadmin@xf28id1-lambda1 status xspd.service
```

This should return the service status without any password prompt.

### 5. Run the IOC

```bash
remote-svc-ctrl "XF:28ID1-CT{SVC-XSPD:1}" xspd.service --host controls@xf28id1-lambda1
```

## Combining with Polkit on the Remote Host

If the remote user is not root, you also need a polkit rule on the remote host
to allow service management. See [polkit.md](polkit.md) for details.

The full setup for remote service control is:

1. SSH key on IOC host → passwordless login to remote host
2. Polkit rule on remote host → passwordless `systemctl start/stop/restart`

## Security Recommendations

- Use a dedicated SSH key pair for the IOC (not a shared user key).
- Restrict the remote user's permissions to only what's needed.
