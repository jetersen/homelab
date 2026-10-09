---
machine:
  certSANs:
    - 192.168.1.10
    - talos01
    - talos01.lan.jetersen.dev
---
apiVersion: v1alpha1
kind: KubeNodeConfig
annotations:
  installerUrl: factory.talos.dev/metal-installer/{{ .SchematicID }}:{{ .TalosVersion }}
---
apiVersion: v1alpha1
kind: UnattendedInstallConfig
provisioning:
  diskSelector:
    match: disk.dev_path == "/dev/nvme0n1"
  wipe: true
---
apiVersion: v1alpha1
kind: HostnameConfig
auto: "off"
hostname: {{ .Node.Host }}
---
apiVersion: v1alpha1
kind: ResolverConfig
nameservers:
  - address: 192.168.1.2
  - address: 192.168.1.1
  - address: fde2:b84e:c4cd:1::53
---
apiVersion: v1alpha1
kind: DHCPv4Config
name: enp1s0
---
apiVersion: v1alpha1
kind: VolumeConfig
name: EPHEMERAL
provisioning:
  diskSelector:
    match: disk.transport == "nvme"
  maxSize: 100GiB
---
apiVersion: v1alpha1
kind: UserVolumeConfig
name: local-path-provisioner
provisioning:
  diskSelector:
    match: disk.transport == "nvme"
  maxSize: 1500GiB
