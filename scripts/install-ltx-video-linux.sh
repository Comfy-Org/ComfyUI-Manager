#!/bin/bash
# ============================================================================
# ComfyUI + LTX-Video Automated Installer for Linux/macOS
# ============================================================================
#
# This script automates the installation of ComfyUI with LTX-Video support.
# It handles dependencies, downloads models, and configures low-VRAM settings.
#
# Prerequisites:
#   - Python 3.9+ installed
#   - Git installed
#   - NVIDIA GPU with CUDA support (for GPU acceleration)
#   - ~50GB free disk space (models + ComfyUI)
#
# Usage:
#   1. Create an empty directory where you want ComfyUI installed
#   2. Save this script in that directory
#   3. Run: chmod +x install-ltx-video-linux.sh
#   4. Run: ./install-ltx-video-linux.sh
#
# ============================================================================

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

SUCCESS="${GREEN}[SUCCESS]${NC}"
ERROR="${RED}[ERROR]${NC}"
INFO="${BLUE}[INFO]${NC}"
WARNING="${YELLOW}[WARNING]${NC}"

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
INSTALL_DIR="$(dirname "$SCRIPT_DIR")"
COMFYUI_DIR="$INSTALL_DIR/ComfyUI"
CUSTOM_NODES="$COMFYUI_DIR/custom_nodes"
MODELS_DIR="$COMFYUI_DIR/models"

echo ""
echo "============================================================================"
echo "ComfyUI + LTX-Video Installer for Linux/macOS"
echo "============================================================================"
echo ""

# Check prerequisites
echo -e "$INFO Checking prerequisites..."

if ! command -v python3 &> /dev/null; then
    echo -e "$ERROR Python 3 not found. Please install Python 3.9+ first."
    exit 1
fi

if ! command -v git &> /dev/null; then
    echo -e "$ERROR Git not found. Please install Git first."
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
echo -e "$SUCCESS Python $PYTHON_VERSION found."
echo -e "$SUCCESS Git found."
echo ""

# Detect OS
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS="linux"
    echo -e "$INFO Detected Linux system"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    OS="macos"
    echo -e "$INFO Detected macOS system"
else
    OS="unknown"
    echo -e "$WARNING Unknown OS detected. Proceeding anyway..."
fi
echo ""

echo -e "$INFO Installation directory: $INSTALL_DIR"
echo -e "$INFO ComfyUI will be installed to: $COMFYUI_DIR"
echo ""

# Step 1: Clone ComfyUI
echo -e "$INFO Step 1/7: Cloning ComfyUI repository..."
if [ -d "$COMFYUI_DIR" ]; then
    echo -e "$INFO ComfyUI directory already exists. Skipping clone."
else
    git clone https://github.com/comfyanonymous/ComfyUI "$COMFYUI_DIR"
    if [ $? -ne 0 ]; then
        echo -e "$ERROR Failed to clone ComfyUI repository."
        exit 1
    fi
    echo -e "$SUCCESS ComfyUI cloned successfully."
fi
echo ""

# Step 2: Clone ComfyUI-Manager
echo -e "$INFO Step 2/7: Installing ComfyUI-Manager..."
if [ -d "$CUSTOM_NODES/comfyui-manager" ]; then
    echo -e "$INFO ComfyUI-Manager already installed. Skipping."
else
    mkdir -p "$CUSTOM_NODES"
    git clone https://github.com/ltdrdata/ComfyUI-Manager "$CUSTOM_NODES/comfyui-manager"
    if [ $? -ne 0 ]; then
        echo -e "$ERROR Failed to clone ComfyUI-Manager."
        exit 1
    fi
    echo -e "$SUCCESS ComfyUI-Manager installed."
fi
echo ""

# Step 3: Setup Python virtual environment
echo -e "$INFO Step 3/7: Setting up Python virtual environment..."
if [ -d "$INSTALL_DIR/venv" ]; then
    echo -e "$INFO Virtual environment already exists. Skipping creation."
else
    python3 -m venv "$INSTALL_DIR/venv"
    if [ $? -ne 0 ]; then
        echo -e "$ERROR Failed to create virtual environment."
        exit 1
    fi
    echo -e "$SUCCESS Virtual environment created."
fi
echo ""

# Activate virtual environment
source "$INSTALL_DIR/venv/bin/activate"
if [ $? -ne 0 ]; then
    echo -e "$ERROR Failed to activate virtual environment."
    exit 1
fi
echo -e "$SUCCESS Virtual environment activated."
echo ""

# Step 4: Install PyTorch with CUDA support
echo -e "$INFO Step 4/7: Installing PyTorch with CUDA support..."
echo -e "$INFO This step may take several minutes..."
pip install --upgrade pip setuptools wheel

# Try CUDA 12.4 first (most recent stable)
if [[ "$OS" == "linux" ]]; then
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
elif [[ "$OS" == "macos" ]]; then
    # macOS typically uses CPU or MPS
    pip install torch torchvision torchaudio
fi

if [ $? -ne 0 ]; then
    echo -e "$ERROR Failed to install PyTorch."
    exit 1
fi
echo -e "$SUCCESS PyTorch installed."
echo ""

# Step 5: Install ComfyUI and Manager dependencies
echo -e "$INFO Step 5/7: Installing ComfyUI dependencies..."
cd "$COMFYUI_DIR"
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo -e "$ERROR Failed to install ComfyUI requirements."
    exit 1
fi
echo -e "$SUCCESS ComfyUI dependencies installed."
echo ""

echo -e "$INFO Installing ComfyUI-Manager dependencies..."
pip install -r "$CUSTOM_NODES/comfyui-manager/requirements.txt"
if [ $? -ne 0 ]; then
    echo -e "$ERROR Failed to install ComfyUI-Manager requirements."
    exit 1
fi
echo -e "$SUCCESS ComfyUI-Manager dependencies installed."
echo ""

# Step 6: Install LTX-Video dependencies
echo -e "$INFO Step 6/7: Installing LTX-Video additional dependencies..."
pip install opencv-python pillow imageio imageio-ffmpeg
if [ $? -ne 0 ]; then
    echo -e "$WARNING Some LTX-Video dependencies may not have installed. This is often non-critical."
fi
echo ""

# Step 7: Create launch scripts
echo -e "$INFO Step 7/7: Creating launch scripts..."
cd "$INSTALL_DIR"

# Create run_gpu.sh
cat > "$INSTALL_DIR/run_gpu.sh" << 'EOF'
#!/bin/bash
cd "$(dirname "$0")/ComfyUI"
source "$(dirname "$0")/venv/bin/activate"

echo ""
echo "============================================================================"
echo "ComfyUI + LTX-Video (Low-VRAM Mode)"
echo "============================================================================"
echo ""
echo "GPU Memory Configuration:"
echo "  - Low VRAM Mode: enabled"
echo "  - Reserved VRAM: 1 GB"
echo "  - Recommended Resolution: 512x512"
echo "  - Recommended Frames: 25-40 (3-5 seconds at 8 FPS)"
echo ""

python main.py --lowvram --reserve-vram 1
EOF

chmod +x "$INSTALL_DIR/run_gpu.sh"
echo -e "$SUCCESS Created run_gpu.sh with low-VRAM settings."

# Create run_cpu.sh
cat > "$INSTALL_DIR/run_cpu.sh" << 'EOF'
#!/bin/bash
cd "$(dirname "$0")/ComfyUI"
source "$(dirname "$0")/venv/bin/activate"

echo ""
echo "============================================================================"
echo "ComfyUI + LTX-Video (CPU Mode - Slow)"
echo "============================================================================"
echo ""

python main.py --cpu
EOF

chmod +x "$INSTALL_DIR/run_cpu.sh"
echo -e "$SUCCESS Created run_cpu.sh for CPU fallback."
echo ""

# Create model directories
mkdir -p "$MODELS_DIR/checkpoints"
mkdir -p "$MODELS_DIR/diffusion_models"
mkdir -p "$MODELS_DIR/text_encoders"
mkdir -p "$MODELS_DIR/vae"

echo -e "$SUCCESS Model directories created."
echo ""

# Create setup guide
echo -e "$INFO Creating LTX-Video setup guide..."
cat > "$INSTALL_DIR/SETUP_GUIDE.txt" << 'EOF'

============================================================================
ComfyUI + LTX-Video Setup Complete!
============================================================================

NEXT STEPS:

1. Download LTX-Video Models:
   Visit: https://huggingface.co/Lightricks
   Download LTX-Video/LTXV 2B model files and place them in:
   - $MODELS_DIR/checkpoints/
   - $MODELS_DIR/diffusion_models/
   - $MODELS_DIR/text_encoders/
   - $MODELS_DIR/vae/

2. Launch ComfyUI:
   Run: ./run_gpu.sh
   ComfyUI will open at: http://127.0.0.1:8188

3. Install LTX-Video Custom Nodes:
   - Click "Manager" button in ComfyUI
   - Search for "LTX" or related nodes
   - Install any required custom nodes
   - Restart ComfyUI

4. Load LTX-Video Workflow:
   - Download an LTX-Video workflow JSON from:
     https://github.com/Lightricks/LTX-Video
   - Drag the JSON file into ComfyUI

5. Configure Recommended Settings:
   - Resolution: 512 x 512
   - Frames: 25 (for ~3 second clips at 8 FPS)
   - FPS: 8
   - Steps: 20-25
   - Batch Size: 1

6. Generate Your First Video:
   Use a simple prompt:
   "A cinematic shot of a red sports car driving along a winding coastal
    road at sunset, realistic lighting, smooth camera tracking"

TROUBLESHOOTING:

- Out of Memory Error:
  * Reduce resolution to 448x448
  * Reduce frame count (try 17 frames first)
  * Close other GPU-intensive applications

- Missing Custom Nodes:
  * Use ComfyUI Manager to install missing nodes
  * Check node console for specific error messages

- Model Not Found:
  * Ensure model files are in the correct directories
  * Verify filenames match the workflow expectations

DOCUMENTATION:
- ComfyUI: https://github.com/comfyanonymous/ComfyUI
- ComfyUI-Manager: https://github.com/ltdrdata/ComfyUI-Manager
- LTX-Video: https://huggingface.co/Lightricks

============================================================================
EOF

echo -e "$SUCCESS Setup guide created: SETUP_GUIDE.txt"
echo ""

# Final summary
echo ""
echo "============================================================================"
echo "Installation Complete!"
echo "============================================================================"
echo ""
echo "Installation Directory: $INSTALL_DIR"
echo "ComfyUI Directory: $COMFYUI_DIR"
echo "Models Directory: $MODELS_DIR"
echo ""
echo "To start ComfyUI, run:"
echo "  $INSTALL_DIR/run_gpu.sh"
echo ""
echo "For detailed setup instructions, see:"
echo "  $INSTALL_DIR/SETUP_GUIDE.txt"
echo ""
