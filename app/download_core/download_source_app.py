import os
import shutil
import sys
import subprocess
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QProgressBar, QPushButton, QMessageBox, QComboBox, QHBoxLayout, QFrame, QCheckBox
from PySide6.QtCore import QThread, Signal, Qt

# =====================================================================
# CẤU HÌNH ĐƯỜNG DẪN BẤT BIẾN - ÉP LƯU "CÙNG CẤP" VỚI THƯ MỤC APP
# =====================================================================
if getattr(sys, 'frozen', False):
    APP_ROOT = os.path.dirname(sys.executable)
else:
    current_file_path = os.path.abspath(__file__)
    current_dir = os.path.dirname(current_file_path)
    if os.path.basename(current_dir) == "ui" or os.path.basename(current_dir) == "control":
        APP_ROOT = os.path.dirname(os.path.dirname(current_dir))
    else:
        APP_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(current_file_path)))

PORTABLE_LIBS_DIR = os.path.join(APP_ROOT, "app_resources", "libs")
MODEL_BASE_DIR = os.path.join(APP_ROOT, "app_resources", "whisper_models")
TRANS_MODEL_DIR = os.path.join(APP_ROOT, "app_resources", "translation_models") # Thư mục dịch thuật local

MAJOR_PACKAGES = ["torch", "torchvision", "torchaudio", "faster-whisper", "transformers", "ctranslate2", "soundfile", "numpy", "huggingface_hub"]

# ==========================================================
# RESOURCE STATUS
# ==========================================================

def _set_resource_ready_flag(value: bool):
    try:
        from PySide6.QtCore import QSettings
        settings = QSettings("MyStudio", "AI_Music_Player")
        settings.setValue("ai_resources_ready", "1" if value else "0")
    except Exception:
        pass


def _get_resource_ready_flag() -> bool:
    try:
        from PySide6.QtCore import QSettings
        settings = QSettings("MyStudio", "AI_Music_Player")
        return settings.value("ai_resources_ready", "0") == "1"
    except Exception:
        return False


def check_resource_status():
    status = {}

    # Core AI
    status["core"] = (
        os.path.isdir(PORTABLE_LIBS_DIR)
        and os.path.isdir(os.path.join(PORTABLE_LIBS_DIR, "torch"))
        and os.path.isdir(os.path.join(PORTABLE_LIBS_DIR, "transformers"))
        and os.path.isdir(os.path.join(PORTABLE_LIBS_DIR, "faster_whisper"))
    )

    # Whisper models
    whisper = {}

    for model in [
        "tiny",
        "base",
        "small",
        "medium",
        "large-v2",
        "large-v3"
    ]:
        path = os.path.join(MODEL_BASE_DIR, model)

        whisper[model] = (
            os.path.isdir(path)
            and len(os.listdir(path)) > 2
        )

    status["whisper"] = whisper

    # Translation model
    trans = os.path.join(
        TRANS_MODEL_DIR,
        "nllb-200"
    )

    status["translation"] = (
        os.path.isdir(trans)
        and len(os.listdir(trans)) > 2
    )

    status["ready"] = (
        status.get("core", False)
        and any(status.get("whisper", {}).values())
    )

    return status

# =====================================================================
# LUỒNG TẢI TỰ ĐỘNG - TÍCH HỢP KÉP CẢ CPU VÀ GPU TRỌN GÓI
# =====================================================================
class PipDownloadWorker(QThread):
    status_signal = Signal(str)
    progress_text_signal = Signal(str) 
    progress_value_signal = Signal(int) 
    finished_signal = Signal(bool, str)

    def __init__(self, hardware_mode, model_name, skip_pip=False, force_clean=False, download_trans=False):
        super().__init__()
        self.hardware_mode = hardware_mode  
        self.model_name = model_name        
        self.skip_pip = skip_pip
        self.force_clean = force_clean 
        self.download_trans = download_trans # Trạng thái tải thêm NLLB

    def run(self):
        try:
            os.environ["HF_HUB_OFFLINE"] = "0"
            os.environ["TRANSFORMERS_OFFLINE"] = "0"

            # --- CƠ CHẾ GIẢI PHÓNG THƯ MỤC LỖI CŨ ---
            if self.force_clean:
                self.status_signal.emit("🧹 Đang giải phóng hoàn toàn bộ cài cũ...")
                self.progress_value_signal.emit(2)
                if os.path.exists(PORTABLE_LIBS_DIR):
                    import random
                    def win_safe_delete(target_dir):
                        for root, dirs, files in os.walk(target_dir, topdown=False):
                            for name in files:
                                file_path = os.path.join(root, name)
                                try: os.remove(file_path)
                                except Exception:
                                    try: os.rename(file_path, file_path + f".{random.randint(1000,9999)}.bak")
                                    except Exception: pass
                            for name in dirs:
                                dir_path = os.path.join(root, name)
                                try: os.rmdir(dir_path)
                                except Exception: pass
                    try: shutil.rmtree(PORTABLE_LIBS_DIR)
                    except Exception: win_safe_delete(PORTABLE_LIBS_DIR)
                self.skip_pip = False 
            
            os.makedirs(PORTABLE_LIBS_DIR, exist_ok=True)
            if PORTABLE_LIBS_DIR not in sys.path:
                sys.path.insert(0, PORTABLE_LIBS_DIR)

            # ---------------------------------------------------------
            # BƯỚC 1: TỰ ĐỘNG CÀI ĐẶT THƯ VIỆN NỀN (CÓ LOG DEBUG RA FILE)
            # ---------------------------------------------------------
            if self.skip_pip:
                self.status_signal.emit("⚡ Toàn bộ lõi AI đã đầy đủ! Đang kiểm tra cấu hình nâng cao...")
                self.progress_value_signal.emit(50 if self.download_trans else 70)
                self.msleep(400) 
            else:
                current_pct = 5
                self.progress_value_signal.emit(current_pct)
                self.status_signal.emit("🚀 Bước 1/4: Đang cài đặt hệ sinh thái AI (Hỗ trợ cả CPU & GPU)...")

                # Định vị Python EXE an toàn
                if getattr(sys, 'frozen', False):
                    python_exe = shutil.which("python")
                    if python_exe is None:
                        self.finished_signal.emit(False, "Không tìm thấy Python trên máy để cài AI runtime.")
                        return
                else:
                    python_exe = sys.executable

                cmd = [
                    python_exe, "-m", "pip", "install", 
                    "--target", PORTABLE_LIBS_DIR,
                    "--no-cache-dir",
                    "--progress-bar", "off", 
                    "--trusted-host", "pypi.org",
                    "--trusted-host", "files.pythonhosted.org",
                    "--trusted-host", "download.pytorch.org",
                    "torch==2.4.0", "torchvision==0.19.0", "torchaudio==2.4.0",
                    "huggingface_hub>=0.19.0",
                    "faster-whisper==1.0.2", 
                    "transformers>=4.35.2",
                    "ctranslate2>=4.0.0",
                    "soundfile>=0.12.1",
                    "numpy<2.0.0",
                    "--extra-index-url", "https://download.pytorch.org/whl/cu121"
                ]

                startupinfo = None
                if sys.platform == "win32":
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = subprocess.SW_HIDE

                # 🎯 ĐƯỜNG DẪN FILE LOG DEBUG: Lưu ngay tại thư mục app_resources
                log_file_path = os.path.join(APP_ROOT, "app_resources", "pip_install_debug.log")
                os.makedirs(os.path.dirname(log_file_path), exist_ok=True)

                # Mở tiến trình với cấu hình gộp stderr vào stdout
                process = subprocess.Popen(
                    cmd, 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.STDOUT, 
                    text=True, 
                    startupinfo=startupinfo, 
                    bufsize=1
                )

                detected_packages = set()

                # 🎯 MỞ FILE GI GHI LOG THỜI GIAN THỰC (Dùng encoding='utf-8' chuẩn chỉnh)
                with open(log_file_path, "w", encoding="utf-8") as log_file:
                    log_file.write("=== BOTUBE PIP INSTALLATION DEBUG LOG ===\n")
                    log_file.write(f"Command executed: {' '.join(cmd)}\n\n")
                    log_file.flush()

                    # Đọc luồng output liên tục từ pip
                    for line in process.stdout:
                        clean_line = line.strip()
                        if not clean_line:
                            continue
                        
                        # 1. Ghi ngay dòng log này vào file .log để debug sau này
                        log_file.write(line)
                        log_file.flush() # Ép dữ liệu ghi xuống ổ cứng lập tức, treo vẫn xem được log

                        # 2. Xử lý hiển thị lên giao diện cho người dùng đỡ sốt ruột
                        if "Downloading" in clean_line:
                            parts = clean_line.split("/")
                            file_name = parts[-1] if parts else clean_line
                            file_name = file_name.split(" ")[0]
                            self.progress_text_signal.emit(f"📥 Đang tải: {file_name[:55]}")
                            
                            for pkg in MAJOR_PACKAGES:
                                if pkg in clean_line.lower() and pkg not in detected_packages:
                                    detected_packages.add(pkg)
                                    max_pip_pct = 45 if self.download_trans else 65
                                    current_pct = min(current_pct + 5, max_pip_pct)
                                    self.progress_value_signal.emit(current_pct)
                                    break
                                    
                        elif "Installing collected packages" in clean_line:
                            self.progress_text_signal.emit("⚙️ Pip đang cấu trúc và tối ưu hóa các gói...")
                            self.progress_value_signal.emit(48 if self.download_trans else 68)

                # Chờ tiến trình kết thúc sạch sẽ
                return_code = process.wait()
                
                if return_code != 0:
                    self.finished_signal.emit(
                        False, 
                        f"[Pip Error Code {return_code}]: Tiến trình cài đặt bị lỗi.\n"
                        f"Chi tiết xem tại file: app_resources/pip_install_debug.log"
                    )
                    return
            # ---------------------------------------------------------
            # BƯỚC 2: TỰ ĐỘNG VÁ LỖI CUDA DLL CHO GPU
            # ---------------------------------------------------------
            '''
            self.status_signal.emit("🛠️ Bước 2/4: Đang tự động liên kết các tệp lõi CUDA rời...")
            self.progress_value_signal.emit(55 if self.download_trans else 75)
            
            torch_lib_dir = os.path.join(PORTABLE_LIBS_DIR, "torch", "lib")
            ctranslate2_dir = os.path.join(PORTABLE_LIBS_DIR, "ctranslate2")
            
            if os.path.exists(torch_lib_dir) and os.path.exists(ctranslate2_dir):
                cuda_dlls = ["cublas", "cudnn", "cufft", "cublaslt"]
                try:
                    for file_name in os.listdir(torch_lib_dir):
                        if any(dll in file_name.lower() for dll in cuda_dlls) and file_name.lower().endswith(".dll"):
                            src_file = os.path.join(torch_lib_dir, file_name)
                            dst_file = os.path.join(ctranslate2_dir, file_name)
                            if not os.path.exists(dst_file):
                                self.progress_text_signal.emit(f"⚡ Đang liên kết: {file_name}")
                                shutil.copy2(src_file, dst_file)
                    self.progress_text_signal.emit("✅ Liên kết hạ tầng CUDA thành công!")
                    self.msleep(400)
                except Exception as copy_err:
                    print(f"⚠️ Cảnh báo lỗi sao chép DLL: {copy_err}")
            '''
            # ---------------------------------------------------------
            # BƯỚC 3: TẢI MODEL WHISPER AI TỪ HUGGINGFACE
            # ---------------------------------------------------------
            self.status_signal.emit(f"🧠 Bước 3/4: Đang đồng bộ hóa Model AI [{self.model_name.upper()}]...")
            self.progress_text_signal.emit("🔗 Đang mở cổng kết nối tới HuggingFace...")
            self.progress_value_signal.emit(65 if self.download_trans else 82)
            
            os.makedirs(MODEL_BASE_DIR, exist_ok=True)
            
            from huggingface_hub import snapshot_download
            self.progress_text_signal.emit(f"📥 Đang tải các file Core của Model {self.model_name.upper()}...")
            
            snapshot_download(
                repo_id=f"Systran/faster-whisper-{self.model_name}",
                local_dir=os.path.join(MODEL_BASE_DIR, self.model_name),
                local_dir_use_symlinks=False
            )

            # ---------------------------------------------------------
            # BƯỚC 4: TẢI THÊM MODEL DỊCH THUẬT NLLB LOCAL (NẾU ĐƯỢC CHỌN)
            # ---------------------------------------------------------
            if self.download_trans:
                self.status_signal.emit("🌍 Bước 4/4: Đang tải Model dịch thuật NLLB Offline...")
                self.progress_text_signal.emit("📥 Đang kéo cấu hình Tokenizer & Weights từ Facebook...")
                self.progress_value_signal.emit(85)
                
                nllb_target_path = os.path.join(TRANS_MODEL_DIR, "nllb-200")
                os.makedirs(nllb_target_path, exist_ok=True)
                
                snapshot_download(
                    repo_id="facebook/nllb-200-distilled-600M",
                    local_dir=nllb_target_path,
                    local_dir_use_symlinks=False
                )
                self.progress_text_signal.emit("✅ Đồng bộ kho dịch thuật Offline thành công!")
                self.msleep(300)

            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"

            self.progress_value_signal.emit(100)
            _set_resource_ready_flag(True)
            try:
                from control.ai_controller import _set_resource_cache_state
                _set_resource_cache_state(True, True)
            except Exception:
                pass
            self.finished_signal.emit(True, "")

        except Exception as e:
            import traceback
            tb_str = traceback.format_exc()
            _set_resource_ready_flag(False)
            try:
                from control.ai_controller import _set_resource_cache_state
                _set_resource_cache_state(False, False)
            except Exception:
                pass
            self.finished_signal.emit(False, f"[System Exception]:\n{tb_str[:500]}")


# =====================================================================
# GIAO DIỆN FORM CHUẨN ĐÓNG GÓI PORTABLE
# =====================================================================
class ResourceDownloadDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        self.apply_stylesheets()
        
    def init_ui(self):
        self.setWindowTitle("Trình cài đặt Core AI tự động")
        self.setFixedSize(580, 440) # Mở rộng nhẹ chiều cao để tối ưu giao diện
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint & ~Qt.WindowCloseButtonHint)

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(25, 25, 25, 25)
        main_layout.setSpacing(15)
        
        self.lbl_title = QLabel("CẤU HÌNH HỆ SINH THÁI CORE AI")
        self.lbl_title.setObjectName("HeaderTitle")
        main_layout.addWidget(self.lbl_title)
        
        self.lbl_status = QLabel("Ứng dụng tự động thiết lập bộ thư viện dùng chung cho cả CPU & GPU. Vui lòng chọn phiên bản Model:")
        self.lbl_status.setObjectName("StatusLabel")
        self.lbl_status.setWordWrap(True)
        main_layout.addWidget(self.lbl_status)
        
        form_frame = QFrame()
        form_frame.setObjectName("FormContainer")
        form_layout = QVBoxLayout(form_frame)
        form_layout.setContentsMargins(20, 18, 20, 18)
        form_layout.setSpacing(16)

        layout_hw = QHBoxLayout()
        lbl_hw = QLabel("Chế độ kiểm thử:")
        lbl_hw.setObjectName("FormLabel")
        lbl_hw.setFixedWidth(110)
        self.cbo_hardware = QComboBox()
        self.cbo_hardware.addItem("Cài đặt bộ thư viện lai (Hỗ trợ cả CPU & GPU NVidia)", "gpu")
        layout_hw.addWidget(lbl_hw)
        layout_hw.addWidget(self.cbo_hardware)
        form_layout.addLayout(layout_hw)
        
        layout_model = QHBoxLayout()
        lbl_model = QLabel("Phiên bản Model:")
        lbl_model.setObjectName("FormLabel")
        lbl_model.setFixedWidth(110)
        self.cbo_model = QComboBox()
        self.cbo_model.addItem("Bản Siêu Nhẹ (Tiny ~75MB)", "tiny")
        self.cbo_model.addItem("Bản Tiêu Chuẩn (Base ~140MB - Khuyên dùng)", "base")
        self.cbo_model.addItem("Bản Phổ Thông (Small ~460MB)", "small")
        self.cbo_model.addItem("Bản Trung Cấp (Medium ~1.5GB)", "medium")
        self.cbo_model.addItem("Bản Cao Cấp V2 (Large-v2 ~3GB)", "large-v2")
        self.cbo_model.addItem("Bản Cao Cấp V3 (Large-v3 ~3GB)", "large-v3")
        self.cbo_model.currentIndexChanged.connect(
            self.refresh_resource_status
        )
        layout_model.addWidget(lbl_model)
        layout_model.addWidget(self.cbo_model)
        form_layout.addLayout(layout_model)
        
        self.lbl_resource_status = QLabel("")
        self.lbl_resource_status.setObjectName("StatusInfo")

        form_layout.addWidget(self.lbl_resource_status)

        main_layout.addWidget(form_frame)

        # --- KHU VỰC CÁC CHỌN LỰA CHECKBOX NÂNG CAO ---
        options_layout = QVBoxLayout()
        options_layout.setSpacing(8)

        self.chk_download_trans = QCheckBox("Tải kèm Model dịch thuật NLLB Offline (Facebook ~1.2GB để dịch không cần mạng)")
        self.chk_download_trans.setObjectName("TransCheckbox")
        options_layout.addWidget(self.chk_download_trans)

        self.chk_force_clean = QCheckBox("Xóa sạch tài nguyên cũ cài lại từ đầu (Khuyên dùng nếu đã dính lỗi mạng cũ)")
        self.chk_force_clean.setObjectName("CleanCheckbox")
        options_layout.addWidget(self.chk_force_clean)
        
        main_layout.addLayout(options_layout)
        
        self.lbl_detail_status = QLabel("")
        self.lbl_detail_status.setObjectName("DetailStatusLabel")
        self.lbl_detail_status.hide()
        main_layout.addWidget(self.lbl_detail_status)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100) 
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(18)
        self.progress_bar.setAlignment(Qt.AlignCenter)
        self.progress_bar.hide() 
        main_layout.addWidget(self.progress_bar)
        
        self.btn_start = QPushButton("Bắt đầu cài đặt tự động")
        self.btn_start.setObjectName("PrimaryButton")
        self.btn_start.setFixedHeight(45)
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.clicked.connect(self.start_download)
        main_layout.addWidget(self.btn_start)
        
        self.setLayout(main_layout)
        self.refresh_resource_status()

    def apply_stylesheets(self):
        style = """
            QDialog { background-color: #111112; }
            QLabel#HeaderTitle { color: #3ea6ff; font-size: 16px; font-weight: bold; letter-spacing: 1px; }
            QLabel#StatusLabel { color: #aaaaaa; font-size: 13px; }
            QLabel#FormLabel { color: #ffffff; font-weight: 500; }
            QLabel#DetailStatusLabel { color: #3ea6ff; font-size: 12px; font-style: italic; }
            QFrame#FormContainer { background-color: #18181c; border: 1px solid #282830; border-radius: 10px; }
            QComboBox { background-color: #222226; border: 1px solid #363642; border-radius: 6px; padding: 6px 30px 6px 12px; color: #ffffff; font-size: 13px; }
            QComboBox:hover { border: 1px solid #4a4a5a; background-color: #27272c; }
            QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 25px; border-left: none; }
            QComboBox::down-arrow { border: 4px solid transparent; border-top-color: #bbbbbb; margin-top: 4px; }
            QProgressBar { border: none; background-color: #18181c; border-radius: 9px; color: #ffffff; font-weight: bold; font-size: 11px; }
            QProgressBar::chunk { background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1c62b9, stop:1 #3ea6ff); border-radius: 9px; }
            QCheckBox#CleanCheckbox { color: #ff6b6b; font-size: 12px; font-weight: 500; padding-left: 2px; }
            QCheckBox#CleanCheckbox:hover { color: #ff8787; }
            QCheckBox#TransCheckbox { color: #2ba640; font-size: 12px; font-weight: 500; padding-left: 2px; }
            QCheckBox#TransCheckbox:hover { color: #3cd058; }
            QPushButton#PrimaryButton { background-color: #3ea6ff; color: #000000; font-weight: bold; font-size: 14px; border: none; border-radius: 8px; }
            QPushButton#PrimaryButton:hover { background-color: #65b8ff; }
            QPushButton#PrimaryButton:pressed { background-color: #1c62b9; color: #ffffff; }
            QPushButton#PrimaryButton:disabled { background-color: #222226; color: #666666; }
        """
        self.setStyleSheet(style)

    def is_pip_installed_correctly(self):
        if not os.path.exists(PORTABLE_LIBS_DIR):
            return False
        existing_dirs = os.listdir(PORTABLE_LIBS_DIR)
        dir_string = "".join(existing_dirs).lower()
        return "faster_whisper" in dir_string and "torch" in dir_string and "transformers" in dir_string

    def start_download(self):
        hardware_mode = self.cbo_hardware.currentData()
        model_name = self.cbo_model.currentData()
        force_clean = self.chk_force_clean.isChecked()
        download_trans = self.chk_download_trans.isChecked()
        
        specific_model_path = os.path.join(MODEL_BASE_DIR, model_name)
        skip_pip_step = self.is_pip_installed_correctly()
        
        if not force_clean and os.path.exists(specific_model_path) and len(os.listdir(specific_model_path)) > 2:
            reply = QMessageBox.question(
                self, "Xác nhận tải lại", 
                f"Hệ thống phát hiện Model [{model_name.upper()}] đã được tải hoàn chỉnh trước đó.\n\nBạn có muốn tải lại không?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.No:
                if PORTABLE_LIBS_DIR not in sys.path:
                    sys.path.insert(0, PORTABLE_LIBS_DIR)
                try:
                    from control.ai_controller import _set_resource_cache_state
                    _set_resource_cache_state(True, True)
                except Exception:
                    pass
                self.accept()
                return

        self.btn_start.setEnabled(False)
        self.cbo_hardware.setEnabled(False)
        self.cbo_model.setEnabled(False)
        self.chk_force_clean.setEnabled(False)
        self.chk_download_trans.setEnabled(False)
        
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.lbl_detail_status.show()
        self.lbl_detail_status.setText("⚙️ Đang phân tích hạ tầng hệ thống...")
        
        self.worker = PipDownloadWorker(hardware_mode, model_name, skip_pip=skip_pip_step, force_clean=force_clean, download_trans=download_trans)
        self.worker.status_signal.connect(self.lbl_status.setText)
        self.worker.progress_text_signal.connect(self.lbl_detail_status.setText) 
        self.worker.progress_value_signal.connect(self.progress_bar.setValue) 
        self.worker.finished_signal.connect(self.download_finished)
        self.worker.start()

    def download_finished(self, success, error_msg):
        self.btn_start.setEnabled(True)
        self.cbo_hardware.setEnabled(True)
        self.cbo_model.setEnabled(True)
        self.chk_force_clean.setEnabled(True)
        self.chk_download_trans.setEnabled(True)
        self.progress_bar.hide()
        self.lbl_detail_status.hide()
        
        if success:
            if PORTABLE_LIBS_DIR not in sys.path:
                sys.path.insert(0, PORTABLE_LIBS_DIR)
            try:
                from control.ai_controller import _set_resource_cache_state
                _set_resource_cache_state(True, True)
            except Exception:
                pass
            self.refresh_resource_status()
            QMessageBox.information(self, "Thành công", "Hệ thống đã tự động cài đặt trọn gói thư viện lai hỗ trợ CPU & GPU thành công!")
            self.accept()
        else:
            try:
                from control.ai_controller import _set_resource_cache_state
                _set_resource_cache_state(False, False)
            except Exception:
                pass
            self.lbl_status.setText("❌ Tiến trình cấu hình thất bại!")
            QMessageBox.critical(self, "Lỗi Hệ Thống", f"Tiến trình cài đặt tự động thất bại do:\n{error_msg}")
    
    def refresh_resource_status(self):

        info = check_resource_status()

        # tránh signal loop
        self.cbo_model.blockSignals(True)

        current_model = self.cbo_model.currentData()

        # cập nhật tên từng model trong combobox
        for i in range(self.cbo_model.count()):

            model = self.cbo_model.itemData(i)
            text = self.cbo_model.itemText(i).split("  ")[0]

            if info["whisper"][model]:
                self.cbo_model.setItemText(
                    i,
                    f"{text}   ✅ Đã tải"
                )
            else:
                self.cbo_model.setItemText(
                    i,
                    f"{text}   ⬇ Chưa tải"
                )

        self.cbo_model.blockSignals(False)

        text = []

        if info["core"]:
            text.append("🟢 Core AI: Đã cài đặt")
        else:
            text.append("🔴 Core AI: Chưa cài")

        if info["whisper"][current_model]:
            text.append(f"🟢 Whisper {current_model}: Đã tải")
        else:
            text.append(f"🟠 Whisper {current_model}: Chưa tải")

        if info["translation"]:
            text.append("🟢 Dịch Offline: Đã tải")
        else:
            text.append("⚪ Dịch Offline: Chưa tải")

        self.lbl_resource_status.setText("\n".join(text))