use std::{env, fs, path::PathBuf};

fn main() {
  let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());
  let backend_dir = manifest_dir.join("backend").join("retriqs-backend");
  let sidecar_path = backend_dir.join("retriqs-backend.exe");

  if !sidecar_path.exists() {
    fs::create_dir_all(&backend_dir).unwrap();
    fs::write(&sidecar_path, []).unwrap();
  }

  tauri_build::build()
}
