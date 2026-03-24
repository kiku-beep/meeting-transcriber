mod commands;
mod sidecar;

use tauri::Manager;

use crate::sidecar::SidecarManager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    #[cfg(debug_assertions)]
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();

    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            // When a second instance is launched, show the existing window
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.show();
                let _ = w.set_focus();
            }
        }))
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_http::init())
        .plugin(tauri_plugin_notification::init())
        .manage(SidecarManager::new(8000))
        .invoke_handler(tauri::generate_handler![
            commands::get_backend_url,
            commands::get_backend_status,
            commands::start_backend,
            commands::stop_backend,
            commands::set_recording_icon,
        ])
        .setup(|app| {
            // Start sidecar (skipped in dev mode)
            let sidecar = app.handle().state::<SidecarManager>();
            if let Err(e) = sidecar.start() {
                log::error!("Failed to start sidecar: {}", e);
            }

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
