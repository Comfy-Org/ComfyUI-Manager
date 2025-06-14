## Testing Changes

1. Activate the ComfyUI environment.

2. Build package locally after making changes.

```bash
# from inside the ComfyUI-Manager directory, with the ComfyUI environment activated
python -m build
```

3. Install the package locally in the ComfyUI environment.

```bash
# Uninstall existing package
pip uninstall comfyui-manager

# Install the locale package
pip install dist/comfyui-manager-*.whl
```

4. Start ComfyUI.

```bash
# after navigating to the ComfyUI directory
python main.py
```

## Manually Publish Test Version to PyPi

1. Set the `PYPI_TOKEN` environment variable in env file.

2. If manually publishing, you likely want to use a release candidate version, so set the version in [pyproject.toml](pyproject.toml) to something like `0.0.1rc1`.

3. Build the package.

```bash
python -m build
```

4. Upload the package to PyPi.

```bash
python -m twine upload dist/* --username __token__ --password $PYPI_TOKEN
```

5. View at https://pypi.org/project/comfyui-manager/
