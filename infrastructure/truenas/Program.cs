using System.Collections;
using System.Text.Json;
using Pulumi;
using YamlDotNet.Serialization;
using TrueNas = Jetersen.Pulumi.TrueNas;

return await Deployment.RunAsync(() =>
{
    var host = new Uri(RequireEnvironment("TRUENAS_HOST"));
    if (host.Scheme != "https")
    {
        throw new InvalidOperationException("TRUENAS_HOST must use HTTPS with a trusted hostname.");
    }

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
        Compose = ReadDocument("compose.yaml"),
        Running = true,
    }, new CustomResourceOptions
    {
        Provider = provider,
        Protect = true,
        RetainOnDelete = true,
    });

    var outputs = new Dictionary<string, object?> { ["appName"] = app.Name };
    var catalogApps = JsonSerializer.Deserialize<Dictionary<string, CatalogAppConfiguration>>(
        File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "catalog-apps.json")),
        new JsonSerializerOptions(JsonSerializerDefaults.Web))
        ?? throw new InvalidOperationException("Catalog app configuration is required.");
    foreach (var (name, settings) in catalogApps)
    {
        outputs[$"{name}AppName"] = CatalogApp(name, settings.Train, settings.Version, provider).Name;
    }

    return outputs;
});

static string RequireEnvironment(string name) =>
    Environment.GetEnvironmentVariable(name) is { Length: > 0 } value
        ? value
        : throw new InvalidOperationException($"{name} is required. Run Pulumi through Varlock.");

static TrueNas.App CatalogApp(string name, string train, string version, TrueNas.Provider provider) =>
    new(name, new TrueNas.AppArgs
    {
        Name = name,
        CatalogApp = name,
        CustomApp = false,
        Train = train,
        Version = version,
        Values = Output.CreateSecret(JsonSerializer.Serialize(ReadDocument($"{name}.json"))),
        Running = true,
    }, new CustomResourceOptions
    {
        Provider = provider,
        Protect = true,
        RetainOnDelete = true,
        // Upstream cannot read this create-only selector during import.
        IgnoreChanges = { "catalogApp" },
    });

static object ReadDocument(string filename)
{
    var yaml = new DeserializerBuilder()
        .WithAttemptingUnquotedStringTypeDeserialization()
        .WithDuplicateKeyChecking()
        .Build();
    var document = yaml.Deserialize<object>(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, filename)));
    return NormalizeYaml(document) as Dictionary<string, object?>
        ?? throw new InvalidOperationException("Application configuration must be a YAML or JSON object.");
}

static object? NormalizeYaml(object? value) => value switch
{
    IDictionary map => map.Keys.Cast<object>()
        .OrderBy(key => key as string, StringComparer.Ordinal)
        .ToDictionary(
            key => key as string ?? throw new InvalidOperationException("Application configuration keys must be strings."),
            key => NormalizeYaml(map[key])),
    IList list => list.Cast<object?>().Select(NormalizeYaml).ToArray(),
    _ => value,
};

record CatalogAppConfiguration(string Train, string Version);
