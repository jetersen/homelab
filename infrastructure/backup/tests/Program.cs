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
{
    Check(!bucket.Inputs.ContainsKey(key), $"Unexpected {key} configuration.");
}

Check(mocks.Resources.Count(r => r.Type?.EndsWith(":Storage") == true) == 2, "Backup and state require separate buckets.");

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
{
    Check(allowedActions.Contains(action), $"Kopia requires {action}.");
}

Check(!allowedActions.Contains("s3:*"), "Wildcard S3 access is forbidden.");
var deniedActions = statements.Where(s => s.GetProperty("Effect").GetString() == "Deny")
    .SelectMany(s => s.GetProperty("Action").EnumerateArray()).Select(a => a.GetString()).ToHashSet();
Check(deniedActions.Contains("s3:DeleteBucket") && deniedActions.Contains("s3:PutObjectAcl"),
    "Bucket deletion and public object ACL changes must be explicitly denied.");

var credential = mocks.Resources.Single(r => r.Name == "kopia-credential");
Check((string)credential.Inputs["userId"] == "2002", "Only the Kopia user receives an S3 key.");
Check(mocks.Resources.Count(r => r.Type?.EndsWith(":S3Credential") == true) == 2, "Only Kopia and state users receive credentials.");
Check(await Output.IsSecretAsync((Output<string>)BackupTestStack.Exports["accessKeyId"]!), "Access key output must be secret.");
Check(await Output.IsSecretAsync((Output<string>)BackupTestStack.Exports["secretAccessKey"]!), "Secret key output must be secret.");
var stateBucket = mocks.Resources.Single(r => r.Name == "pulumi-state-bucket");
Check((string)stateBucket.Inputs["name"] == "test-pulumi", "State must not share the Kopia bucket.");
Check((string)stateBucket.Inputs["regionName"] == "DE", "State must use Frankfurt.");
Check((double)stateBucket.Inputs["ownerId"] == 1001, "State must use the owner without credentials.");
Check((bool)stateBucket.Inputs["hideObjects"], "State bucket contents must not be embedded in state.");
Check(((IReadOnlyDictionary<string, object>)stateBucket.Inputs["versioning"])["status"].ToString() == "enabled",
    "State must retain previous object versions.");
var lifecycle = mocks.Resources.Single(r => r.Name == "pulumi-state-lifecycle");
Check((string)lifecycle.Inputs["containerName"] == "test-pulumi", "Cleanup must target only the state bucket.");
var rules = ((IEnumerable<object>)lifecycle.Inputs["rules"]).Cast<IReadOnlyDictionary<string, object>>().ToArray();
Check(rules.Length == 2, "OVH requires a separate unfiltered expired-delete-marker rule.");
var rule = rules.Single(r => (string)r["id"] == "clean-old-pulumi-versions");
Check((string)rule["status"] == "enabled", "State version cleanup must be enabled.");
Check((string)((IReadOnlyDictionary<string, object>)rule["filter"])["prefix"] == ".pulumi/",
    "Cleanup must target only Pulumi objects.");
Check(Convert.ToDouble(((IReadOnlyDictionary<string, object>)rule["noncurrentVersionExpiration"])["noncurrentDays"]) == 90,
    "Superseded state versions must expire after 90 days.");
Check(!rule.ContainsKey("expiration"), "Version cleanup must not expire current state objects.");
var markerRule = rules.Single(r => (string)r["id"] == "clean-expired-delete-markers");
Check((string)markerRule["status"] == "enabled", "Delete marker cleanup must be enabled.");
Check(!markerRule.ContainsKey("filter"), "OVH rejects filters with expired-delete-marker cleanup.");
var expiration = (IReadOnlyDictionary<string, object>)markerRule["expiration"];
Check((bool)expiration["expiredObjectDeleteMarker"], "Expired delete markers must be removed.");
Check(!expiration.ContainsKey("days") && !expiration.ContainsKey("date"), "Current state objects must never expire.");
Check(Convert.ToDouble(((IReadOnlyDictionary<string, object>)rule["abortIncompleteMultipartUpload"])["daysAfterInitiation"]) == 7,
    "Abandoned uploads must be aborted after seven days.");
var statePolicy = mocks.Resources.Single(r => r.Name == "pulumi-state-policy");
Check((string)statePolicy.Inputs["userId"] == "3003", "State policy must target a separate user.");
using var stateDocument = JsonDocument.Parse((string)statePolicy.Inputs["policy"]);
Check(!stateDocument.RootElement.TryGetProperty("Version", out _), "OVH state policy must omit Version.");
var stateStatements = stateDocument.RootElement.GetProperty("Statement").EnumerateArray().ToArray();
var stateAllows = stateStatements.Where(s => s.GetProperty("Effect").GetString() == "Allow").ToArray();
Check(stateAllows.SelectMany(s => s.GetProperty("Resource").EnumerateArray())
    .All(r => r.GetString() is "arn:aws:s3:::test-pulumi" or "arn:aws:s3:::test-pulumi/.pulumi/*"),
    "State access must stay within the state bucket and Pulumi prefix.");
Check(stateAllows.SelectMany(s => s.GetProperty("Action").EnumerateArray()).Select(a => a.GetString()).ToHashSet()
    .SetEquals(new[] { "s3:ListBucket", "s3:GetObject", "s3:PutObject", "s3:DeleteObject" }),
    "State requires only list, read, write, and delete permissions.");
var stateDenies = stateStatements.Where(s => s.GetProperty("Effect").GetString() == "Deny")
    .SelectMany(s => s.GetProperty("Action").EnumerateArray()).Select(a => a.GetString()).ToHashSet();
Check(stateDenies.Contains("s3:PutBucketVersioning") && stateDenies.Contains("s3:PutLifecycleConfiguration"),
    "State user must not alter retention.");
Check(!stateDenies.Contains("s3:DeleteObjectVersion"), "OVH rejects the unsupported DeleteObjectVersion action.");
Check((string)mocks.Resources.Single(r => r.Name == "pulumi-state-credential").Inputs["userId"] == "3003",
    "State credentials must belong to the state user.");
foreach (var key in new[] { "stateAccessKeyId", "stateSecretAccessKey" })
{
    Check(await Output.IsSecretAsync((Output<string>)BackupTestStack.Exports[key]!), "State credentials must be secret.");
}

Check(BackupTestStack.ResourceOptions.Count == 10, "All ten managed resources must have protection checks.");
foreach (var options in BackupTestStack.ResourceOptions)
{
    Check(options.Protect == true && options.RetainOnDelete == true, "Resources must resist deletion and replacement.");
}

Console.WriteLine("Backup resource, permission, credential, and deletion protection checks passed; no cloud APIs called.");

static void Check(bool condition, string message)
{
    if (!condition)
    {
        throw new InvalidOperationException(message);
    }
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
                {
                    ResourceOptions.Add(args.Options);
                }

                return null;
            },
        },
    })
    {
        var provider = new Ovh.Provider("ovh-eu", new()
        {
            Endpoint = "ovh-eu"
        });
        Exports = BackupResources.Create("test-project", "test-kopia", "test-pulumi", provider);
    }
}

public sealed class BackupMocks : IMocks
{
    public ConcurrentBag<MockResourceArgs> Resources { get; } = new();

    public Task<(string? id, object state)> NewResourceAsync(MockResourceArgs args)
    {
        Resources.Add(args);
        var state = new Dictionary<string, object>(args.Inputs);
        if (args.Name is "kopia-credential" or "pulumi-state-credential")
        {
            state["accessKeyId"] = "fake-access-key";
            state["secretAccessKey"] = "fake-secret-key";
        }
        var id = args.Name switch
        {
            "bucket-owner" => "1001",
            "kopia-user" => "2002",
            "pulumi-state-user" => "3003",
            _ => args.Name + "-id"
        };
        return Task.FromResult<(string?, object)>((id, state));
    }

    public Task<object> CallAsync(MockCallArgs args) =>
        throw new InvalidOperationException("Tests must not invoke cloud lookups.");
}
