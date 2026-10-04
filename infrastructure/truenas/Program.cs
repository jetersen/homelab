using Pulumi;
using TrueNas = Jetersen.Pulumi.TrueNas;

return await Deployment.RunAsync(() =>
{
    var host = new Uri(RequireEnvironment("TRUENAS_HOST"));
    if (host.Scheme != "https")
        throw new InvalidOperationException("TRUENAS_HOST must use HTTPS with a trusted hostname.");
    var endpoint = new UriBuilder(host) { Scheme = "wss", Path = "/api/current", Query = "" };
    var provider = new TrueNas.Provider("nas", new TrueNas.ProviderArgs
    {
        Endpoint = endpoint.Uri.ToString(),
        ApiKey = Output.CreateSecret(RequireEnvironment("TRUENAS_TOKEN")),
        Insecure = false,
    });

    var app = new TrueNas.App("technitium", new TrueNas.AppArgs
    {
        Name = "technitium",
        CustomApp = true,
        CustomComposeConfigString = File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "compose.yaml")),
        Running = true,
    }, new CustomResourceOptions
    {
        Provider = provider,
        Protect = true,
        RetainOnDelete = true,
    });

    return new Dictionary<string, object?> { ["appName"] = app.Name };
});

static string RequireEnvironment(string name) =>
    Environment.GetEnvironmentVariable(name) is { Length: > 0 } value
        ? value
        : throw new InvalidOperationException($"{name} is required. Run Pulumi through Varlock.");
