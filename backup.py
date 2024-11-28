import os
import re
import platform
import glob
import subprocess
import sys

def get_logs_directory():
    system = platform.system()
    if system == "Darwin":  # macOS
        return os.path.expanduser("~/Library/Logs/ComfyUI")
    if system == "Windows":
        appdata = os.getenv("APPDATA")
        if appdata is None:
            raise EnvironmentError("APPDATA environment variable is not set")
        return os.path.join(appdata, "ComfyUI", "logs")
  
    raise NotImplementedError(f"System {system} not supported")

def parse_log_file(log_path):
    custom_nodes = set()
    pattern = r"custom_nodes[/\\]([^/\\\s]+)(?:\.py)?"

    with open(log_path, 'r', encoding='utf-8') as file:
        content = file.read()
        matches = re.finditer(pattern, content)
        
        for match in matches:
            node_name = match.group(1)
            # Exclude specific nodes
            if node_name not in ["ComfyUI-Manager", "websocket_image_save.py"]:
                custom_nodes.add(node_name)
    
    return custom_nodes

def get_sorted_log_files():
    try:
      logs_dir = get_logs_directory()
    except EnvironmentError:
      print("Failed to get logs directory")
      return []
    
    log_files = glob.glob(os.path.join(logs_dir, "comfyui*.log"))
    
    # Sort files by modification time, newest first
    return sorted(log_files, key=os.path.getmtime, reverse=True)

def install_custom_nodes(nodes_list):
    if not nodes_list:
        print("No custom nodes to install")
        return
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    cm_cli_path = os.path.join(current_dir, "cm-cli.py")
    
    if not os.path.exists(cm_cli_path):
        print("ComfyUI-Manager CLI not found")
        return
    
    nodes_str = " ".join(nodes_list)
    
    try:
        cmd = [sys.executable, cm_cli_path, "install", *nodes_list]
        subprocess.run(cmd, check=True)
        print(f"Successfully installed nodes: {nodes_str}")
    except subprocess.CalledProcessError as e:
        print(f"Error installing nodes: {e}")

def main():
    log_files = get_sorted_log_files()
    if not log_files:
        print("No log files found")
        return

    custom_nodes = set()
    for log_file in log_files:
        nodes = parse_log_file(log_file)
        if nodes:
            custom_nodes.update(nodes)    
    print(f"Found custom nodes: {custom_nodes}")
    install_custom_nodes(custom_nodes)

if __name__ == "__main__":
    #main()
    print(parse_log_file("/Users/junhanhuang/Downloads/comfyui_2024-11-28T00-22-15-857Z.log"))

