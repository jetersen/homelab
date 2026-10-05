using Homelab.Backup;
using Pulumi;
using Ovh = Pulumi.Ovh;

return await Deployment.RunAsync(() =>
{
    var config = new Config();
    var provider = new Ovh.Provider("ovh-eu", new Ovh.ProviderArgs
    {
        Endpoint = "ovh-eu",
        ApplicationKey = SecretEnvironment("OVH_APPLICATION_KEY"),
        ApplicationSecret = SecretEnvironment("OVH_APPLICATION_SECRET"),
        ConsumerKey = SecretEnvironment("OVH_CONSUMER_KEY"),
    });

    return BackupResources.Create(
        config.Require("projectId"), config.Require("bucketName"), config.Require("stateBucketName"), provider);
});

static Output<string> SecretEnvironment(string name)
{
    var value = Environment.GetEnvironmentVariable(name);
    if (string.IsNullOrWhiteSpace(value))
    {
        throw new InvalidOperationException($"{name} is required. Run Pulumi through Varlock.");
    }

    return Output.CreateSecret(value);
}
