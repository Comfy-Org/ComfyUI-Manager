from comfy.cli_args import args

SECURITY_MESSAGE_MIDDLE_OR_BELOW = "ERROR: To use this action, a security_level of `middle or below` is required. Please contact the administrator.\nReference: https://github.com/ltdrdata/ComfyUI-Manager#security-policy"
SECURITY_MESSAGE_NORMAL_MINUS = "ERROR: To use this feature, you must either set '--listen' to a local IP and set the security level to 'normal-' or lower, or set the security level to 'middle' or 'weak'. Please contact the administrator.\nReference: https://github.com/ltdrdata/ComfyUI-Manager#security-policy"
SECURITY_MESSAGE_GENERAL = "ERROR: This installation is not allowed in this security_level. Please contact the administrator.\nReference: https://github.com/ltdrdata/ComfyUI-Manager#security-policy"
SECURITY_MESSAGE_NORMAL_MINUS_MODEL = "ERROR: Downloading models that are not in '.safetensors' format is only allowed for models registered in the 'default' channel at this security level. If you want to download this model, set the security level to 'normal-' or lower."


def is_loopback(address):
    import ipaddress

    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


is_local_mode = is_loopback(args.listen)


model_dir_name_map = {
    "checkpoints": "checkpoints",
    "checkpoint": "checkpoints",
    "unclip": "checkpoints",
    "text_encoders": "text_encoders",
    "clip": "text_encoders",
    "vae": "vae",
    "lora": "loras",
    "t2i-adapter": "controlnet",
    "t2i-style": "controlnet",
    "controlnet": "controlnet",
    "clip_vision": "clip_vision",
    "gligen": "gligen",
    "upscale": "upscale_models",
    "embedding": "embeddings",
    "embeddings": "embeddings",
    "unet": "diffusion_models",
    "diffusion_model": "diffusion_models",
}
