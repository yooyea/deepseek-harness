# Managed DeepHarness tenant

This workspace runs in a disposable container. Never restart or replace the Harness process directly after creating or installing a profile plugin: the container filesystem is not the durable source of truth.

For a generated installable plugin bundle, ensure `package.json` has a new immutable version and declares `dsh.bundle.patch`, build it, then run:

```bash
deepharness-plugin-publish /path/to/plugin --rebuild
```

The command packages the plugin, uploads it through a short-lived tenant-scoped URL, records its desired version in the control plane, and requests a clean container rebuild. The control plane restores the exact artifact before Harness starts. A version is immutable; change `package.json` version before publishing changed bytes.

Do not place Alibaba Cloud credentials in this workspace. The command authenticates with the tenant's injected runtime token, and the control plane alone accesses private object storage.
