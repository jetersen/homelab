# Code style

Use Biome for JavaScript formatting and linting, Ruff for Python, and the .NET SDK
formatter for C#. Shared editor defaults live in `.editorconfig`.

JavaScript uses two spaces, double quotes, semicolons and braced conditionals.
Python uses four spaces, double quotes and sorted imports, targeting Python 3.13
on the Trixie runner. Both formatters wrap at 100 columns. C# uses four spaces, braces on separate lines, `var`, file-scoped
namespaces and System imports first. Private fields use `_camelCase`; static
readonly fields use PascalCase.

Install the development tools with Node 24 and a Python virtual
environment:

```sh
npm ci --ignore-scripts
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
```

Run `npm run check:javascript`, `npm run check:python` and
`npm run check:csharp`. The corresponding `format:javascript`, `format:python`
and `format:csharp` scripts apply fixes. Restore the C# projects before formatting;
the TrueNAS SDK download is handled by `infrastructure/truenas/restore-provider.py`.
The root `Homelab.slnx` includes all C# projects and `global.json` selects the SDK.

DNSControl configuration uses ES5 syntax and APIs supported by its embedded Otto
runtime. Node scripts can use modern JavaScript. Separate functions and methods
with a blank line.

Go compatibility code uses `gofmt` and `go test -race`. The code-style workflow
checks all four languages using tools bundled in the runner image. Updating
`package-lock.json` or `requirements-dev.txt` also publishes a new runner image. Changes under `kubernetes/` or
`infrastructure/truenas/` can also trigger deployment workflows on `main`;
use a review branch when only code changes are authorized.
