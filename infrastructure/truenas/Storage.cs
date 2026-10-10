using Pulumi;
using TrueNas = Jetersen.Pulumi.TrueNas;

static class Storage
{
    public static void Configure(TrueNas.Provider provider)
    {
        var backup = Dataset("backup-dataset", new TrueNas.DatasetArgs
        {
            Name = "nvme/backup",
            Copies = 1,
        }, provider);

        _ = Dataset("kubernetes-backup-dataset", new TrueNas.DatasetArgs
        {
            Name = backup.Name.Apply(name => $"{name}/kubernetes"),
            Acltype = "posix",
            Aclmode = "DISCARD",
            Atime = "OFF",
            Exec = "OFF",
            Sync = "STANDARD",
            Quota = 100L * 1024 * 1024 * 1024,
        }, provider);

        _ = Dataset("forgejo-dataset", new TrueNas.DatasetArgs
        {
            Name = "nvme/forgejo",
            Acltype = "posix",
            Aclmode = "DISCARD",
            Atime = "OFF",
            Exec = "ON",
            Sync = "STANDARD",
            Quota = 100L * 1024 * 1024 * 1024,
        }, provider);

        _ = Dataset("apps-dataset", new TrueNas.DatasetArgs
        {
            Name = "nvme/apps",
            Acltype = "nfsv4",
            Aclmode = "PASSTHROUGH",
            Atime = "OFF",
            Copies = 1,
        }, provider);

        _ = Dataset("media-dataset", new TrueNas.DatasetArgs
        {
            Name = "nvme/media",
            Copies = 1,
        }, provider);

        _ = Dataset("git-dataset", new TrueNas.DatasetArgs
        {
            Name = "nvme/git",
            Copies = 1,
        }, provider);

        _ = Dataset("forgejo-backup-staging-dataset", new TrueNas.DatasetArgs
        {
            Name = "nvme/forgejo-backup-staging",
            Acltype = "posix",
            Aclmode = "DISCARD",
            Atime = "OFF",
            Exec = "ON",
            Sync = "STANDARD",
            Quota = 120L * 1024 * 1024 * 1024,
        }, provider);

        _ = Dataset("share-dataset", new TrueNas.DatasetArgs
        {
            Name = "nvme/share",
            Copies = 1,
        }, provider);

        _ = new TrueNas.ScrubTask("nvme-scrub", new TrueNas.ScrubTaskArgs
        {
            Pool = 1,
            Enabled = true,
            Threshold = 35,
            Schedule = new TrueNas.Inputs.ScrubTaskScheduleArgs
            {
                Minute = "00",
                Hour = "00",
                Dom = "*",
                Month = "*",
                Dow = "7",
            },
        }, Retained(provider));

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

    private static TrueNas.Dataset Dataset(string name, TrueNas.DatasetArgs args, TrueNas.Provider provider)
    {
        args.Type = "filesystem";
        args.Compression ??= "inherit";
        args.Acltype ??= "inherit";
        args.Aclmode ??= "INHERIT";
        args.Atime ??= "INHERIT";
        args.Checksum ??= "INHERIT";
        args.Dedup ??= "INHERIT";
        args.Exec ??= "INHERIT";
        args.Readonly ??= "INHERIT";
        args.Snapdir ??= "INHERIT";
        args.Sync ??= "INHERIT";
        return new TrueNas.Dataset(name, args, Retained(provider));
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
