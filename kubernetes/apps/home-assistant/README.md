# Home Assistant

## KVM certificate delivery

cert-manager issues a dedicated Let's Encrypt certificate for
`glkvm.jetersen.dev`. Internal DNS resolves this hostname directly to the KVM,
so console access does not depend on the Kubernetes ingress during maintenance.
Reflector copies only this certificate's TLS Secret into Home Assistant's
namespace. The KVM administrator password is stored in a separate SOPS-encrypted
Secret.

Home Assistant synchronizes the certificate when the UniFi tracker
`device_tracker.glkvm` becomes `home`, when Home Assistant starts, and when
Folder watcher detects a change to the mounted TLS Secret. Configure Folder
watcher for `/etc/glkvm/tls` with the pattern `..data`, and name its event entity
`event.glkvm_certificate_changed`. Kubernetes replaces this symlink atomically
when the Secret changes. No scheduled sync job is required.

The UniFi integration uses a local Network View Only account. Enable the KVM's
specific client in its tracking options. Home Assistant stores this integration
configuration on its persistent volume.

The sync compares the installed certificate before authenticating or uploading.
It verifies trusted HTTPS and the exact issued certificate after installation.
The last verified leaf fingerprint is retained in `/config` so an expired but
unchanged KVM certificate can be replaced after a long period offline. An unknown
certificate is rejected. Uploading reloads the KVM web server without rebooting
the KVM or its controlled computer.

Run `shell_command.glkvm_sync_certificate` to retry manually. Failures create a
persistent Home Assistant notification. A powered-off KVM is skipped; its next
online event retries with the latest certificate.
