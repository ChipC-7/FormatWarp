// 格式跃迁：Tauri 2 Rust 壳。
// 职责：
//   - 启动 Python FastAPI 后端（prod=打包 sidecar 二进制；dev=系统 python3 + uvicorn）；
//   - 解析后端 stdout 的 "FORMATWARP_PORT=xxxx" 写入全局状态，前端 invoke 读取；
//   - 退出时 kill 后端子进程，并用 pid 文件做孤儿进程兜底（启动时清理上次残留）。

use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use tauri::{Manager, RunEvent, State};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

const PID_FILE_NAME: &str = "formatwarp-backend.pid";

/// 后端进程状态：实际端口 + 子进程句柄 + pid 文件路径
pub struct BackendState {
    pub port: Arc<Mutex<u16>>,
    pub child: Mutex<Option<CommandChild>>,
    pub pid_file: PathBuf,
}

/// 后端端口查询命令（前端 invoke("get_backend_port") 读取）
#[tauri::command]
fn get_backend_port(state: State<'_, BackendState>) -> u16 {
    *state.port.lock().unwrap()
}

/// 从一行 stdout 解析 "FORMATWARP_PORT=xxxx"
fn parse_port(line: &str) -> Option<u16> {
    line.trim()
        .strip_prefix("FORMATWARP_PORT=")?
        .trim()
        .parse::<u16>()
        .ok()
}

/// 跨平台按 pid 杀进程（孤儿清理兜底）
fn kill_pid(pid: i32) {
    #[cfg(target_os = "windows")]
    {
        let _ = std::process::Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/F", "/T"])
            .status();
    }
    #[cfg(not(target_os = "windows"))]
    {
        let _ = std::process::Command::new("kill")
            .args(["-9", &pid.to_string()])
            .status();
    }
}

/// 清理上次残留的后端进程（pid 文件兜底）
fn cleanup_stale(pid_file: &PathBuf) {
    if let Ok(text) = std::fs::read_to_string(pid_file) {
        if let Ok(pid) = text.trim().parse::<i32>() {
            kill_pid(pid);
        }
    }
    let _ = std::fs::remove_file(pid_file);
}

/// 项目根目录（src-tauri 的上一级，dev 下 uvicorn 从这里跑，backend 包可导入）
fn project_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("CARGO_MANIFEST_DIR 无父目录") // frontend
        .parent()
        .expect("frontend 无父目录") // 项目根 FormatWarp
        .to_path_buf()
}

/// 判断是否 dev 模式：tauri dev 用 debug profile，tauri build 用 release。
/// 用编译期标志判定比检查 devUrl 更可靠（tauri.conf.json 中 devUrl 常驻）。
fn is_dev() -> bool {
    cfg!(debug_assertions)
}

/// 启动后端进程。
///  - prod：spawn sidecar 二进制，解析 stdout 中的 FORMATWARP_PORT；
///  - dev ：spawn 系统 python3 -m uvicorn（从项目根，固定 8765），便于后端热重载。
/// 返回子进程句柄；stdout/stderr 由后台线程持续排空（避免管道阻塞）。
fn spawn_backend(app: &tauri::App, port: Arc<Mutex<u16>>) -> Option<CommandChild> {
    if is_dev() {
        // dev：系统 python3（依赖本机环境；优点：改 backend/ 代码无需重新打包）
        let root = project_root();
        let cmd = app
            .shell()
            .command("python3")
            .args([
                "-m", "uvicorn", "backend.app:app",
                "--host", "127.0.0.1", "--port", "8765",
            ])
            .current_dir(root);
        match cmd.spawn() {
            Ok((mut rx, child)) => {
                // 持续排空 stdout/stderr，避免管道阻塞；异步 channel 用 try_recv 轮询
                std::thread::spawn(move || loop {
                    match rx.try_recv() {
                        Ok(CommandEvent::Stdout(line)) => {
                            eprintln!("[dev-backend] {}", String::from_utf8_lossy(&line).trim_end());
                        }
                        Ok(CommandEvent::Stderr(line)) => {
                            eprintln!("[dev-backend] {}", String::from_utf8_lossy(&line).trim_end());
                        }
                        Ok(CommandEvent::Terminated(_)) | Err(_) => break,
                        Ok(_) => {}
                    }
                    std::thread::sleep(std::time::Duration::from_millis(100));
                });
                Some(child)
            }
            Err(e) => {
                eprintln!("dev 后端启动失败（请确认 python3 / uvicorn 已安装）: {e}");
                None
            }
        }
    } else {
        // prod：sidecar 二进制（externalBin，文件名自动带 target triple）
        let sidecar = app.shell().sidecar("formatwarp-backend");
        match sidecar {
            Ok(cmd) => match cmd.spawn() {
                Ok((mut rx, child)) => {
                    // 持续解析 stdout 中的 FORMATWARP_PORT；stderr 透传；异步 channel 用 try_recv 轮询
                    std::thread::spawn(move || loop {
                        match rx.try_recv() {
                            Ok(CommandEvent::Stdout(line)) => {
                                let text = String::from_utf8_lossy(&line).to_string();
                                if let Some(p) = parse_port(&text) {
                                    *port.lock().unwrap() = p;
                                }
                            }
                            Ok(CommandEvent::Stderr(line)) => {
                                eprintln!("[backend] {}", String::from_utf8_lossy(&line).trim_end());
                            }
                            Ok(CommandEvent::Terminated(_)) | Err(_) => break,
                            Ok(_) => {}
                        }
                        std::thread::sleep(std::time::Duration::from_millis(100));
                    });
                    Some(child)
                }
                Err(e) => {
                    eprintln!("sidecar 启动失败: {e}");
                    None
                }
            },
            Err(e) => {
                eprintln!("sidecar 配置错误（请先运行 backend/build_sidecar.sh）: {e}");
                None
            }
        }
    }
}

/// 退出清理：kill 后端子进程 + 删除 pid 文件
fn cleanup(app_handle: &tauri::AppHandle) {
    if let Some(state) = app_handle.try_state::<BackendState>() {
        if let Some(child) = state.child.lock().unwrap().take() {
            let _ = child.kill();
        }
        let _ = std::fs::remove_file(&state.pid_file);
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            // 孤儿进程兜底：先清理上次残留，再记录本次 pid
            let pid_file = std::env::temp_dir().join(PID_FILE_NAME);
            cleanup_stale(&pid_file);

            let port = Arc::new(Mutex::new(8765u16));
            let child = spawn_backend(app, Arc::clone(&port));
            if let Some(c) = &child {
                let _ = std::fs::write(&pid_file, c.pid().to_string());
            }
            app.manage(BackendState {
                port,
                child: Mutex::new(child),
                pid_file,
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![get_backend_port])
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app_handle, event| {
        if let RunEvent::Exit = event {
            cleanup(app_handle);
        }
    });
}
