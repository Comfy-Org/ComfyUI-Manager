import os
from urllib.parse import urlparse
import urllib
import sys

aria2 = os.getenv('COMFYUI_MANAGER_ARIA2_SERVER')
HF_ENDPOINT = os.getenv('HF_ENDPOINT')

if aria2 is not None:
    secret = os.getenv('COMFYUI_MANAGER_ARIA2_SECRET')
    url = urlparse(aria2)
    port = url.port
    host = url.scheme + '://' + url.hostname
    import aria2p

    aria2 = aria2p.API(aria2p.Client(host=host, port=port, secret=secret))


def basic_download_url(url, dest_folder, filename):
    import requests

    # Ensure the destination folder exists
    if not os.path.exists(dest_folder):
        os.makedirs(dest_folder)

    # Full path to save the file
    dest_path = os.path.join(dest_folder, filename)

    # Download the file
    response = requests.get(url, stream=True)
    if response.status_code == 200:
        with open(dest_path, 'wb') as file:
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    file.write(chunk)
    else:
        raise Exception(f"Failed to download file from {url}")


def download_url(model_url: str, model_dir: str, filename: str):
    if HF_ENDPOINT:
        model_url = model_url.replace('https://huggingface.co', HF_ENDPOINT)
    if aria2:
        return aria2_download_url(model_url, model_dir, filename)
    else:
        from torchvision.datasets.utils import download_url as torchvision_download_url
        return torchvision_download_url(model_url, model_dir, filename)


def aria2_find_task(dir: str, filename: str):
    target = os.path.join(dir, filename)

    downloads = aria2.get_downloads()

    for download in downloads:
        for file in download.files:
            if file.is_metadata:
                continue
            if str(file.path) == target:
                return download


def aria2_download_url(model_url: str, model_dir: str, filename: str):
    import manager_core as core
    import tqdm
    import time

    if model_dir.startswith(core.comfy_path):
        model_dir = model_dir[len(core.comfy_path) :]

    download_dir = model_dir if model_dir.startswith('/') else os.path.join('/models', model_dir)

    download = aria2_find_task(download_dir, filename)
    if download is None:
        options = {'dir': download_dir, 'out': filename}
        download = aria2.add(model_url, options)[0]

    if download.is_active:
        with tqdm.tqdm(
            total=download.total_length,
            bar_format='{l_bar}{bar}{r_bar}',
            desc=filename,
            unit='B',
            unit_scale=True,
        ) as progress_bar:
            while download.is_active:
                if progress_bar.total == 0 and download.total_length != 0:
                    progress_bar.reset(download.total_length)
                progress_bar.update(download.completed_length - progress_bar.n)
                time.sleep(1)
                download.update()


def download_url_with_agent(url, save_path):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'}

        req = urllib.request.Request(url, headers=headers)
        response = urllib.request.urlopen(req)
        data = response.read()

        if not os.path.exists(os.path.dirname(save_path)):
            os.makedirs(os.path.dirname(save_path))

        with open(save_path, 'wb') as f:
            f.write(data)

    except Exception as e:
        print(f"Download error: {url} / {e}", file=sys.stderr)
        return False

    print("Installation was successful.")
    return True