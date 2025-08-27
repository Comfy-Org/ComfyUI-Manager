import mimetypes
import manager_core as core
import os
from aiohttp import web
import aiohttp
import json
import hashlib

import folder_paths
from server import PromptServer


def extract_model_file_names(json_data):
    """Extract unique file names from the input JSON data."""
    file_names = set()
    model_filename_extensions = {'.safetensors', '.ckpt', '.pt', '.pth', '.bin'}

    # Recursively search for file names in the JSON data
    def recursive_search(data):
        if isinstance(data, dict):
            for value in data.values():
                recursive_search(value)
        elif isinstance(data, list):
            for item in data:
                recursive_search(item)
        elif isinstance(data, str) and '.' in data:
            file_names.add(os.path.basename(data))  # file_names.add(data)

    recursive_search(json_data)
    return [f for f in list(file_names) if os.path.splitext(f)[1] in model_filename_extensions]


def find_file_paths(base_dir, file_names):
    """Find the paths of the files in the base directory."""
    file_paths = {}

    for root, dirs, files in os.walk(base_dir):
        # Exclude certain directories
        dirs[:] = [d for d in dirs if d not in ['.git']]

        for file in files:
            if file in file_names:
                file_paths[file] = os.path.join(root, file)
    return file_paths


def compute_sha256_checksum(filepath):
    """Compute the SHA256 checksum of a file, in chunks"""
    sha256 = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


@PromptServer.instance.routes.get("/manager/share_option")
async def share_option(request):
    if "value" in request.rel_url.query:
        core.get_config()['share_option'] = request.rel_url.query['value']
        core.write_config()
    else:
        return web.Response(text=core.get_config()['share_option'], status=200)

    return web.Response(status=200)


def get_openart_auth():
    if not os.path.exists(os.path.join(core.manager_files_path, ".openart_key")):
        return None
    try:
        with open(os.path.join(core.manager_files_path, ".openart_key"), "r") as f:
            openart_key = f.read().strip()
        return openart_key if openart_key else None
    except:
        return None


def get_matrix_auth():
    if not os.path.exists(os.path.join(core.manager_files_path, "matrix_auth")):
        return None
    try:
        with open(os.path.join(core.manager_files_path, "matrix_auth"), "r") as f:
            matrix_auth = f.read()
            homeserver, username, password = matrix_auth.strip().split("\n")
            if not homeserver or not username or not password:
                return None
        return {
            "homeserver": homeserver,
            "username": username,
            "password": password,
        }
    except:
        return None


def get_comfyworkflows_auth():
    if not os.path.exists(os.path.join(core.manager_files_path, "comfyworkflows_sharekey")):
        return None
    try:
        with open(os.path.join(core.manager_files_path, "comfyworkflows_sharekey"), "r") as f:
            share_key = f.read()
            if not share_key.strip():
                return None
        return share_key
    except:
        return None


def get_youml_settings():
    if not os.path.exists(os.path.join(core.manager_files_path, ".youml")):
        return None
    try:
        with open(os.path.join(core.manager_files_path, ".youml"), "r") as f:
            youml_settings = f.read().strip()
        return youml_settings if youml_settings else None
    except:
        return None


def set_youml_settings(settings):
    with open(os.path.join(core.manager_files_path, ".youml"), "w") as f:
        f.write(settings)


@PromptServer.instance.routes.get("/manager/get_openart_auth")
async def api_get_openart_auth(request):
    # print("Getting stored Matrix credentials...")
    openart_key = get_openart_auth()
    if not openart_key:
        return web.Response(status=404)
    return web.json_response({"openart_key": openart_key})


@PromptServer.instance.routes.post("/manager/set_openart_auth")
async def api_set_openart_auth(request):
    json_data = await request.json()
    openart_key = json_data['openart_key']
    with open(os.path.join(core.manager_files_path, ".openart_key"), "w") as f:
        f.write(openart_key)
    return web.Response(status=200)


@PromptServer.instance.routes.get("/manager/get_matrix_auth")
async def api_get_matrix_auth(request):
    # print("Getting stored Matrix credentials...")
    matrix_auth = get_matrix_auth()
    if not matrix_auth:
        return web.Response(status=404)
    return web.json_response(matrix_auth)


@PromptServer.instance.routes.get("/manager/youml/settings")
async def api_get_youml_settings(request):
    youml_settings = get_youml_settings()
    if not youml_settings:
        return web.Response(status=404)
    return web.json_response(json.loads(youml_settings))


@PromptServer.instance.routes.post("/manager/youml/settings")
async def api_set_youml_settings(request):
    json_data = await request.json()
    set_youml_settings(json.dumps(json_data))
    return web.Response(status=200)


@PromptServer.instance.routes.get("/manager/get_comfyworkflows_auth")
async def api_get_comfyworkflows_auth(request):
    # Check if the user has provided Matrix credentials in a file called 'matrix_accesstoken'
    # in the same directory as the ComfyUI base folder
    # print("Getting stored Comfyworkflows.com auth...")
    comfyworkflows_auth = get_comfyworkflows_auth()
    if not comfyworkflows_auth:
        return web.Response(status=404)
    return web.json_response({"comfyworkflows_sharekey": comfyworkflows_auth})


@PromptServer.instance.routes.post("/manager/set_esheep_workflow_and_images")
async def set_esheep_workflow_and_images(request):
    json_data = await request.json()
    with open(os.path.join(core.manager_files_path, "esheep_share_message.json"), "w", encoding='utf-8') as file:
        json.dump(json_data, file, indent=4)
        return web.Response(status=200)


@PromptServer.instance.routes.get("/manager/get_esheep_workflow_and_images")
async def get_esheep_workflow_and_images(request):
    with open(os.path.join(core.manager_files_path, "esheep_share_message.json"), 'r', encoding='utf-8') as file:
        data = json.load(file)
        return web.Response(status=200, text=json.dumps(data))


def set_matrix_auth(json_data):
    homeserver = json_data['homeserver']
    username = json_data['username']
    password = json_data['password']
    with open(os.path.join(core.manager_files_path, "matrix_auth"), "w") as f:
        f.write("\n".join([homeserver, username, password]))


def set_comfyworkflows_auth(comfyworkflows_sharekey):
    with open(os.path.join(core.manager_files_path, "comfyworkflows_sharekey"), "w") as f:
        f.write(comfyworkflows_sharekey)


def has_provided_matrix_auth(matrix_auth):
    return matrix_auth['homeserver'].strip() and matrix_auth['username'].strip() and matrix_auth['password'].strip()


def has_provided_comfyworkflows_auth(comfyworkflows_sharekey):
    return comfyworkflows_sharekey.strip()


@PromptServer.instance.routes.post("/manager/share")
async def share_art(request):
    # get json data
    json_data = await request.json()

    matrix_auth = json_data['matrix_auth']
    comfyworkflows_sharekey = json_data['cw_auth']['cw_sharekey']

    set_matrix_auth(matrix_auth)
    set_comfyworkflows_auth(comfyworkflows_sharekey)

    share_destinations = json_data['share_destinations']
    credits = json_data['credits']
    title = json_data['title']
    description = json_data['description']
    is_nsfw = json_data['is_nsfw']
    prompt = json_data['prompt']
    potential_outputs = json_data['potential_outputs']
    selected_output_index = json_data['selected_output_index']

    try:
        output_to_share = potential_outputs[int(selected_output_index)]
    except:
        # for now, pick the first output
        output_to_share = potential_outputs[0]

    assert output_to_share['type'] in ('image', 'output')
    output_dir = folder_paths.get_output_directory()

    if output_to_share['type'] == 'image':
        asset_filename = output_to_share['image']['filename']
        asset_subfolder = output_to_share['image']['subfolder']

        if output_to_share['image']['type'] == 'temp':
            output_dir = folder_paths.get_temp_directory()
    else:
        asset_filename = output_to_share['output']['filename']
        asset_subfolder = output_to_share['output']['subfolder']

    if asset_subfolder:
        asset_filepath = os.path.join(output_dir, asset_subfolder, asset_filename)
    else:
        asset_filepath = os.path.join(output_dir, asset_filename)

    # get the mime type of the asset
    assetFileType = mimetypes.guess_type(asset_filepath)[0]

    share_website_host = "UNKNOWN"
    if "comfyworkflows" in share_destinations:
        share_website_host = "https://comfyworkflows.com"
        share_endpoint = f"{share_website_host}/api"

        # get presigned urls
        async with aiohttp.ClientSession(trust_env=True, connector=aiohttp.TCPConnector(verify_ssl=False)) as session:
            async with session.post(
                    f"{share_endpoint}/get_presigned_urls",
                    json={
                        "assetFileName": asset_filename,
                        "assetFileType": assetFileType,
                        "workflowJsonFileName": 'workflow.json',
                        "workflowJsonFileType": 'application/json',
                    },
            ) as resp:
                assert resp.status == 200
                presigned_urls_json = await resp.json()
                assetFilePresignedUrl = presigned_urls_json["assetFilePresignedUrl"]
                assetFileKey = presigned_urls_json["assetFileKey"]
                workflowJsonFilePresignedUrl = presigned_urls_json["workflowJsonFilePresignedUrl"]
                workflowJsonFileKey = presigned_urls_json["workflowJsonFileKey"]

        # upload asset
        async with aiohttp.ClientSession(trust_env=True, connector=aiohttp.TCPConnector(verify_ssl=False)) as session:
            async with session.put(assetFilePresignedUrl, data=open(asset_filepath, "rb")) as resp:
                assert resp.status == 200

        # upload workflow json
        async with aiohttp.ClientSession(trust_env=True, connector=aiohttp.TCPConnector(verify_ssl=False)) as session:
            async with session.put(workflowJsonFilePresignedUrl, data=json.dumps(prompt['workflow']).encode('utf-8')) as resp:
                assert resp.status == 200

        model_filenames = extract_model_file_names(prompt['workflow'])
        model_file_paths = find_file_paths(folder_paths.base_path, model_filenames)

        models_info = {}
        for filename, filepath in model_file_paths.items():
            models_info[filename] = {
                "filename": filename,
                "sha256_checksum": compute_sha256_checksum(filepath),
                "relative_path": os.path.relpath(filepath, folder_paths.base_path),
            }

        # make a POST request to /api/upload_workflow with form data key values
        async with aiohttp.ClientSession(trust_env=True, connector=aiohttp.TCPConnector(verify_ssl=False)) as session:
            form = aiohttp.FormData()
            if comfyworkflows_sharekey:
                form.add_field("shareKey", comfyworkflows_sharekey)
            form.add_field("source", "comfyui_manager")
            form.add_field("assetFileKey", assetFileKey)
            form.add_field("assetFileType", assetFileType)
            form.add_field("workflowJsonFileKey", workflowJsonFileKey)
            form.add_field("sharedWorkflowWorkflowJsonString", json.dumps(prompt['workflow']))
            form.add_field("sharedWorkflowPromptJsonString", json.dumps(prompt['output']))
            form.add_field("shareWorkflowCredits", credits)
            form.add_field("shareWorkflowTitle", title)
            form.add_field("shareWorkflowDescription", description)
            form.add_field("shareWorkflowIsNSFW", str(is_nsfw).lower())
            form.add_field("currentSnapshot", json.dumps(await core.get_current_snapshot()))
            form.add_field("modelsInfo", json.dumps(models_info))

            async with session.post(
                    f"{share_endpoint}/upload_workflow",
                    data=form,
            ) as resp:
                assert resp.status == 200
                upload_workflow_json = await resp.json()
                workflowId = upload_workflow_json["workflowId"]

    # check if the user has provided Matrix credentials
    if "matrix" in share_destinations:
        comfyui_share_room_id = '!LGYSoacpJPhIfBqVfb:matrix.org'
        filename = os.path.basename(asset_filepath)
        content_type = assetFileType

        try:
            from matrix_client.api import MatrixHttpApi
            from matrix_client.client import MatrixClient

            homeserver = 'matrix.org'
            if matrix_auth:
                homeserver = matrix_auth.get('homeserver', 'matrix.org')
            homeserver = homeserver.replace("http://", "https://")
            if not homeserver.startswith("https://"):
                homeserver = "https://" + homeserver

            client = MatrixClient(homeserver)
            try:
                token = client.login(username=matrix_auth['username'], password=matrix_auth['password'])
                if not token:
                    return web.json_response({"error": "Invalid Matrix credentials."}, content_type='application/json', status=400)
            except:
                return web.json_response({"error": "Invalid Matrix credentials."}, content_type='application/json', status=400)

            matrix = MatrixHttpApi(homeserver, token=token)
            with open(asset_filepath, 'rb') as f:
                mxc_url = matrix.media_upload(f.read(), content_type, filename=filename)['content_uri']

            workflow_json_mxc_url = matrix.media_upload(prompt['workflow'], 'application/json', filename='workflow.json')['content_uri']

            text_content = ""
            if title:
                text_content += f"{title}\n"
            if description:
                text_content += f"{description}\n"
            if credits:
                text_content += f"\ncredits: {credits}\n"
            matrix.send_message(comfyui_share_room_id, text_content)
            matrix.send_content(comfyui_share_room_id, mxc_url, filename, 'm.image')
            matrix.send_content(comfyui_share_room_id, workflow_json_mxc_url, 'workflow.json', 'm.file')
        except:
            import traceback
            traceback.print_exc()
            return web.json_response({"error": "An error occurred when sharing your art to Matrix."}, content_type='application/json', status=500)

    return web.json_response({
        "comfyworkflows": {
            "url": None if "comfyworkflows" not in share_destinations else f"{share_website_host}/workflows/{workflowId}",
        },
        "matrix": {
            "success": None if "matrix" not in share_destinations else True
        }
    }, content_type='application/json', status=200)
