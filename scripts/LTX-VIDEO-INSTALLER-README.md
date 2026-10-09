# ComfyUI + LTX-Video Automated Installers

This directory contains automated installers to set up ComfyUI with LTX-Video support on Windows, Linux, and macOS systems.

## Available Installers

### Windows (NVIDIA GPU)
- **File:** `install-ltx-video-windows.bat`
- **OS:** Windows 10/11
- **GPU:** NVIDIA (CUDA compatible)
- **Installation Type:** Full automated setup with virtual environment

### Linux (NVIDIA GPU)
- **File:** `install-ltx-video-linux.sh`
- **OS:** Ubuntu, Debian, Red Hat, or other Linux distributions
- **GPU:** NVIDIA (CUDA compatible)
- **Installation Type:** Full automated setup with virtual environment

## System Requirements

### Minimum Specs
- **OS:** Windows 10+, Ubuntu 18.04+, macOS 10.15+
- **GPU:** NVIDIA GPU with 6GB VRAM (8GB+ recommended)
- **CPU:** Intel i5/Ryzen 5 or better
- **RAM:** 8GB system RAM minimum, 16GB recommended
- **Storage:** ~50GB free space (models + ComfyUI)
- **Python:** 3.9 or higher
- **Git:** Must be installed and in PATH

### Recommended Specs (for smooth 8K or longer videos)
- **GPU:** NVIDIA RTX 5070 (8GB), RTX 6000 (24GB), or better
- **GPU VRAM:** 12GB+ for extended sessions
- **System RAM:** 32GB
- **Storage:** 100GB+ SSD
- **Python:** 3.11 or 3.12
- **CUDA:** 12.1+ (for RTX 50-series)

### RTX 5070 (8GB) Specific Configuration
The installers are optimized for RTX 5070 with these presets:
```
Resolution:    512 × 512 (start) → 768 × 512 (after testing)
Frames:        25–40 frames
FPS:           8 (produces 3–5 second clips)
Steps:         20–25
Batch Size:    1
VRAM Mode:     Low-VRAM with 1GB reserve
```

## Quick Start

### Windows Installation

1. **Create installation directory:**
   ```cmd
   mkdir C:\ComfyUI-LTX
   cd C:\ComfyUI-LTX
   ```

2. **Download the installer:**
   - Download `install-ltx-video-windows.bat` and save it in `C:\ComfyUI-LTX`
   - Or clone this repository:
     ```cmd
     git clone https://github.com/ltdrdata/ComfyUI-Manager
     cd ComfyUI-Manager\scripts
     ```

3. **Run the installer:**
   ```cmd
   install-ltx-video-windows.bat
   ```
   - Let the script run completely (10-30 minutes depending on internet speed)
   - The script will:
     - Clone ComfyUI
     - Install ComfyUI-Manager
     - Set up a Python virtual environment
     - Install PyTorch with CUDA support
     - Configure low-VRAM mode
     - Create launcher scripts

4. **Download LTX-Video models:**
   - Visit: https://huggingface.co/Lightricks
   - Download the LTXV 2B model files
   - Place files in: `C:\ComfyUI-LTX\ComfyUI\models\`
     - Checkpoints → `models/checkpoints/`
     - Diffusion models → `models/diffusion_models/`
     - Text encoders → `models/text_encoders/`
     - VAE → `models/vae/`

5. **Launch ComfyUI:**
   ```cmd
   run_gpu.bat
   ```
   - Opens at: http://127.0.0.1:8188

### Linux Installation

1. **Create installation directory:**
   ```bash
   mkdir ~/ComfyUI-LTX
   cd ~/ComfyUI-LTX
   ```

2. **Download the installer:**
   - Download `install-ltx-video-linux.sh` and save it in `~/ComfyUI-LTX`
   - Or clone this repository:
     ```bash
     git clone https://github.com/ltdrdata/ComfyUI-Manager
     cd ComfyUI-Manager/scripts
     ```

3. **Run the installer:**
   ```bash
   chmod +x install-ltx-video-linux.sh
   ./install-ltx-video-linux.sh
   ```
   - Let the script run completely (10-30 minutes depending on internet speed)

4. **Download LTX-Video models:**
   - Visit: https://huggingface.co/Lightricks
   - Download the LTXV 2B model files
   - Place files in: `~/ComfyUI-LTX/ComfyUI/models/`

5. **Launch ComfyUI:**
   ```bash
   ./run_gpu.sh
   ```
   - Opens at: http://127.0.0.1:8188

## What the Installers Do

### Step-by-Step Breakdown

1. **Verify Prerequisites**
   - Checks Python 3.9+ installation
   - Checks Git installation
   - Validates system compatibility

2. **Clone Repositories**
   - Clones ComfyUI from official repository
   - Clones ComfyUI-Manager for node management

3. **Create Virtual Environment**
   - Isolates Python dependencies
   - Prevents conflicts with system packages

4. **Install PyTorch**
   - Installs PyTorch with CUDA support (for NVIDIA GPUs)
   - Automatically selects correct version for your system

5. **Install Dependencies**
   - ComfyUI core dependencies
   - ComfyUI-Manager dependencies
   - LTX-Video-specific packages (OpenCV, PIL, imageio)

6. **Create Launcher Scripts**
   - `run_gpu.bat` (Windows) or `run_gpu.sh` (Linux)
     - Optimized with `--lowvram` mode for 8GB VRAM
   - `run_cpu.bat` (Windows) or `run_cpu.sh` (Linux)
     - Fallback CPU mode (very slow, not recommended)

7. **Create Model Directories**
   - Automatically creates required model storage paths

8. **Generate Setup Guide**
   - Creates `SETUP_GUIDE.txt` with next steps

## Troubleshooting

### Installation Issues

#### Python not found
- **Solution:** Install Python 3.9+ from https://www.python.org
- Ensure "Add Python to PATH" during installation
- Restart your terminal after installing Python

#### Git not found (Windows)
- **Solution:** Install Git from https://git-scm.com/download/win
- Choose "Use Windows default console window"
- Restart your terminal after installing Git

#### Virtual environment activation fails
- **Windows:** Ensure `python -m venv` works: `python -m venv test_venv`
- **Linux:** Ensure `python3 -m venv` works: `python3 -m venv test_venv`
- Clean up the failed venv and restart the installer

#### PyTorch installation fails
- Check internet connection
- Try installing PyTorch manually:
  ```bash
  # Windows/Linux NVIDIA
  pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
  ```
- For specific GPU issues, consult: https://pytorch.org/get-started/locally/

### Runtime Issues

#### Out of Memory (OOM) Error
- **Immediate solutions:**
  - Close other GPU-intensive applications (games, browsers)
  - Reduce video resolution to `448 × 448`
  - Reduce frame count to 17 frames
  - Reduce inference steps to 20

- **Persistent issues:**
  - Update NVIDIA drivers to latest version
  - Use `--reserve-vram 2` instead of `1` in launcher script
  - Enable `--split-attention` flag

#### CUDA/Driver Mismatch
- Check NVIDIA driver version: `nvidia-smi`
- Update drivers from https://www.nvidia.com/Download/driverDetails.aspx
- For RTX 50-series, use driver version 570+

#### Model files not loading
- Verify model files are in correct directories:
  ```
  ComfyUI/models/
  ├── checkpoints/        (LTXV checkpoint)
  ├── diffusion_models/   (LTX diffusion model)
  ├── text_encoders/      (T5 text encoder)
  └── vae/                (LTX video VAE)
  ```
- Check filenames match workflow expectations
- Use ComfyUI Manager to verify missing nodes

#### Workflow import fails
- Ensure ComfyUI-Manager is properly installed
- Click "Install Missing Custom Nodes" in Manager
- Restart ComfyUI after installing nodes

## Advanced Configuration

### Custom VRAM Allocation

Edit the launcher script to adjust VRAM settings:

**Windows (`run_gpu.bat`):**
```bat
python main.py --lowvram --reserve-vram 1
```

Alternatives:
- `--lowvram --reserve-vram 2` (more aggressive memory saving)
- `--normalvram` (use full VRAM, only for 12GB+ GPUs)
- `--cpu` (CPU fallback, very slow)

**Linux (`run_gpu.sh`):**
```bash
python main.py --lowvram --reserve-vram 1
```

### Enabling Split Attention (Advanced)

For additional VRAM savings, add to launcher:

**Windows:**
```bat
python main.py --lowvram --reserve-vram 1 --split-attention
```

**Linux:**
```bash
python main.py --lowvram --reserve-vram 1 --split-attention
```

### Using Alternative PyTorch Versions

For specific CUDA versions, modify the installer:

```bash
# For CUDA 12.1
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# For CUDA 11.8 (older systems)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
```

## Model Download Guide

### Official Models
- **Lightricks Hugging Face:** https://huggingface.co/Lightricks
- **Download LTXV 2B** (recommended for RTX 5070)

### Model File Organization

After downloading, organize files like this:

```
ComfyUI/models/
├── checkpoints/
│   └── ltxv_2b.safetensors        (main model)
├── diffusion_models/
│   └── ltx_video_2b.pt            (diffusion component)
├── text_encoders/
│   └── t5_text_encoder.pt         (text encoding)
└── vae/
    └── ltx_video_vae.pt           (video VAE)
```

**Note:** Exact filenames depend on the model release. Check the model's Hugging Face page for correct naming.

## Performance Optimization

### For RTX 5070 (8GB VRAM)

| Setting | Value | Notes |
|---------|-------|-------|
| Resolution | 512×512 | Start here; test before upscaling |
| Frames | 25 | ~3 second clip at 8 FPS |
| FPS | 8 | Smooth motion, lower VRAM |
| Steps | 20-25 | Quality vs speed tradeoff |
| Batch Size | 1 | Required for low VRAM |
| Guidance Scale | 7.5 | Default workflow value |
| Seed | Random | Or set for reproducibility |

### Progression Path

**Test 1:** Quick validation (2 sec)
- Resolution: 512×512
- Frames: 17
- Steps: 20

**Test 2:** Standard clip (3 sec)
- Resolution: 512×512
- Frames: 25
- Steps: 25

**Test 3:** Extended clip (5 sec)
- Resolution: 512×512
- Frames: 40
- Steps: 25

**Test 4:** Higher quality (3 sec)
- Resolution: 512×768
- Frames: 25
- Steps: 30

## Updating ComfyUI and Managers

### Update ComfyUI
```bash
cd ComfyUI
git pull
```

### Update ComfyUI-Manager
```bash
cd ComfyUI/custom_nodes/comfyui-manager
git pull
```

### Update Dependencies
```bash
# Activate virtual environment first
source venv/bin/activate  # Linux/macOS
venv\Scripts\activate     # Windows

# Update installed packages
pip install --upgrade -r requirements.txt
```

## Support and Resources

- **ComfyUI Documentation:** https://github.com/comfyanonymous/ComfyUI
- **ComfyUI-Manager:** https://github.com/ltdrdata/ComfyUI-Manager
- **LTX-Video Official:** https://github.com/Lightricks/LTX-Video
- **NVIDIA CUDA Documentation:** https://developer.nvidia.com/cuda-toolkit
- **PyTorch Installation:** https://pytorch.org/get-started/locally/

## License

These installation scripts are provided as part of ComfyUI-Manager under the same license as the main project. See LICENSE.txt for details.

## Contributing

To improve these installers:
1. Test on multiple systems and GPU configurations
2. Report issues with detailed error messages
3. Submit pull requests with improvements
4. Document any breaking changes

---

**Last Updated:** 2026-09-23
**Tested On:** Windows 11 (RTX 5070), Ubuntu 22.04, macOS 13+
**ComfyUI-Manager Version:** 3.42+
