#[cfg_attr(mobile, tauri::mobile_entry_point)]
use reqwest::blocking::Client;
use rfd::{MessageButtons, MessageDialog, MessageLevel};
use serde::Serialize;
#[cfg(target_os = "macos")]
use std::fs;
use std::{
  env,
  path::PathBuf,
  process::{Child, Command, Stdio},
  sync::{
    atomic::{AtomicBool, Ordering},
    Mutex,
  },
  thread,
  time::{Duration, Instant},
};
#[cfg(windows)]
use std::os::windows::process::CommandExt;
use tauri::{
  menu::MenuBuilder,
  tray::TrayIconBuilder,
  AppHandle, Manager, RunEvent, WindowEvent,
};

const BACKEND_URL: &str = "http://127.0.0.1:9621";
const HEALTH_URL: &str = "http://127.0.0.1:9621/health";
const BACKEND_STARTUP_TIMEOUT: Duration = Duration::from_secs(45);
const BACKEND_POLL_INTERVAL: Duration = Duration::from_millis(500);
const MENU_OPEN: &str = "open";
const MENU_RESTART_BACKEND: &str = "restart-backend";
const MENU_QUIT: &str = "quit";
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct BackendRuntime {
  backend_base_url: String,
  desktop: bool,
}

#[derive(Default)]
struct DesktopState {
  backend_child: Mutex<Option<Child>>,
  quitting: AtomicBool,
}

enum BackendProbe {
  Ready,
  Starting,
  Unavailable,
  ConflictingProcess(String),
}

#[tauri::command]
fn get_backend_runtime() -> BackendRuntime {
  BackendRuntime {
    backend_base_url: BACKEND_URL.to_string(),
    desktop: true,
  }
}

fn probe_backend() -> BackendProbe {
  let client = match Client::builder()
    .timeout(Duration::from_secs(2))
    .build()
  {
    Ok(client) => client,
    Err(error) => {
      return BackendProbe::ConflictingProcess(format!(
        "Failed to create health probe client: {error}"
      ))
    }
  };

  match client
    .get(HEALTH_URL)
    .header("Accept", "application/json")
    .send()
  {
    Ok(response) => match response.json::<serde_json::Value>() {
      Ok(json) => match json.get("status").and_then(|value| value.as_str()) {
        Some("healthy") => BackendProbe::Ready,
        Some("starting") => BackendProbe::Starting,
        Some("error") => BackendProbe::ConflictingProcess(
          json
            .get("message")
            .and_then(|value| value.as_str())
            .unwrap_or("Backend reported an error state.")
            .to_string(),
        ),
        Some(other) => BackendProbe::ConflictingProcess(format!(
          "Port 9621 responded with unsupported backend status: {other}"
        )),
        None => BackendProbe::ConflictingProcess(
          "Port 9621 is responding, but it is not a Retriqs backend.".into(),
        ),
      },
      Err(error) => BackendProbe::ConflictingProcess(format!(
        "Port 9621 is in use, but the response is not a valid Retriqs backend: {error}"
      )),
    },
    Err(error) if error.is_connect() || error.is_timeout() => BackendProbe::Unavailable,
    Err(error) => BackendProbe::ConflictingProcess(format!(
      "Port 9621 responded unexpectedly: {error}"
    )),
  }
}

fn wait_for_backend_ready() -> Result<(), String> {
  let start = Instant::now();

  loop {
    match probe_backend() {
      BackendProbe::Ready => return Ok(()),
      BackendProbe::Starting | BackendProbe::Unavailable => {
        if start.elapsed() > BACKEND_STARTUP_TIMEOUT {
          return Err(format!(
            "Timed out waiting for the backend to report healthy status at {HEALTH_URL}."
          ));
        }
      }
      BackendProbe::ConflictingProcess(message) => return Err(message),
    }

    thread::sleep(BACKEND_POLL_INTERVAL);
  }
}

fn terminate_managed_backend(app: &AppHandle) {
  let state = app.state::<DesktopState>();
  let child = {
    let mut backend_child = state.backend_child.lock().unwrap();
    backend_child.take()
  };

  if let Some(child) = child {
    let mut child = child;
    let _ = child.kill();
    let _ = child.wait();
  }
}

fn backend_search_paths(app: &AppHandle) -> Vec<PathBuf> {
  let manifest_backend = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
    .join("backend")
    .join("retriqs-backend")
    .join("retriqs-backend.exe");
  let release_backend = env::current_exe()
    .ok()
    .and_then(|path| path.parent().map(|dir| dir.to_path_buf()))
    .map(|dir| {
      dir
        .join("backend")
        .join("retriqs-backend")
        .join("retriqs-backend.exe")
    });
  let resource_backend = app
    .path()
    .resource_dir()
    .ok()
    .map(|dir| {
      dir
        .join("backend")
        .join("retriqs-backend")
        .join("retriqs-backend.exe")
    });

  let mut candidates = Vec::new();
  if let Some(path) = resource_backend {
    candidates.push(path);
  }
  if let Some(path) = release_backend {
    candidates.push(path);
  }
  candidates.push(manifest_backend);
  candidates
}

fn backend_executable_path(app: &AppHandle) -> Result<PathBuf, String> {
  backend_search_paths(app)
    .into_iter()
    .find(|path| path.exists())
    .ok_or_else(|| {
      "Failed to locate bundled backend files. Rebuild the desktop backend before launching the app."
        .to_string()
    })
}

fn resolve_backend_runtime_dirs(app: &AppHandle) -> Result<(PathBuf, Option<PathBuf>), String> {
  #[cfg(target_os = "macos")]
  {
    let app_data_dir = app
      .path()
      .app_data_dir()
      .map_err(|error| format!("Failed to resolve app data directory: {error}"))?;
    fs::create_dir_all(&app_data_dir).map_err(|error| {
      format!(
        "Failed to create app data directory at {}: {error}",
        app_data_dir.display()
      )
    })?;

    let working_dir = app_data_dir.join("rag_storage");
    fs::create_dir_all(&working_dir).map_err(|error| {
      format!(
        "Failed to create working directory at {}: {error}",
        working_dir.display()
      )
    })?;

    let log_dir = app.path().app_log_dir().ok();
    if let Some(ref dir) = log_dir {
      fs::create_dir_all(dir).map_err(|error| {
        format!(
          "Failed to create log directory at {}: {error}",
          dir.display()
        )
      })?;
    }

    return Ok((working_dir, log_dir));
  }

  #[cfg(not(target_os = "macos"))]
  {
    let backend_path = backend_executable_path(app)?;
    let backend_dir = backend_path.parent().ok_or_else(|| {
      format!(
        "Backend executable path has no parent directory: {}",
        backend_path.display()
      )
    })?;
    Ok((backend_dir.to_path_buf(), None))
  }
}

fn spawn_backend(app: &AppHandle) -> Result<(), String> {
  let state = app.state::<DesktopState>();
  if state.backend_child.lock().unwrap().is_some() {
    return Ok(());
  }

  let backend_path = backend_executable_path(app)?;
  let backend_dir = backend_path.parent().ok_or_else(|| {
    format!(
      "Backend executable path has no parent directory: {}",
      backend_path.display()
    )
  })?;
  let (working_dir, log_dir) = resolve_backend_runtime_dirs(app)?;
  let mut command = Command::new(&backend_path);
  command
    .args(["--host", "127.0.0.1", "--port", "9621"])
    .current_dir(backend_dir)
    .env("WORKING_DIR", &working_dir)
    .stdin(Stdio::null())
    .stdout(Stdio::null())
    .stderr(Stdio::null());

  if let Some(log_dir) = log_dir {
    command.env("LOG_DIR", log_dir);
  }

  #[cfg(windows)]
  command.creation_flags(CREATE_NO_WINDOW);

  let child = command
    .spawn()
    .map_err(|error| format!("Failed to spawn backend executable at {}: {error}", backend_path.display()))?;

  *state.backend_child.lock().unwrap() = Some(child);

  Ok(())
}

fn ensure_backend(app: &AppHandle) -> Result<(), String> {
  match probe_backend() {
    BackendProbe::Ready => Ok(()),
    BackendProbe::Starting => wait_for_backend_ready(),
    BackendProbe::Unavailable => {
      spawn_backend(app)?;
      wait_for_backend_ready()
    }
    BackendProbe::ConflictingProcess(message) => Err(message),
  }
}

fn show_backend_startup_error(message: &str) {
  MessageDialog::new()
    .set_level(MessageLevel::Error)
    .set_title("Retriqs startup error")
    .set_description(message)
    .set_buttons(MessageButtons::Ok)
    .show();
}

fn show_main_window(app: &AppHandle) {
  if let Some(window) = app.get_webview_window("main") {
    let _ = window.show();
    let _ = window.unminimize();
    let _ = window.set_focus();
  }
}

fn hide_main_window(app: &AppHandle) {
  if let Some(window) = app.get_webview_window("main") {
    let _ = window.hide();
  }
}

fn build_tray(app: &AppHandle) -> tauri::Result<()> {
  let tray_menu = MenuBuilder::new(app)
    .text(MENU_OPEN, "Open")
    .text(MENU_RESTART_BACKEND, "Restart backend")
    .separator()
    .text(MENU_QUIT, "Quit")
    .build()?;

  let mut tray = TrayIconBuilder::with_id("main-tray")
    .menu(&tray_menu)
    .show_menu_on_left_click(true);

  if let Some(icon) = app.default_window_icon() {
    tray = tray.icon(icon.clone());
  }

  tray.build(app)?;
  Ok(())
}

pub fn run() {
  let builder = tauri::Builder::default()
    .invoke_handler(tauri::generate_handler![get_backend_runtime])
    .manage(DesktopState::default())
    .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
      show_main_window(app);
    }))
    .on_menu_event(|app, event| match event.id().0.as_str() {
      MENU_OPEN => show_main_window(app),
      MENU_RESTART_BACKEND => {
        terminate_managed_backend(app);
        if let Err(error) = ensure_backend(app) {
          show_backend_startup_error(&error);
          app.state::<DesktopState>().quitting.store(true, Ordering::SeqCst);
          app.exit(1);
          return;
        }
        show_main_window(app);
      }
      MENU_QUIT => {
        app.state::<DesktopState>().quitting.store(true, Ordering::SeqCst);
        app.exit(0);
      }
      _ => {}
    })
    .on_window_event(|window, event| {
      if let WindowEvent::CloseRequested { api, .. } = event {
        let quitting = window
          .app_handle()
          .state::<DesktopState>()
          .quitting
          .load(Ordering::SeqCst);

        if !quitting {
          api.prevent_close();
          let _ = window.hide();
        }
      }
    })
    .setup(|app| {
      app.handle().plugin(
        tauri_plugin_log::Builder::default()
          .level(if cfg!(debug_assertions) {
            log::LevelFilter::Info
          } else {
            log::LevelFilter::Warn
          })
          .build(),
      )?;

      build_tray(app.handle())?;
      hide_main_window(app.handle());

      let app_handle = app.handle().clone();
      thread::spawn(move || match ensure_backend(&app_handle) {
        Ok(()) => show_main_window(&app_handle),
        Err(error) => {
          show_backend_startup_error(&error);
          app_handle
            .state::<DesktopState>()
            .quitting
            .store(true, Ordering::SeqCst);
          app_handle.exit(1);
        }
      });

      Ok(())
    });

  builder
    .build(tauri::generate_context!())
    .expect("error while building tauri application")
    .run(|app, event| {
      if matches!(event, RunEvent::Exit { .. }) {
        terminate_managed_backend(app);
      }
    });
}
