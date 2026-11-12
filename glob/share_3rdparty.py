import mimetypes
import manager_core as core
import os
from aiohttp import web
import json

import folder_paths
from server import PromptServer


@PromptServer.instance.routes.get("/manager/share_option")
async def share_option(request):
    if "value" in request.rel_url.query:
        core.get_config()['share_option'] = request.rel_url.query['value']
        core.write_config()
    else:
        return web.Response(text=core.get_config()['share_option'], status=200)

    return web.Response(status=200)


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


def set_matrix_auth(json_data):
    homeserver = json_data['homeserver']
    username = json_data['username']
    password = json_data['password']
    with open(os.path.join(core.manager_files_path, "matrix_auth"), "w") as f:
        f.write("\n".join([homeserver, username, password]))


def has_provided_matrix_auth(matrix_auth):
    return matrix_auth['homeserver'].strip() and matrix_auth['username'].strip() and matrix_auth['password'].strip()


@PromptServer.instance.routes.post("/manager/share")
async def share_art(request):
    # get json data
    json_data = await request.json()

    matrix_auth = json_data['matrix_auth']

    set_matrix_auth(matrix_auth)

    share_destinations = json_data['share_destinations']
    credits = json_data['credits']
    title = json_data['title']
    description = json_data['description']
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

    # check if the user has provided Matrix credentials
    if "matrix" in share_destinations:
        comfyui_share_room_id = '!LGYSoacpJPhIfBqVfb:matrix.org'
        filename = os.path.basename(asset_filepath)
        content_type = assetFileType

        try:
            from nio import AsyncClient, LoginResponse, UploadResponse

            homeserver = 'matrix.org'
            if matrix_auth:
                homeserver = matrix_auth.get('homeserver', 'matrix.org')
            homeserver = homeserver.replace("http://", "https://")
            if not homeserver.startswith("https://"):
                homeserver = "https://" + homeserver

            client = AsyncClient(homeserver, matrix_auth['username'])

            # Login
            login_resp = await client.login(matrix_auth['password'])
            if not isinstance(login_resp, LoginResponse) or not login_resp.access_token:
                await client.close()
                return web.json_response({"error": "Invalid Matrix credentials."}, content_type='application/json', status=400)

            # Upload asset
            with open(asset_filepath, 'rb') as f:
                upload_resp, _maybe_keys = await client.upload(f, content_type=content_type, filename=filename)
                asset_data = f.seek(0) or f.read()  # get size for info below
            if not isinstance(upload_resp, UploadResponse) or not upload_resp.content_uri:
                await client.close()
                return web.json_response({"error": "Failed to upload asset to Matrix."}, content_type='application/json', status=500)
            mxc_url = upload_resp.content_uri

            # Upload workflow JSON
            import io
            workflow_json_bytes = json.dumps(prompt['workflow']).encode('utf-8')
            workflow_io = io.BytesIO(workflow_json_bytes)
            upload_workflow_resp, _maybe_keys = await client.upload(workflow_io, content_type='application/json', filename='workflow.json')
            workflow_io.seek(0)
            if not isinstance(upload_workflow_resp, UploadResponse) or not upload_workflow_resp.content_uri:
                await client.close()
                return web.json_response({"error": "Failed to upload workflow to Matrix."}, content_type='application/json', status=500)
            workflow_json_mxc_url = upload_workflow_resp.content_uri

            # Send text message
            text_content = ""
            if title:
                text_content += f"{title}\n"
            if description:
                text_content += f"{description}\n"
            if credits:
                text_content += f"\ncredits: {credits}\n"
            await client.room_send(
                room_id=comfyui_share_room_id,
                message_type="m.room.message",
                content={"msgtype": "m.text", "body": text_content}
            )

            # Send image
            await client.room_send(
                room_id=comfyui_share_room_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.image",
                    "body": filename,
                    "url": mxc_url,
                    "info": {
                        "mimetype": content_type,
                        "size": len(asset_data)
                    }
                }
            )

            # Send workflow JSON file
            await client.room_send(
                room_id=comfyui_share_room_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.file",
                    "body": "workflow.json",
                    "url": workflow_json_mxc_url,
                    "info": {
                        "mimetype": "application/json",
                        "size": len(workflow_json_bytes)
                    }
                }
            )

            await client.close()

        except:
            import traceback
            traceback.print_exc()
            return web.json_response({"error": "An error occurred when sharing your art to Matrix."}, content_type='application/json', status=500)

    return web.json_response({
        "matrix": {
            "success": None if "matrix" not in share_destinations else True
        }
    }, content_type='application/json', status=200)
