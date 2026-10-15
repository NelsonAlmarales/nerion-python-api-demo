# Python API pagination and failure-handling demo

A small, AI-assisted programming sample by **Nerion Dev**. It uses invented tickets and a local HTTP server. This is a synthetic capability demonstration, with no client deployment or production results claimed.

The sample shows how a bounded export can retrieve both pages, retry a temporary rate limit, and stop on specific failures. It uses only Python's standard library and makes requests to its own server on `127.0.0.1`. No API key, account, external service or package installation is needed.

## Run on Windows

Save `demo_api_local.py` alongside this file. Use an existing CPython 3.12 or newer installation. In PowerShell, replace the placeholder below with the actual path to that interpreter:

```powershell
$DemoPython = 'C:\Path\To\python.exe' # Replace this placeholder.
& $DemoPython --version
& $DemoPython -I .\demo_api_local.py --output .\results\demo-001
```

For the same checks with Python optimization enabled, use a different, new output directory:

```powershell
& $DemoPython -I -O .\demo_api_local.py --output .\results\demo-002
```

An existing output directory is refused with exit code 2. Read `RESULTADO.json` and `report.json` inside the newly created output directory. Successful execution reports `PASS_LOCAL_HTTP_SYNTHETIC_ONLY` and exits with code 0; a failed acceptance check exits with code 1. Check both the exit code and the receipt.

## Expected observations

| Synthetic case | Expected observation |
| --- | --- |
| Two pages after a rate limit | HTTP 429, 200, 200; two tickets, two pages |
| First-page-only example versus complete export | One ticket versus two tickets |
| Unauthorized response | The export stops after one HTTP 401 |
| Persistent unavailable response | The export stops after two HTTP 503 responses |
| Invalid JSON | The export stops with a JSON decoding error |

The receipt records measured values separately from expected values, the Python runtime, source hash and output hash. Review the actual measurements rather than relying only on a PASS label.

## Scope and limits

The input contract is deliberately narrow: `data` / `next_cursor` pages, and three string fields per invented ticket. This does not demonstrate a third-party API integration, OAuth, a scheduler, a Google Sheets connection, deployment, load capacity or a repaired client system. HTTP-date `Retry-After` is unsupported. Production-grade atomic output replacement and filesystem syncing are outside this sample.

The source was developed and reviewed with AI assistance. The release commands above are checked on Windows using the explicit interpreter path; no registered `py` launcher or `python` command on PATH is assumed. No Linux execution is claimed. A client task would need its own agreed input contract, acceptance criteria and funded scope before implementation.
