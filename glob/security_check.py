import sys
import subprocess
import os

import manager_util


def security_check():
    print("[START] Security scan")

    custom_nodes_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    comfyui_path = os.path.abspath(os.path.join(custom_nodes_path, '..'))

    guide = {
        "ComfyUI_LLMVISION": """
0.Remove ComfyUI\\custom_nodes\\ComfyUI_LLMVISION.
1.Remove pip packages: openai-1.16.3.dist-info, anthropic-0.21.4.dist-info, openai-1.30.2.dist-info, anthropic-0.21.5.dist-info, anthropic-0.26.1.dist-info, %LocalAppData%\\rundll64.exe
  (For portable versions, it is recommended to reinstall. If you are using a venv, it is advised to recreate the venv.)
2.Remove these files in your system: lib/browser/admin.py, Cadmino.py, Fadmino.py, VISION-D.exe, BeamNG.UI.exe
3.Check your Windows registry for the key listed above and remove it.
  (HKEY_CURRENT_USER\\Software\\OpenAICLI)
4.Run a malware scanner.
5.Change all of your passwords, everywhere.

(Reinstall OS is recommended.)
\n
Detailed information: https://old.reddit.com/r/comfyui/comments/1dbls5n/psa_if_youve_used_the_comfyui_llmvision_node_from/
    """,
        "lolMiner": """
1. Remove pip packages: lolMiner*
2. Remove files: lolMiner*, 4G_Ethash_Linux_Readme.txt, mine* in ComfyUI dir.

(Reinstall ComfyUI is recommended.)
    """,
    "ultralytics==8.3.41": f"""
Execute following commands:
    {sys.executable} -m pip uninstall ultralytics
    {sys.executable} -m pip install ultralytics==8.3.40
    
And kill and remove /tmp/ultralytics_runner


The version 8.3.41 to 8.3.42 of the Ultralytics package you installed is compromised. Please uninstall that version and reinstall the latest version.
https://blog.comfy.org/comfyui-statement-on-the-ultralytics-crypto-miner-situation/
    """,
    "ultralytics==8.3.42": f"""
Execute following commands:
    {sys.executable} -m pip uninstall ultralytics
    {sys.executable} -m pip install ultralytics==8.3.40

And kill and remove /tmp/ultralytics_runner


The version 8.3.41 to 8.3.42 of the Ultralytics package you installed is compromised. Please uninstall that version and reinstall the latest version.
https://blog.comfy.org/comfyui-statement-on-the-ultralytics-crypto-miner-situation/
    """,
    "litellm==1.82.7": f"""
Execute following commands:
    {sys.executable} -m pip uninstall litellm

The litellm PyPI package versions 1.82.7 and 1.82.8 were compromised via a supply chain attack.
Malicious code harvests SSH keys, environment variables, API keys, cloud credentials, and exfiltrates them to an attacker-controlled server.
Version 1.82.8 also installs a .pth file that executes malware on ANY Python startup, even without importing litellm.

1. Uninstall litellm immediately.
2. Assume all credentials accessible to the litellm environment are compromised.
3. Rotate all API keys, cloud credentials, SSH keys, and database passwords.
4. Check site-packages for unexpected .pth files (e.g. litellm_init.pth) and remove them.
5. Run a full malware scan.

Details: https://github.com/BerriAI/litellm/issues/24518
Advisory: PYSEC-2026-2
    """,
    "litellm==1.82.8": f"""
Execute following commands:
    {sys.executable} -m pip uninstall litellm

The litellm PyPI package versions 1.82.7 and 1.82.8 were compromised via a supply chain attack.
Malicious code harvests SSH keys, environment variables, API keys, cloud credentials, and exfiltrates them to an attacker-controlled server.
Version 1.82.8 also installs a .pth file that executes malware on ANY Python startup, even without importing litellm.

1. Uninstall litellm immediately.
2. Assume all credentials accessible to the litellm environment are compromised.
3. Rotate all API keys, cloud credentials, SSH keys, and database passwords.
4. Check site-packages for unexpected .pth files (e.g. litellm_init.pth) and remove them.
5. Run a full malware scan.

Details: https://github.com/BerriAI/litellm/issues/24518
Advisory: PYSEC-2026-2
    """
             }

    node_blacklist = {"ComfyUI_LLMVISION": "ComfyUI_LLMVISION"}

    pip_blacklist = {
        "AppleBotzz": "ComfyUI_LLMVISION",
        "ultralytics==8.3.41": "ultralytics==8.3.41",
        "ultralytics==8.3.42": "ultralytics==8.3.42",
        "litellm==1.82.7": "litellm==1.82.7",
        "litellm==1.82.8": "litellm==1.82.8",
    }

    file_blacklist = {
        "ComfyUI_LLMVISION": ["%LocalAppData%\\rundll64.exe"],
        "lolMiner": [os.path.join(comfyui_path, 'lolMiner')]
    }

    installed_pips = subprocess.check_output(manager_util.make_pip_cmd(["freeze"]), text=True)

    detected = set()
    try:
        anthropic_info = subprocess.check_output(manager_util.make_pip_cmd(["show", "anthropic"]), text=True, stderr=subprocess.DEVNULL)
        requires_lines = [x for x in anthropic_info.split('\n') if x.startswith("Requires")]
        if requires_lines:
            anthropic_reqs = requires_lines[0].split(": ", 1)[1]
            if "pycrypto" in anthropic_reqs:
                location_lines = [x for x in anthropic_info.split('\n') if x.startswith("Location")]
                if location_lines:
                    location = location_lines[0].split(": ", 1)[1]
                    for fi in os.listdir(location):
                        if fi.startswith("anthropic"):
                            guide["ComfyUI_LLMVISION"] = (f"\n0.Remove {os.path.join(location, fi)}" + guide["ComfyUI_LLMVISION"])
                            detected.add("ComfyUI_LLMVISION")

    except subprocess.CalledProcessError:
        pass

    for k, v in node_blacklist.items():
        if os.path.exists(os.path.join(custom_nodes_path, k)):
            print(f"[SECURITY ALERT] custom node '{k}' is dangerous.")
            detected.add(v)

    installed_pip_set = set(installed_pips.strip().split('\n'))

    for k, v in pip_blacklist.items():
        if '==' in k:
            if k in installed_pip_set:
                detected.add(v)
        else:
            if any(line.split('==')[0] == k for line in installed_pip_set):
                detected.add(v)

    for k, v in file_blacklist.items():
        for x in v:
            if os.path.exists(os.path.expandvars(x)):
                detected.add(k)
                break

    if len(detected) > 0:
        for line in installed_pip_set:
            for k, v in pip_blacklist.items():
                if '==' in k:
                    if line == k:
                        print(f"[SECURITY ALERT] '{line}' is dangerous.")
                else:
                    if line.split('==')[0] == k:
                        print(f"[SECURITY ALERT] '{line}' is dangerous.")

        print("\n########################################################################")
        print("   Malware has been detected, forcibly terminating ComfyUI execution.")
        print("########################################################################\n")

        for x in detected:
            print(f"\n======== TARGET: {x} =========")
            print("\nTODO:")
            print(guide.get(x))

        exit(-1)

    print("[DONE] Security scan")
