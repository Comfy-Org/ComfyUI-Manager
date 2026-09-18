"""Installation-denial messages shared by the glob and legacy servers."""

SECURITY_MESSAGE_MIDDLE = "ERROR: To use this action, a security_level of `normal or below` is required. Please contact the administrator.\nReference: https://github.com/Comfy-Org/ComfyUI-Manager#security-policy"
SECURITY_MESSAGE_MIDDLE_P = "ERROR: To use this action, security_level must be `normal or below`, and network_mode must be set to `personal_cloud`. Please contact the administrator.\nReference: https://github.com/Comfy-Org/ComfyUI-Manager#security-policy"
SECURITY_MESSAGE_HIGH_P = "ERROR: To use this action, '--listen' must be set to a local IP and security_level must be 'normal-' or lower. Please contact the administrator.\nReference: https://github.com/Comfy-Org/ComfyUI-Manager#security-policy"
SECURITY_MESSAGE_GENERAL = "ERROR: This installation is not allowed in this security_level. Please contact the administrator.\nReference: https://github.com/Comfy-Org/ComfyUI-Manager#security-policy"
SECURITY_MESSAGE_NORMAL_MINUS_MODEL = "ERROR: Downloading models that are not in '.safetensors' format is only allowed for models registered in the 'default' channel at this security level. If you want to download this model, set the security level to 'normal-' or lower."
