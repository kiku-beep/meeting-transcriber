use tauri::{AppHandle, Manager, State};

use crate::audio_sidecar::AudioSidecarManager;
use crate::sidecar::SidecarManager;

#[cfg(windows)]
use {
    std::sync::Mutex,
    windows::Win32::{
        Graphics::Gdi::{
            CreateBitmap, CreateDIBSection, DeleteObject, GetDC, ReleaseDC,
            BITMAPINFO, BITMAPINFOHEADER, BI_RGB, DIB_RGB_COLORS, HGDIOBJ,
        },
        UI::Shell::{ITaskbarList3, TaskbarList},
        UI::WindowsAndMessaging::{CreateIconIndirect, DestroyIcon, HICON, ICONINFO},
        System::Com::{CoCreateInstance, CoInitializeEx, CLSCTX_INPROC_SERVER, COINIT_APARTMENTTHREADED},
    },
};

#[cfg(windows)]
static OVERLAY_HICON: Mutex<Option<isize>> = Mutex::new(None);

#[tauri::command]
pub fn get_backend_url(sidecar: State<'_, SidecarManager>) -> String {
    sidecar.url()
}

#[tauri::command]
pub fn get_backend_status(sidecar: State<'_, SidecarManager>) -> bool {
    sidecar.is_healthy()
}

#[tauri::command]
pub fn start_backend(sidecar: State<'_, SidecarManager>) -> Result<String, String> {
    sidecar.start()?;
    Ok("Started".into())
}

#[tauri::command]
pub fn stop_backend(sidecar: State<'_, SidecarManager>) -> String {
    sidecar.stop();
    "Stopped".into()
}

#[tauri::command]
pub fn set_recording_icon(app: AppHandle, recording: bool) {
    #[cfg(windows)]
    {
        let Some(w) = app.get_webview_window("main") else { return };
        let hwnd = match w.hwnd() {
            Ok(h) => h,
            Err(_) => return,
        };

        unsafe {
            // Ensure COM is initialized on this thread (STA)
            let _ = CoInitializeEx(None, COINIT_APARTMENTTHREADED);

            // Create ITaskbarList3
            let taskbar: windows::core::Result<ITaskbarList3> =
                CoCreateInstance(&TaskbarList, None, CLSCTX_INPROC_SERVER);
            let Ok(taskbar) = taskbar else { return };
            let _ = taskbar.HrInit();

            if recording {
                // Build 32x32 red circle HICON for overlay
                let dst_w: usize = 32;
                let dst_h: usize = 32;
                let cx = dst_w as f32 / 2.0;
                let cy = dst_h as f32 / 2.0;
                let r = (dst_w as f32 / 2.0) - 1.5;
                let mut dst_bgra = vec![0u8; dst_w * dst_h * 4];
                for dy in 0..dst_h {
                    for dx in 0..dst_w {
                        let fx = dx as f32 + 0.5;
                        let fy = dy as f32 + 0.5;
                        let dist = ((fx - cx).powi(2) + (fy - cy).powi(2)).sqrt();
                        let di = (dy * dst_w + dx) * 4;
                        if dist <= r {
                            dst_bgra[di]     = 0x1a; // B
                            dst_bgra[di + 1] = 0x1a; // G
                            dst_bgra[di + 2] = 0xe0; // R (red)
                            dst_bgra[di + 3] = 0xff; // A
                        }
                    }
                }

                let hdc = GetDC(None);
                let bmi = BITMAPINFO {
                    bmiHeader: BITMAPINFOHEADER {
                        biSize: std::mem::size_of::<BITMAPINFOHEADER>() as u32,
                        biWidth: dst_w as i32,
                        biHeight: -(dst_h as i32),
                        biPlanes: 1,
                        biBitCount: 32,
                        biCompression: BI_RGB.0,
                        biSizeImage: 0,
                        biXPelsPerMeter: 0,
                        biYPelsPerMeter: 0,
                        biClrUsed: 0,
                        biClrImportant: 0,
                    },
                    bmiColors: [Default::default()],
                };
                let mut bits: *mut std::ffi::c_void = std::ptr::null_mut();
                let hbm_color = CreateDIBSection(Some(hdc), &bmi, DIB_RGB_COLORS, &mut bits, None, 0);
                ReleaseDC(None, hdc);
                let Ok(hbm_color) = hbm_color else { return };
                std::ptr::copy_nonoverlapping(dst_bgra.as_ptr(), bits as *mut u8, dst_bgra.len());

                let mask_size = ((dst_w + 15) / 16 * 2 * dst_h) as usize;
                let mask_bytes = vec![0u8; mask_size];
                let hbm_mask = CreateBitmap(dst_w as i32, dst_h as i32, 1, 1, Some(mask_bytes.as_ptr() as *const _));

                let ii = ICONINFO {
                    fIcon: windows::core::BOOL(1),
                    xHotspot: 0,
                    yHotspot: 0,
                    hbmMask: hbm_mask,
                    hbmColor: hbm_color,
                };
                let hicon = CreateIconIndirect(&ii);
                let _ = DeleteObject(HGDIOBJ(hbm_mask.0));
                let _ = DeleteObject(HGDIOBJ(hbm_color.0));
                let Ok(hicon) = hicon else { return };

                let _ = taskbar.SetOverlayIcon(hwnd, hicon, windows::core::w!("録音中"));

                // Store for later cleanup
                let mut prev = OVERLAY_HICON.lock().unwrap();
                if let Some(old) = prev.take() {
                    let _ = DestroyIcon(HICON(old as *mut _));
                }
                *prev = Some(hicon.0 as isize);
            } else {
                // Remove overlay
                let _ = taskbar.SetOverlayIcon(hwnd, HICON(std::ptr::null_mut()), windows::core::w!(""));

                let mut prev = OVERLAY_HICON.lock().unwrap();
                if let Some(old) = prev.take() {
                    let _ = DestroyIcon(HICON(old as *mut _));
                }
            }
        }
    }

    #[cfg(not(windows))]
    let _ = (app, recording);
}

// ── Audio sidecar commands (for remote server mode) ──────────────

#[tauri::command]
pub fn start_audio_sidecar(
    audio_sidecar: State<'_, AudioSidecarManager>,
    server_url: String,
    client_id: String,
    token: String,
    session_name: String,
    mic_index: Option<i32>,
    loopback_index: Option<i32>,
) -> Result<String, String> {
    audio_sidecar.start(
        &server_url,
        &client_id,
        &token,
        &session_name,
        mic_index,
        loopback_index,
    )?;
    Ok("Started".into())
}

#[tauri::command]
pub fn stop_audio_sidecar(audio_sidecar: State<'_, AudioSidecarManager>) -> String {
    audio_sidecar.stop();
    "Stopped".into()
}

#[tauri::command]
pub fn get_audio_sidecar_status(audio_sidecar: State<'_, AudioSidecarManager>) -> bool {
    audio_sidecar.is_running()
}
