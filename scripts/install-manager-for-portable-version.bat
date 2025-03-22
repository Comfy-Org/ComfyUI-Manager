.\python_embeded\python.exe -s -m pip install gitpython
.\python_embeded\python.exe -c "import git; git.Repo.clone_from('https://github.com/ltdrdata/ComfyUI-Manager', './ComfyUI/custom_nodes/comfyui-manager')"
.\python_embeded\python.exe -m pip install -r ./ComfyUI/custom_nodes/comfyui-manager/requirements.txt
