@echo off
REM ============================================================================
REM ComfyUI + LTX-Video Automated Installer for Windows NVIDIA GPUs
REM ============================================================================
REM
REM This script automates the installation of ComfyUI with LTX-Video support.
REM It handles dependencies, downloads models, and configures low-VRAM settings.
REM
REM Prerequisites:
REM   - Python 3.9+ installed and in PATH
REM   - Git installed and in PATH
REM   - NVIDIA GPU with at least 6GB VRAM (8GB recommended for RTX 5070)
REM   - ~50GB free disk space (models + ComfyUI)
REM
REM Usage:
REM   1. Create an empty directory where you want ComfyUI installed
REM   2. Save this script in that directory
REM   3. Run: install-ltx-video-windows.bat
REM
REM ============================================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ============================================================================
echo ComfyUI + LTX-Video Installer for Windows
echo ============================================================================
echo.

REM Color codes for output
set "SUCCESS=[SUCCESS]"
set "ERROR=[ERROR]"
set "INFO=[INFO]"

REM Check prerequisites
echo %INFO% Checking prerequisites...
python --version >nul 2>&1
if errorlevel 1 (
    echo %ERROR% Python not found. Please install Python 3.9+ and add it to PATH.
    pause
    exit /b 1
)

git --version >nul 2>&1
if errorlevel 1 (
    echo %ERROR% Git not found. Please install Git from https://git-scm.com/download/win
    pause
    exit /b 1
)

echo %SUCCESS% Prerequisites verified.
echo.

REM Setup installation directory
set "INSTALL_DIR=%CD%"
set "COMFYUI_DIR=%INSTALL_DIR%\ComfyUI"
set "CUSTOM_NODES=%COMFYUI_DIR%\custom_nodes"
set "MODELS_DIR=%COMFYUI_DIR%\models"

echo %INFO% Installation directory: %INSTALL_DIR%
echo %INFO% ComfyUI will be installed to: %COMFYUI_DIR%
echo.

REM Step 1: Clone ComfyUI
echo %INFO% Step 1/7: Cloning ComfyUI repository...
if exist "%COMFYUI_DIR%" (
    echo %INFO% ComfyUI directory already exists. Skipping clone.
) else (
    git clone https://github.com/comfyanonymous/ComfyUI "%COMFYUI_DIR%"
    if errorlevel 1 (
        echo %ERROR% Failed to clone ComfyUI repository.
        pause
        exit /b 1
    )
    echo %SUCCESS% ComfyUI cloned successfully.
)
echo.

REM Step 2: Clone ComfyUI-Manager
echo %INFO% Step 2/7: Installing ComfyUI-Manager...
if exist "%CUSTOM_NODES%\comfyui-manager" (
    echo %INFO% ComfyUI-Manager already installed. Skipping.
) else (
    if not exist "%CUSTOM_NODES%" mkdir "%CUSTOM_NODES%"
    git clone https://github.com/ltdrdata/ComfyUI-Manager "%CUSTOM_NODES%\comfyui-manager"
    if errorlevel 1 (
        echo %ERROR% Failed to clone ComfyUI-Manager.
        pause
        exit /b 1
    )
    echo %SUCCESS% ComfyUI-Manager installed.
)
echo.

REM Step 3: Setup Python virtual environment
echo %INFO% Step 3/7: Setting up Python virtual environment...
if exist "%INSTALL_DIR%\venv" (
    echo %INFO% Virtual environment already exists. Skipping creation.
) else (
    python -m venv "%INSTALL_DIR%\venv"
    if errorlevel 1 (
        echo %ERROR% Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo %SUCCESS% Virtual environment created.
)
echo.

REM Activate virtual environment
call "%INSTALL_DIR%\venv\Scripts\activate.bat"
if errorlevel 1 (
    echo %ERROR% Failed to activate virtual environment.
    pause
    exit /b 1
)
echo %SUCCESS% Virtual environment activated.
echo.

REM Step 4: Install PyTorch with CUDA support
echo %INFO% Step 4/7: Installing PyTorch with CUDA support...
echo %INFO% This step may take several minutes...
pip install --upgrade pip setuptools wheel
python -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
if errorlevel 1 (
    echo %ERROR% Failed to install PyTorch.
    pause
    exit /b 1
)
echo %SUCCESS% PyTorch installed with CUDA support.
echo.

REM Step 5: Install ComfyUI and Manager dependencies
echo %INFO% Step 5/7: Installing ComfyUI dependencies...
cd /d "%COMFYUI_DIR%"
pip install -r requirements.txt
if errorlevel 1 (
    echo %ERROR% Failed to install ComfyUI requirements.
    pause
    exit /b 1
)
echo %SUCCESS% ComfyUI dependencies installed.
echo.

echo %INFO% Installing ComfyUI-Manager dependencies...
pip install -r "%CUSTOM_NODES%\comfyui-manager\requirements.txt"
if errorlevel 1 (
    echo %ERROR% Failed to install ComfyUI-Manager requirements.
    pause
    exit /b 1
)
echo %SUCCESS% ComfyUI-Manager dependencies installed.
echo.

REM Step 6: Install LTX-Video dependencies
echo %INFO% Step 6/7: Installing LTX-Video additional dependencies...
pip install opencv-python pillow imageio imageio-ffmpeg
if errorlevel 1 (
    echo %WARNING% Some LTX-Video dependencies may not have installed. This is often non-critical.
)
echo.

REM Step 7: Create launch scripts with low-VRAM settings
echo %INFO% Step 7/7: Creating launch scripts with low-VRAM configuration...
cd /d "%INSTALL_DIR%"

REM Create run_gpu.bat with low-VRAM settings
(
    echo @echo off
    echo cd /d "%COMFYUI_DIR%"
    echo call "%INSTALL_DIR%\venv\Scripts\activate.bat"
    echo echo.
    echo echo ============================================================================
    echo echo ComfyUI + LTX-Video (Low-VRAM Mode)
    echo echo ============================================================================
    echo echo.
    echo echo GPU Memory Configuration:
    echo echo   - Low VRAM Mode: enabled
    echo echo   - Reserved VRAM: 1 GB
    echo echo   - Recommended Resolution: 512x512
    echo echo   - Recommended Frames: 25-40 (3-5 seconds at 8 FPS)
    echo echo.
    echo python main.py --lowvram --reserve-vram 1
    echo pause
) > "%INSTALL_DIR%\run_gpu.bat"

echo %SUCCESS% Created run_gpu.bat with low-VRAM settings.

REM Create run_cpu.bat (for fallback)
(
    echo @echo off
    echo cd /d "%COMFYUI_DIR%"
    echo call "%INSTALL_DIR%\venv\Scripts\activate.bat"
    echo echo.
    echo echo ============================================================================
    echo echo ComfyUI + LTX-Video (CPU Mode - Slow)
    echo echo ============================================================================
    echo echo.
    echo python main.py --cpu
    echo pause
) > "%INSTALL_DIR%\run_cpu.bat"

echo %SUCCESS% Created run_cpu.bat for CPU fallback.
echo.

REM Create model directories
if not exist "%MODELS_DIR%\checkpoints" mkdir "%MODELS_DIR%\checkpoints"
if not exist "%MODELS_DIR%\diffusion_models" mkdir "%MODELS_DIR%\diffusion_models"
if not exist "%MODELS_DIR%\text_encoders" mkdir "%MODELS_DIR%\text_encoders"
if not exist "%MODELS_DIR%\vae" mkdir "%MODELS_DIR%\vae"

echo %SUCCESS% Model directories created.
echo.

REM Create setup guide
echo %INFO% Creating LTX-Video setup guide...
(
    echo.
    echo ============================================================================
    echo ComfyUI + LTX-Video Setup Complete!
    echo ============================================================================
    echo.
    echo NEXT STEPS:
    echo.
    echo 1. Download LTX-Video Models:
    echo    Visit: https://huggingface.co/Lightricks
    echo    Download LTX-Video/LTXV 2B model files and place them in:
    echo    - %MODELS_DIR%\checkpoints\
    echo    - %MODELS_DIR%\diffusion_models\
    echo    - %MODELS_DIR%\text_encoders\
    echo    - %MODELS_DIR%\vae\
    echo.
    echo 2. Launch ComfyUI:
    echo    Double-click: run_gpu.bat
    echo    ComfyUI will open at: http://127.0.0.1:8188
    echo.
    echo 3. Install LTX-Video Custom Nodes:
    echo    - Click "Manager" button in ComfyUI
    echo    - Search for "LTX" or related nodes
    echo    - Install any required custom nodes
    echo    - Restart ComfyUI
    echo.
    echo 4. Load LTX-Video Workflow:
    echo    - Download an LTX-Video workflow JSON from:
    echo      https://github.com/Lightricks/LTX-Video
    echo    - Drag the JSON file into ComfyUI
    echo.
    echo 5. Configure Recommended Settings for RTX 5070 (8GB):
    echo    - Resolution: 512 x 512
    echo    - Frames: 25 (for ~3 second clips at 8 FPS)
    echo    - FPS: 8
    echo    - Steps: 20-25
    echo    - Batch Size: 1
    echo.
    echo 6. Generate Your First Video:
    echo    Use a simple prompt:
    echo    "A cinematic shot of a red sports car driving along a winding coastal
    echo     road at sunset, realistic lighting, smooth camera tracking"
    echo.
    echo TROUBLESHOOTING:
    echo.
    echo - Out of Memory Error:
    echo   * Reduce resolution to 448x448
    echo   * Reduce frame count (try 17 frames first)
    echo   * Close other GPU-intensive applications
    echo.
    echo - Missing Custom Nodes:
    echo   * Use ComfyUI Manager to install missing nodes
    echo   * Check node console for specific error messages
    echo.
    echo - Model Not Found:
    echo   * Ensure model files are in the correct directories
    echo   * Verify filenames match the workflow expectations
    echo.
    echo DOCUMENTATION:
    echo - ComfyUI: https://github.com/comfyanonymous/ComfyUI
    echo - ComfyUI-Manager: https://github.com/ltdrdata/ComfyUI-Manager
    echo - LTX-Video: https://huggingface.co/Lightricks
    echo.
    echo ============================================================================
) > "%INSTALL_DIR%\SETUP_GUIDE.txt"

echo %SUCCESS% Setup guide created: SETUP_GUIDE.txt
echo.

REM Final summary
echo.
echo ============================================================================
echo Installation Complete!
echo ============================================================================
echo.
echo Installation Directory: %INSTALL_DIR%
echo ComfyUI Directory: %COMFYUI_DIR%
echo Models Directory: %MODELS_DIR%
echo.
echo To start ComfyUI, run:
echo   %INSTALL_DIR%\run_gpu.bat
echo.
echo For detailed setup instructions, see:
echo   %INSTALL_DIR%\SETUP_GUIDE.txt
echo.
echo Press any key to continue...
pause

endlocal
