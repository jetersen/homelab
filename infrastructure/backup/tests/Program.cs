using System.Collections.Concurrent;
using System.Text.Json;
using Homelab.Backup;
using Pulumi;
using Pulumi.Testing;
using Ovh = Pulumi.Ovh;

var mocks = new BackupMocks();
await Deployment.TestAsync<BackupTestStack>(mocks, new TestOptions { IsPreview = false });

var bucket = mocks.Resources.Single(r => r.Name == "kopia-bucket");
Check((string)bucket.Inputs["regionName"] == "DE", "Bucket must use Frankfurt.");
Check((double)bucket.Inputs["ownerId"] == 1001, "Bucket must belong to the separate owner.");
Check((bool)bucket.Inputs["hideObjects"], "Repository objects must stay out of infrastructure state.");
foreach (var key in new[] { "versioning", "objectLock", "replication" })
    Check(!bucket.Inputs.ContainsKey(key), $"Unexpected {key} configuration.");
Check(mocks.Resources.Count(r => r.Type?.EndsWith(":Storage") == true) == 1, "Only one bucket is allowed.");

var policy = mocks.Resources.Single(r => r.Name == "kopia-policy");
Check((string)policy.Inputs["userId"] == "2002", "Policy must target the Kopia user, not the owner.");
using var document = JsonDocument.Parse((string)policy.Inputs["policy"]);
Check(document.RootElement.EnumerateObject().Select(p => p.Name).SequenceEqual(new[] { "Statement" }),
    "OVH returns only Statement; extra root fields cause perpetual policy diffs.");
var statements = document.RootElement.GetProperty("Statement").EnumerateArray().ToArray();
var allows = statements.Where(s => s.GetProperty("Effect").GetString() == "Allow").ToArray();
Check(allows.SelectMany(s => s.GetProperty("Resource").EnumerateArray())
    .All(r => r.GetString() is "arn:aws:s3:::test-kopia" or "arn:aws:s3:::test-kopia/*"),
    "S3 access must be limited to the backup bucket.");
var allowedActions = allows.SelectMany(s => s.GetProperty("Action").EnumerateArray())
    .Select(a => a.GetString()).ToHashSet();
foreach (var action in new[] { "s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket", "s3:AbortMultipartUpload" })
    Check(allowedActions.Contains(action), $"Kopia requires {action}.");
Check(!allowedActions.Contains("s3:*"), "Wildcard S3 access is forbidden.");
var deniedActions = statements.Where(s => s.GetProperty("Effect").GetString() == "Deny")
    .SelectMany(s => s.GetProperty("Action").EnumerateArray()).Select(a => a.GetString()).ToHashSet();
Check(deniedActions.Contains("s3:DeleteBucket") && deniedActions.Contains("s3:PutObjectAcl"),
    "Bucket deletion and public object ACL changes must be explicitly denied.");

var credential = mocks.Resources.Single(r => r.Name == "kopia-credential");
Check((string)credential.Inputs["userId"] == "2002", "Only the Kopia user receives an S3 key.");
Check(mocks.Resources.Count(r => r.Type?.EndsWith(":S3Credential") == true) == 1, "Owner must not receive S3 credentials.");
Check(await Output.IsSecretAsync((Output<string>)BackupTestStack.Exports["accessKeyId"]!), "Access key output must be secret.");
Check(await Output.IsSecretAsync((Output<string>)BackupTestStack.Exports["secretAccessKey"]!), "Secret key output must be secret.");
Check(BackupTestStack.ResourceOptions.Count == 5, "All five managed resources must have protection checks.");
foreach (var options in BackupTestStack.ResourceOptions)
    Check(options.Protect == true && options.RetainOnDelete == true, "Resources must resist deletion and replacement.");
Console.WriteLine("Backup resource, permission, credential, and deletion protection checks passed; no cloud APIs called.");

static void Check(bool condition, string message)
{
    if (!condition) throw new InvalidOperationException(message);
}

public sealed class BackupTestStack : Stack
{
    public static Dictionary<string, object?> Exports { get; private set; } = new();
    public static List<ResourceOptions> ResourceOptions { get; } = new();

    public BackupTestStack() : base(new StackOptions
    {
        ResourceTransformations =
        {
            args =>
            {
                if (args.Resource is CustomResource and not ProviderResource)
                    ResourceOptions.Add(args.Options);
                return null;
            },
        },
    })
    {
        var provider = new Ovh.Provider("ovh-eu", new() { Endpoint = "ovh-eu" });
        Exports = BackupResources.Create("test-project", "test-kopia", provider);
    }
}

public sealed class BackupMocks : IMocks
{
    public ConcurrentBag<MockResourceArgs> Resources { get; } = new();

    public Task<(string? id, object state)> NewResourceAsync(MockResourceArgs args)
    {
        Resources.Add(args);
        var state = new Dictionary<string, object>(args.Inputs);
        if (args.Name == "kopia-credential")
        {
            state["accessKeyId"] = "fake-access-key";
            state["secretAccessKey"] = "fake-secret-key";
        }
        var id = args.Name switch { "bucket-owner" => "1001", "kopia-user" => "2002", _ => args.Name + "-id" };
        return Task.FromResult<(string?, object)>((id, state));
    }

    public Task<object> CallAsync(MockCallArgs args) =>
        throw new InvalidOperationException("Tests must not invoke cloud lookups.");
}
