using System.Globalization;
using System.Text.Json;
using Pulumi;
using Ovh = Pulumi.Ovh;

namespace Homelab.Backup;

public static class StateResources
{
    public static Dictionary<string, object?> Create(
        string projectId, string bucketName, Ovh.CloudProject.User owner, Ovh.Provider provider)
    {
        var bucket = new Ovh.CloudProject.Storage("pulumi-state-bucket", new()
        {
            ServiceName = projectId,
            RegionName = "DE",
            Name = bucketName,
            OwnerId = owner.Id.Apply(id => double.Parse(id, CultureInfo.InvariantCulture)),
            HideObjects = true,
            Versioning = new Ovh.CloudProject.Inputs.StorageVersioningArgs { Status = "enabled" },
        }, Protected(provider));

        var lifecycle = new Ovh.CloudProjectStorageObjectBucketLifecycleConfiguration("pulumi-state-lifecycle", new()
        {
            ServiceName = projectId,
            RegionName = bucket.RegionName,
            ContainerName = bucket.Name,
            Rules =
            {
                new Ovh.Inputs.CloudProjectStorageObjectBucketLifecycleConfigurationRuleArgs
                {
                    Id = "clean-old-pulumi-versions",
                    Status = "enabled",
                    Filter = new Ovh.Inputs.CloudProjectStorageObjectBucketLifecycleConfigurationRuleFilterArgs
                    {
                        Prefix = ".pulumi/",
                    },
                    NoncurrentVersionExpiration = new Ovh.Inputs.CloudProjectStorageObjectBucketLifecycleConfigurationRuleNoncurrentVersionExpirationArgs
                    {
                        NoncurrentDays = 90,
                    },
                    AbortIncompleteMultipartUpload = new Ovh.Inputs.CloudProjectStorageObjectBucketLifecycleConfigurationRuleAbortIncompleteMultipartUploadArgs
                    {
                        DaysAfterInitiation = 7,
                    },
                },
                // OVH rejects a filter on expired-delete-marker rules.
                new Ovh.Inputs.CloudProjectStorageObjectBucketLifecycleConfigurationRuleArgs
                {
                    Id = "clean-expired-delete-markers",
                    Status = "enabled",
                    Expiration = new Ovh.Inputs.CloudProjectStorageObjectBucketLifecycleConfigurationRuleExpirationArgs
                    {
                        ExpiredObjectDeleteMarker = true,
                    },
                },
            },
        }, Protected(provider));

        var user = new Ovh.CloudProject.User("pulumi-state-user", new()
        {
            ServiceName = projectId,
            Description = "Homelab Pulumi state backend",
            RoleNames = { "objectstore_operator" },
        }, Protected(provider));

        var policy = new Ovh.CloudProject.S3Policy("pulumi-state-policy", new()
        {
            ServiceName = projectId,
            UserId = user.Id,
            Policy = bucket.Name.Apply(CreatePolicy),
        }, Protected(provider));

        var options = Protected(provider);
        options.DependsOn.Add(policy);
        options.DependsOn.Add(lifecycle);
        options.AdditionalSecretOutputs.Add("accessKeyId");
        var credential = new Ovh.CloudProject.S3Credential("pulumi-state-credential", new()
        {
            ServiceName = projectId,
            UserId = user.Id,
        }, options);

        return new()
        {
            ["stateBucketName"] = bucket.Name,
            ["stateAccessKeyId"] = Output.CreateSecret(credential.AccessKeyId),
            ["stateSecretAccessKey"] = Output.CreateSecret(credential.SecretAccessKey),
        };
    }

    private static CustomResourceOptions Protected(Ovh.Provider provider) => new()
    {
        Provider = provider,
        Protect = true,
        RetainOnDelete = true,
    };

    public static string CreatePolicy(string bucketName) => JsonSerializer.Serialize(new
    {
        // OVH strips Version on read. Keep the state user separate from the owner ACL.
        Statement = new object[]
        {
            new
            {
                Sid = "DenyBucketAdministrationAndPublicAcls",
                Effect = "Deny",
                Action = new[] { "s3:CreateBucket", "s3:DeleteBucket", "s3:PutBucketAcl", "s3:PutObjectAcl", "s3:PutBucketVersioning", "s3:PutLifecycleConfiguration" },
                Resource = new[] { "*" },
            },
            new
            {
                Sid = "ListStateBucket",
                Effect = "Allow",
                Action = new[] { "s3:ListBucket" },
                Resource = new[] { $"arn:aws:s3:::{bucketName}" },
            },
            new
            {
                Sid = "MaintainPulumiState",
                Effect = "Allow",
                Action = new[] { "s3:GetObject", "s3:PutObject", "s3:DeleteObject" },
                Resource = new[] { $"arn:aws:s3:::{bucketName}/.pulumi/*" },
            },
        },
    });
}
