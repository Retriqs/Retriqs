use std::{env, fs, path::PathBuf};

#[cfg(target_os = "windows")]
const BACKEND_EXECUTABLE_NAME: &str = "retriqs-backend.exe";
#[cfg(not(target_os = "windows"))]
const BACKEND_EXECUTABLE_NAME: &str = "retriqs-backend";

fn main() {
  let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());
  let backend_dir = manifest_dir.join("backend").join("retriqs-backend");
  let sidecar_path = backend_dir.join(BACKEND_EXECUTABLE_NAME);

  if !sidecar_path.exists() {
    fs::create_dir_all(&backend_dir).unwrap();
    fs::write(&sidecar_path, []).unwrap();
  }

  tauri_build::build()
}
