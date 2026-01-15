git clone https://github.com/Comfy-Org/ComfyUI
cd ComfyUI/custom_nodes
git clone https://github.com/Comfy-Org/ComfyUI-Manager comfyui-manager
git clone https://github.com/city96/ComfyUI-GGUF ComfyUI-GGUF
git clone https://github.com/ProGamerGov/ComfyUI_pytorch360convert ComfyUI_pytorch360convert
git clone https://github.com/ProGamerGov/ComfyUI_pytorch360convert_video ComfyUI_pytorch360convert_video
git clone https://github.com/ProGamerGov/ComfyUI_preview360panorama ComfyUI_preview360panorama
git clone https://github.com/ssitu/ComfyUI_UltimateSDUpscale ComfyUI_UltimateSDUpscale
cd ..
python -m venv venv
source venv/bin/activate
python -m pip install torch torchvision torchaudio --extra-index-url https://download.pytorch.org/whl/cu121
python -m pip install -r requirements.txt
python -m pip install -r custom_nodes/comfyui-manager/requirements.txt
python -m pip install --no-dependencies pytorch360convert
python -m pip install hf_transfer gguf
cd ..
echo "#!/bin/bash" > run_gpu.sh
echo "cd ComfyUI" >> run_gpu.sh
echo "source venv/bin/activate" >> run_gpu.sh
echo "python main.py --preview-method auto" >> run_gpu.sh
chmod +x run_gpu.sh

echo "#!/bin/bash" > run_cpu.sh
echo "cd ComfyUI" >> run_cpu.sh
echo "source venv/bin/activate" >> run_cpu.sh
echo "python main.py --preview-method auto --cpu" >> run_cpu.sh
chmod +x run_cpu.sh
