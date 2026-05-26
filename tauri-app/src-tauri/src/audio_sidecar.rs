use std::io::{BufRead, BufReader, Write};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use log::{error, info, warn};

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

#[cfg(target_os = "windows")]
const CREATE_NO_WINDOW: u32 = 0x08000000;

/// Manages the audio capture sidecar process.
/// This process captures local audio (mic + WASAPI loopback) and streams it
/// to the remote transcription server via WebSocket.
pub struct AudioSidecarManager {
    child: Mutex<Option<Child>>,
}

impl AudioSidecarManager {
    pub fn new() -> Self {
        Self {
            child: Mutex::new(None),
        }
    }

    /// Start the audio sidecar with the given server URL and client ID.
    pub fn start(
        &self,
        server_url: &str,
        client_id: &str,
        token: &str,
        session_name: &str,
        mic_index: Option<i32>,
        loopback_index: Option<i32>,
    ) -> Result<(), String> {
        let mut guard = self.child.lock().map_err(|e| e.to_string())?;
        if guard.is_some() {
            warn!("Audio sidecar already running");
            return Ok(());
        }

        // Convert http:// URL to ws://
        let ws_url = server_url
            .replace("http://", "ws://")
            .replace("https://", "wss://");

        // Find the audio sidecar binary or Python script.
        let exe_dir = std::env::current_exe()
            .map_err(|e| e.to_string())?
            .parent()
            .ok_or("Cannot find exe dir")?
            .to_path_buf();

        let sidecar_name = if cfg!(target_os = "windows") {
            "audio_sidecar.exe"
        } else {
            "audio_sidecar"
        };
        let sidecar_exe = exe_dir.join("sidecar").join(sidecar_name);

        let mut cmd = if sidecar_exe.exists() {
            let mut c = Command::new(&sidecar_exe);
            c.args(["--server", &ws_url, "--client-id", client_id]);
            c
        } else if let Some(script) = resolve_python_sidecar_script(&exe_dir) {
            let mut c = Command::new(python_command_for_script(&script));
            c.args([
                script.to_string_lossy().as_ref(),
                "--server",
                &ws_url,
                "--client-id",
                client_id,
            ]);
            c
        } else {
            return Err(format!(
                "Audio sidecar not found: {} or audio_sidecar/main.py",
                sidecar_exe.display()
            ));
        };

        if !token.is_empty() {
            cmd.args(["--token", token]);
        }
        if !session_name.is_empty() {
            cmd.args(["--session-name", session_name]);
        }
        if let Some(idx) = mic_index {
            cmd.args(["--mic", &idx.to_string()]);
        }
        if let Some(idx) = loopback_index {
            cmd.args(["--loopback", &idx.to_string()]);
        }

        cmd.stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped());

        #[cfg(target_os = "windows")]
        cmd.creation_flags(CREATE_NO_WINDOW);

        if !sidecar_exe.exists() {
            let resolved = resolve_python_sidecar_script(&exe_dir);
            info!("Audio sidecar exe_dir: {}", exe_dir.display());
            info!("Audio sidecar resolved script: {:?}", resolved);
        }

        info!("Starting audio sidecar: server={}, client={}", ws_url, client_id);

        let mut child = cmd.spawn()
            .map_err(|e| format!("Failed to start audio sidecar: {}", e))?;

        // Spawn thread to capture stderr and log it
        if let Some(stderr) = child.stderr.take() {
            thread::spawn(move || {
                let reader = BufReader::new(stderr);
                for line in reader.lines() {
                    match line {
                        Ok(l) => error!("audio_sidecar STDERR: {}", l),
                        Err(_) => break,
                    }
                }
            });
        }

        // Wait for SIDECAR_READY signal (with timeout via limited reads)
        let mut ready = false;
        if let Some(stdout) = child.stdout.take() {
            let reader = BufReader::new(stdout);
            for line in reader.lines().take(10) {
                match line {
                    Ok(l) if l.contains("SIDECAR_READY") => {
                        info!("Audio sidecar ready");
                        ready = true;
                        break;
                    }
                    Ok(l) => info!("audio_sidecar STDOUT: {}", l),
                    Err(e) => {
                        error!("audio_sidecar stdout read error: {}", e);
                        break;
                    }
                }
            }
        }

        // Check if process already exited
        match child.try_wait() {
            Ok(Some(exit)) => {
                return Err(format!("Audio sidecar exited immediately with: {}", exit));
            }
            Ok(None) => { /* still running, good */ }
            Err(e) => {
                return Err(format!("Failed to check sidecar status: {}", e));
            }
        }

        if !ready {
            warn!("Audio sidecar started but SIDECAR_READY not received");
        }

        *guard = Some(child);
        info!("Audio sidecar started successfully");
        Ok(())
    }

    /// Stop the audio sidecar.
    pub fn stop(&self) {
        let mut guard = match self.child.lock() {
            Ok(g) => g,
            Err(e) => {
                error!("Failed to lock audio sidecar: {}", e);
                return;
            }
        };

        if let Some(mut child) = guard.take() {
            info!("Stopping audio sidecar...");
            if let Some(stdin) = child.stdin.as_mut() {
                let _ = stdin.write_all(b"stop\n");
                let _ = stdin.flush();
            }

            for _ in 0..50 {
                match child.try_wait() {
                    Ok(Some(_)) => {
                        info!("Audio sidecar stopped gracefully");
                        return;
                    }
                    Ok(None) => thread::sleep(Duration::from_millis(100)),
                    Err(e) => {
                        error!("Failed to poll audio sidecar shutdown: {}", e);
                        break;
                    }
                }
            }

            warn!("Audio sidecar did not stop in time; killing process");
            let _ = child.kill();
            let _ = child.wait();
            info!("Audio sidecar stopped");
        }
    }

    pub fn is_running(&self) -> bool {
        let mut guard = match self.child.lock() {
            Ok(g) => g,
            Err(_) => return false,
        };
        if let Some(child) = guard.as_mut() {
            match child.try_wait() {
                Ok(Some(_)) => {
                    *guard = None;
                    false
                }
                Ok(None) => true,
                Err(_) => false,
            }
        } else {
            false
        }
    }
}

fn python_command_for_script(script: &std::path::Path) -> std::path::PathBuf {
    if let Some(sidecar_dir) = script.parent() {
        let venv_python = if cfg!(target_os = "windows") {
            sidecar_dir.join(".venv").join("Scripts").join("python.exe")
        } else {
            sidecar_dir.join(".venv").join("bin").join("python")
        };
        if venv_python.exists() {
            return venv_python;
        }
    }

    if cfg!(target_os = "windows") {
        std::path::PathBuf::from("python")
    } else {
        std::path::PathBuf::from("python3")
    }
}

fn resolve_python_sidecar_script(exe_dir: &std::path::Path) -> Option<std::path::PathBuf> {
    if let Ok(path) = std::env::var("AUDIO_SIDECAR_SCRIPT") {
        let path = std::path::PathBuf::from(path);
        if path.exists() {
            return Some(path);
        }
    }

    let mut candidates = Vec::new();

    // Dev mode: tauri-app/src-tauri/target/debug/<app>
    if let Some(path) = exe_dir
        .parent()
        .and_then(|p| p.parent())
        .and_then(|p| p.parent())
        .and_then(|p| p.parent())
        .map(|p| p.join("audio_sidecar").join("main.py"))
    {
        candidates.push(path);
    }

    // Release bundles built from this source tree can still use the prepared
    // local venv, which keeps Mac client builds usable without system packages.
    if let Some(manifest_dir) = option_env!("CARGO_MANIFEST_DIR") {
        candidates.push(
            std::path::PathBuf::from(manifest_dir)
                .join("..")
                .join("..")
                .join("audio_sidecar")
                .join("main.py"),
        );
    }

    // Bundled resource variants.
    candidates.push(exe_dir.join("audio_sidecar").join("main.py"));
    candidates.push(exe_dir.join("resources").join("audio_sidecar").join("main.py"));
    if let Some(path) = exe_dir
        .parent()
        .map(|p| p.join("Resources").join("audio_sidecar").join("main.py"))
    {
        candidates.push(path);
    }

    candidates.into_iter().find(|path| path.exists())
}

impl Drop for AudioSidecarManager {
    fn drop(&mut self) {
        self.stop();
    }
}
