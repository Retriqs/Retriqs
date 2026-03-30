# LightRAG WebUI

LightRAG WebUI is a React-based web interface for interacting with the LightRAG system. It provides a user-friendly interface for querying, managing, and exploring LightRAG's functionalities.

## Installation

1. **Install Bun:**

    If you haven't already installed Bun, follow the official documentation: [https://bun.sh/docs/installation](https://bun.sh/docs/installation)

2. **Install Dependencies:**

    In the `retriqs_webui` directory, run the following command to install project dependencies:

    ```bash
    bun install --frozen-lockfile
    ```

3. **Build the Project:**

    Run the following command to build the project:

    ```bash
    bun run build
    ```

    This command will bundle the project and output the built files to the `retriqs/api/webui` directory.

## Development

- **Start the Development Server:**

  If you want to run the WebUI in development mode, use the following command:

  ```bash
  bun run dev
  ```

## Tauri Development (Minimal Setup)

This setup keeps the API server and frontend dev server separate. Tauri only opens a desktop window pointing to `http://localhost:1420`.

### Prerequisites (Windows)

- Python environment for API (`.venv` with `lightrag-hku[api]` installed)
- Bun installed
- Rust toolchain installed (`rustup`, includes `cargo`)
- Microsoft C++ Build Tools (Desktop development with C++)
- Microsoft Edge WebView2 runtime

### 1. Build or place the backend bundle

The Tauri shell now starts or reuses the bundled backend automatically in dev mode too. Make sure the backend bundle exists at:

`src-tauri/backend/retriqs-backend/retriqs-backend.exe`

The easiest way to prepare it is:

```bash
../scripts/build_nuitka_sidecar.ps1
```

You do not need to run `retriqs-server` separately unless you explicitly want to test against a manually started backend.

### 2. Start WebUI dev server (terminal 1, `retriqs_webui/`)

```bash
bun install
bun run dev:tauri-ui
```

In dev mode, the frontend resolves the backend URL from Tauri at runtime, so it should target the managed local backend automatically.

### 3. Start Tauri shell (terminal 2, `retriqs_webui/`)

```bash
bun run tauri:dev
```

Tauri uses `src-tauri/tauri.conf.json` with `devUrl: http://localhost:1420`, opens the Vite dev UI, and starts or reuses the bundled backend on `http://127.0.0.1:9621`.

## Tauri Production Packaging

Production desktop packaging uses:

- Tauri for the desktop shell and Windows installers
- Nuitka for the bundled Python backend

### Build the backend bundle

From the repo root:

```powershell
./scripts/build_nuitka_sidecar.ps1
```

This builds a standalone `retriqs-backend` folder and stages it into `src-tauri/backend/` for Tauri packaging.

Gemini support is excluded from the desktop backend by default because the current `google-genai` package can exhaust MSVC heap space during Nuitka compilation. If you need Gemini in a desktop build, opt in explicitly:

```powershell
./scripts/build_nuitka_sidecar.ps1 -EnableGemini
```

### Build the desktop installer

From the repo root:

```powershell
./scripts/build_desktop.ps1
```

This produces Windows desktop bundles under `src-tauri/target/release/bundle/`. The installed desktop app will probe `http://127.0.0.1:9621`, start the bundled backend if needed, hide to tray on close, and terminate the backend only on explicit quit.

### Windows code signing

The desktop packaging flow supports optional Windows signing without changing the existing manual steps:

```powershell
./scripts/build_nuitka_sidecar.ps1
cd retriqs_webui
bun run tauri:bundle
```

When `D3VS_WINDOWS_SIGN=1` is set, the build will:

- sign `dist/desktop/retriqs-backend.dist/retriqs-backend.exe` during the Nuitka sidecar step
- sign Tauri-generated Windows artifacts during `bun run tauri:bundle`

The configured certificate must belong to `d3vs B.V.`. Provide one of these certificate sources:

```powershell
$env:D3VS_WINDOWS_SIGN = "1"
$env:D3VS_WINDOWS_CERT_THUMBPRINT = "<thumbprint from Cert:\\CurrentUser\\My or Cert:\\LocalMachine\\My>"
```

Or:

```powershell
$env:D3VS_WINDOWS_SIGN = "1"
$env:D3VS_WINDOWS_PFX_PATH = "C:\\path\\to\\d3vs-bv-codesign.pfx"
$env:D3VS_WINDOWS_PFX_PASSWORD = "<pfx password>"
```

Optional settings:

```powershell
$env:D3VS_WINDOWS_TIMESTAMP_URL = "http://timestamp.digicert.com"
$env:D3VS_WINDOWS_DIGEST_ALGORITHM = "sha256"
```

If signing is enabled but the certificate subject does not contain `d3vs B.V.`, the build will fail.

## Script Commands

The following are some commonly used script commands defined in `package.json`:

- `bun install`: Installs project dependencies.
- `bun run dev`: Starts the development server.
- `bun run dev:tauri-ui`: Starts Vite on `http://localhost:1420` for Tauri dev.
- `bun run tauri:dev`: Starts Tauri desktop window in development mode.
- `bun run build`: Builds the project.
- `bun run lint`: Runs the linter.
