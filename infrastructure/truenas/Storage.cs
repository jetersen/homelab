using Pulumi;
using TrueNas = Jetersen.Pulumi.TrueNas;

static class Storage
{
    public static void Configure(TrueNas.Provider provider)
    {
        _ = new TrueNas.NfsConfig("nfs", new TrueNas.NfsConfigArgs
        {
            Protocols = { "NFSV3", "NFSV4" },
            AllowNonroot = false,
            Bindips = { },
            MountdLog = false,
            MountdPort = 0,
            RpclockdPort = 0,
            RpcstatdPort = 0,
            StatdLockdLog = false,
            UserdManageGids = false,
            V4Domain = "",
            V4Krb = false,
            Rdma = false,
        }, Retained(provider));

        _ = new TrueNas.Service("nfs-service", new TrueNas.ServiceArgs
        {
            Name = "nfs",
            Enabled = true,
            Running = true,
        }, Retained(provider));

        Share("git-nfs", new TrueNas.NfsShareArgs
        {
            Path = "/mnt/nvme/git",
            Networks = { "192.168.1.0/24" },
            MapallUser = "apps",
            MapallGroup = "apps",
        }, provider);

        Share("backup-nfs", new TrueNas.NfsShareArgs
        {
            Path = "/mnt/nvme/backup",
            Comment = "used for backup",
            Networks = { "192.168.1.0/24" },
            MapallUser = "apps",
            MapallGroup = "apps",
        }, provider);

        Share("media-nfs", new TrueNas.NfsShareArgs
        {
            Path = "/mnt/nvme/media",
            Comment = "Kubernetes homelab media stack",
            Hosts = { "192.168.1.10", "192.168.1.128" },
            MapallUser = "apps",
            MapallGroup = "apps",
            Securities = { "SYS" },
        }, provider);

        Share("kubernetes-backup-nfs", new TrueNas.NfsShareArgs
        {
            Path = "/mnt/nvme/backup/kubernetes",
            Comment = "Encrypted Kubernetes application backups",
            Hosts = { "192.168.1.10" },
            MapallUser = "apps",
            MapallGroup = "apps",
            Securities = { "SYS" },
        }, provider);

        Share("forgejo-nfs", new TrueNas.NfsShareArgs
        {
            Path = "/mnt/nvme/forgejo",
            Comment = "Forgejo repositories and application uploads",
            Hosts = { "192.168.1.10" },
            Securities = { "SYS" },
        }, provider);

        Share("forgejo-backup-staging-nfs", new TrueNas.NfsShareArgs
        {
            Path = "/mnt/nvme/forgejo-backup-staging",
            Comment = "Forgejo consistent backup staging",
            Hosts = { "192.168.1.10" },
            Securities = { "SYS" },
        }, provider);
    }

    private static void Share(string name, TrueNas.NfsShareArgs args, TrueNas.Provider provider)
    {
        args.Enabled = true;
        args.Ro = false;
        args.ExposeSnapshots = false;
        _ = new TrueNas.NfsShare(name, args, Retained(provider));
    }

    private static CustomResourceOptions Retained(TrueNas.Provider provider) => new()
    {
        Provider = provider,
        Protect = true,
        RetainOnDelete = true,
    };
}
