use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

use log::{error, info, warn};

#[cfg(target_os = "windows")]
const CREATE_NO_WINDOW: u32 = 0x08000000;

/// Manages the FastAPI backend sidecar process.
pub struct SidecarManager {
    child: Mutex<Option<Child>>,
    port: u16,
}

impl SidecarManager {
    pub fn new(port: u16) -> Self {
        Self {
            child: Mutex::new(None),
            port,
        }
    }

    pub fn url(&self) -> String {
        format!("http://127.0.0.1:{}", self.port)
    }

    /// Start the sidecar process.
    /// In dev mode (debug build), skip starting — assume backend is running manually.
    pub fn start(&self) -> Result<(), String> {
        if cfg!(debug_assertions) {
            info!("Dev mode: skipping sidecar start (start backend manually)");
            return Ok(());
        }

        let mut guard = self.child.lock().map_err(|e| e.to_string())?;
        if guard.is_some() {
            warn!("Sidecar already running");
            return Ok(());
        }

        // Find the sidecar binary relative to the app executable
        // Production layout:
        //   <install_dir>/Transcriber.exe
        //   <install_dir>/sidecar/transcriber-backend.exe
        //   <install_dir>/.env
        // Data: %APPDATA%/transcriber/ (light), <install_dir>/../transcriber-sessions/ (heavy)
        let exe_dir = std::env::current_exe()
            .map_err(|e| e.to_string())?
            .parent()
            .ok_or("Cannot find exe dir")?
            .to_path_buf();

        let sidecar_exe = exe_dir
            .join("sidecar")
            .join("transcriber-backend.exe");

        if !sidecar_exe.exists() {
            return Err(format!("Sidecar not found: {}", sidecar_exe.display()));
        }

        // Light data (dict, speakers, corrections) → %APPDATA%/transcriber
        let data_dir = std::env::var("APPDATA")
            .map(|appdata| std::path::PathBuf::from(appdata).join("transcriber"))
            .unwrap_or_else(|_| exe_dir.join("data"));
        std::fs::create_dir_all(&data_dir).ok();

        // Heavy data (sessions with audio/screenshots) → next to install dir (same drive)
        let sessions_dir = exe_dir
            .parent()
            .map(|p| p.join("transcriber-sessions"))
            .unwrap_or_else(|| data_dir.join("sessions"));
        std::fs::create_dir_all(&sessions_dir).ok();

        info!("Starting sidecar: {}", sidecar_exe.display());
        info!("Data directory: {}", data_dir.display());
        info!("Sessions directory: {}", sessions_dir.display());

        let mut cmd = Command::new(&sidecar_exe);
        cmd.arg("--port")
            .arg(self.port.to_string())
            .arg("--data-dir")
            .arg(data_dir.to_str().unwrap_or("data"))
            .arg("--sessions-dir")
            .arg(sessions_dir.to_str().unwrap_or(""))
            .arg("--legacy-data-dir")
            .arg(exe_dir.join("data").to_str().unwrap_or(""))
            .current_dir(&exe_dir)
            .stdout(Stdio::null())
            .stderr(Stdio::null());

        #[cfg(target_os = "windows")]
        cmd.creation_flags(CREATE_NO_WINDOW);

        let child = cmd.spawn()
            .map_err(|e| format!("Failed to start sidecar: {}", e))?;

        *guard = Some(child);
        info!("Sidecar started (port {})", self.port);
        Ok(())
    }

    /// Stop the sidecar process.
    pub fn stop(&self) {
        if cfg!(debug_assertions) {
            info!("Dev mode: skipping sidecar stop");
            return;
        }

        let mut guard = match self.child.lock() {
            Ok(g) => g,
            Err(e) => {
                error!("Failed to lock sidecar: {}", e);
                return;
            }
        };

        if let Some(mut child) = guard.take() {
            info!("Stopping sidecar...");
            let _ = child.kill();
            let _ = child.wait();
            info!("Sidecar stopped");
        }
    }

    /// Check if the backend is healthy by polling /api/health.
    pub fn is_healthy(&self) -> bool {
        // Simple blocking HTTP check using std::net (no extra dependencies)
        use std::io::{Read, Write};
        use std::net::TcpStream;

        let addr = format!("127.0.0.1:{}", self.port);
        let stream = match TcpStream::connect_timeout(
            &addr.parse().unwrap(),
            Duration::from_secs(2),
        ) {
            Ok(s) => s,
            Err(_) => return false,
        };

        let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
        let _ = stream.set_write_timeout(Some(Duration::from_secs(2)));

        let request = format!(
            "GET /api/health HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nConnection: close\r\n\r\n",
            self.port
        );

        let mut stream = stream;
        if stream.write_all(request.as_bytes()).is_err() {
            return false;
        }

        let mut response = String::new();
        if stream.read_to_string(&mut response).is_err() {
            return false;
        }

        response.contains("200 OK") && response.contains("\"ok\"")
    }
}

impl Drop for SidecarManager {
    fn drop(&mut self) {
        self.stop();
    }
}
