using System.Globalization;
using System.Text.Json;
using Pulumi;
using Ovh = Pulumi.Ovh;

namespace Homelab.Backup;

public static class BackupResources
{
    public static Dictionary<string, object?> Create(string projectId, string bucketName, string stateBucketName, Ovh.Provider provider)
    {
        // The Kopia user must not inherit the bucket owner's FULL_CONTROL ACL.
        var owner = new Ovh.CloudProject.User("bucket-owner", new()
        {
            ServiceName = projectId,
            Description = "Homelab backup bucket owner; no S3 credentials issued",
            RoleNames = { "objectstore_operator" },
        }, Protected(provider));

        var bucket = new Ovh.CloudProject.Storage("kopia-bucket", new()
        {
            ServiceName = projectId,
            RegionName = "DE",
            Name = bucketName,
            OwnerId = owner.Id.Apply(id => double.Parse(id, CultureInfo.InvariantCulture)),
            HideObjects = true,
            // Standard is the default PUT class on the .io endpoint. No lifecycle,
            // versioning, Object Lock, or replication is configured here.
        }, Protected(provider));

        var kopia = new Ovh.CloudProject.User("kopia-user", new()
        {
            ServiceName = projectId,
            Description = "Homelab Kopia backup and repository maintenance",
            RoleNames = { "objectstore_operator" },
        }, Protected(provider));

        var policy = new Ovh.CloudProject.S3Policy("kopia-policy", new()
        {
            ServiceName = projectId,
            UserId = kopia.Id,
            Policy = bucket.Name.Apply(CreatePolicy),
        }, Protected(provider));

        var credentialOptions = Protected(provider);
        credentialOptions.DependsOn.Add(policy);
        credentialOptions.AdditionalSecretOutputs.Add("accessKeyId");
        var credential = new Ovh.CloudProject.S3Credential("kopia-credential", new()
        {
            ServiceName = projectId,
            UserId = kopia.Id,
        }, credentialOptions);

        var exports = new Dictionary<string, object?>
        {
            ["projectId"] = projectId,
            ["bucketName"] = bucket.Name,
            ["region"] = "de",
            ["endpoint"] = "s3.de.io.cloud.ovh.net",
            ["storageClass"] = "STANDARD",
            ["accessKeyId"] = Output.CreateSecret(credential.AccessKeyId),
            ["secretAccessKey"] = Output.CreateSecret(credential.SecretAccessKey),
        };
        foreach (var (key, value) in StateResources.Create(projectId, stateBucketName, owner, provider))
        {
            exports.Add(key, value);
        }

        return exports;
    }

    private static CustomResourceOptions Protected(Ovh.Provider provider) => new()
    {
        Provider = provider,
        Protect = true,
        RetainOnDelete = true,
    };

    public static string CreatePolicy(string bucketName) => JsonSerializer.Serialize(new
    {
        // OVH strips the AWS Version field on read; omit it to avoid perpetual diffs.
        Statement = new object[]
        {
            new
            {
                Sid = "DenyBucketAdministrationAndPublicAcls",
                Effect = "Deny",
                Action = new[] { "s3:CreateBucket", "s3:DeleteBucket", "s3:PutBucketAcl", "s3:PutObjectAcl" },
                Resource = new[] { "*" },
            },
            new
            {
                Sid = "ListBackupBucket",
                Effect = "Allow",
                Action = new[] { "s3:ListBucket", "s3:GetBucketLocation", "s3:ListBucketMultipartUploads" },
                Resource = new[] { $"arn:aws:s3:::{bucketName}" },
            },
            new
            {
                Sid = "MaintainKopiaObjects",
                Effect = "Allow",
                Action = new[]
                {
                    "s3:GetObject", "s3:PutObject", "s3:DeleteObject",
                    "s3:ListMultipartUploadParts", "s3:AbortMultipartUpload",
                },
                Resource = new[] { $"arn:aws:s3:::{bucketName}/*" },
            },
        },
    });
}
