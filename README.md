# ComfyUI Manager

**ComfyUI-Manager** is an extension designed to enhance the usability of [ComfyUI](https://github.com/comfyanonymous/ComfyUI). It offers management functions to **install, remove, disable, and enable** various custom nodes of ComfyUI. Furthermore, this extension provides a hub feature and convenience functions to access a wide range of information within ComfyUI.

![menu](https://raw.githubusercontent.com/ltdrdata/ComfyUI-extension-tutorials/refs/heads/Main/ComfyUI-Manager/images/dialog.jpg)

## NOTICE
* V3.16: Support for `uv` has been added. Set `use_uv` in `config.ini`.
* V3.10: `double-click feature` is removed
  * This feature has been moved to https://github.com/ltdrdata/comfyui-connection-helper
* V3.3.2: Overhauled. Officially supports [https://registry.comfy.org/](https://registry.comfy.org/).
* You can see whole nodes info on [ComfyUI Nodes Info](https://ltdrdata.github.io/) page.

## Installation

### Installation[method1] (General installation method: ComfyUI-Manager only)

To install ComfyUI-Manager in addition to an existing installation of ComfyUI, you can follow the following steps:

1. goto `ComfyUI/custom_nodes` dir in terminal(cmd)
2. `git clone https://github.com/ltdrdata/ComfyUI-Manager comfyui-manager`
3. Restart ComfyUI


### Installation[method2] (Installation for portable ComfyUI version: ComfyUI-Manager only)
1. install git 
- https://git-scm.com/download/win
- standalone version  
- select option: use windows default console window
2. Download [scripts/install-manager-for-portable-version.bat](https://github.com/ltdrdata/ComfyUI-Manager/raw/main/scripts/install-manager-for-portable-version.bat) into installed `"ComfyUI_windows_portable"` directory
- Don't click. Right click the link and use save as...
3. double click `install-manager-for-portable-version.bat` batch file

![portable-install](https://raw.githubusercontent.com/ltdrdata/ComfyUI-extension-tutorials/Main/ComfyUI-Manager/images/portable-install.jpg)


### Installation[method3] (Installation through comfy-cli: install ComfyUI and ComfyUI-Manager at once.)  
> RECOMMENDED: comfy-cli provides various features to manage ComfyUI from the CLI.

* **prerequisite: python 3, git**

Windows:
```commandline
python -m venv venv
venv\Scripts\activate
pip install comfy-cli
comfy install
```

Linux/OSX:
```commandline
python -m venv venv
. venv/bin/activate
pip install comfy-cli
comfy install
```
* See also: https://github.com/Comfy-Org/comfy-cli


### Installation[method4] (Installation for linux+venv: ComfyUI + ComfyUI-Manager)

To install ComfyUI with ComfyUI-Manager on Linux using a venv environment, you can follow these steps:
* **prerequisite: python-is-python3, python3-venv, git**

1. Download [scripts/install-comfyui-venv-linux.sh](https://github.com/ltdrdata/ComfyUI-Manager/raw/main/scripts/install-comfyui-venv-linux.sh) into empty install directory
- Don't click. Right click the link and use save as...
- ComfyUI will be installed in the subdirectory of the specified directory, and the directory will contain the generated executable script.
2. `chmod +x install-comfyui-venv-linux.sh`
3. `./install-comfyui-venv-linux.sh`

### Installation Precautions
* **DO**: `ComfyUI-Manager` files must be accurately located in the path `ComfyUI/custom_nodes/comfyui-manager`
  * Installing in a compressed file format is not recommended.
* **DON'T**: Decompress directly into the `ComfyUI/custom_nodes` location, resulting in the Manager contents like `__init__.py` being placed directly in that directory.
  * You have to remove all ComfyUI-Manager files from `ComfyUI/custom_nodes`
* **DON'T**: In a form where decompression occurs in a path such as `ComfyUI/custom_nodes/ComfyUI-Manager/ComfyUI-Manager`.
* **DON'T**: In a form where decompression occurs in a path such as `ComfyUI/custom_nodes/ComfyUI-Manager-main`.
  * In such cases, `ComfyUI-Manager` may operate, but it won't be recognized within `ComfyUI-Manager`, and updates cannot be performed. It also poses the risk of duplicate installations. Remove it and install properly via `git clone` method.


You can execute ComfyUI by running either `./run_gpu.sh` or `./run_cpu.sh` depending on your system configuration.

## Colab Notebook
This repository provides Colab notebooks that allow you to install and use ComfyUI, including ComfyUI-Manager. To use ComfyUI, [click on this link](https://colab.research.google.com/github/ltdrdata/ComfyUI-Manager/blob/main/notebooks/comfyui_colab_with_manager.ipynb).
* Support for installing ComfyUI
* Support for basic installation of ComfyUI-Manager
* Support for automatically installing dependencies of custom nodes upon restarting Colab notebooks.


## How To Use

1. Click "Manager" button on main menu

    ![mainmenu](https://raw.githubusercontent.com/ltdrdata/ComfyUI-extension-tutorials/Main/ComfyUI-Manager/images/topbar.jpg)


2. If you click on 'Install Custom Nodes' or 'Install Models', an installer dialog will open.

    ![menu](https://raw.githubusercontent.com/ltdrdata/ComfyUI-extension-tutorials/refs/heads/Main/ComfyUI-Manager/images/dialog.jpg)

    * There are three DB modes: `DB: Channel (1day cache)`, `DB: Local`, and `DB: Channel (remote)`. 
      * `Channel (1day cache)` utilizes Channel cache information with a validity period of one day to quickly display the list.
        * This information will be updated when there is no cache, when the cache expires, or when external information is retrieved through the Channel (remote).
        * Whenever you start ComfyUI anew, this mode is always set as the **default** mode.
      * `Local` uses information stored locally in ComfyUI-Manager.
        * This information will be updated only when you update ComfyUI-Manager.
        * For custom node developers, they should use this mode when registering their nodes in `custom-node-list.json` and testing them.
      * `Channel (remote)` retrieves information from the remote channel, always displaying the latest list.
      * In cases where retrieval is not possible due to network errors, it will forcibly use local information.

    * The ```Fetch Updates``` menu retrieves update data for custom nodes locally. Actual updates are applied by clicking the ```Update``` button in the ```Install Custom Nodes``` menu.

3. Click 'Install' or 'Try Install' button.

    ![node-install-dialog](https://raw.githubusercontent.com/ltdrdata/ComfyUI-extension-tutorials/Main/ComfyUI-Manager/images/custom-nodes.jpg)

    ![model-install-dialog](https://raw.githubusercontent.com/ltdrdata/ComfyUI-extension-tutorials/Main/ComfyUI-Manager/images/models.jpg)

    * Installed: This item is already installed.
    * Install: Clicking this button will install the item.
    * Try Install: This is a custom node of which installation information cannot be confirmed. Click the button to try installing it.

    * If a red background `Channel` indicator appears at the top, it means it is not the default channel. Since the amount of information held is different from the default channel, many custom nodes may not appear in this channel state.
      * Channel settings have a broad impact, affecting not only the node list but also all functions like "Update all."
    * Conflicted Nodes with a yellow background show a list of nodes conflicting with other extensions in the respective extension. This issue needs to be addressed by the developer, and users should be aware that due to these conflicts, some nodes may not function correctly and may need to be installed accordingly.

4. Share
  ![menu](https://raw.githubusercontent.com/ltdrdata/ComfyUI-extension-tutorials/Main/ComfyUI-Manager/images/topbar.jpg) ![share](https://raw.githubusercontent.com/ltdrdata/ComfyUI-extension-tutorials/Main/ComfyUI-Manager/images/share.jpg) 

  * You can share the workflow by clicking the Share button at the bottom of the main menu or selecting Share Output from the Context Menu of the Image node.
  * Currently, it supports sharing via [https://comfyworkflows.com/](https://comfyworkflows.com/),
    [https://openart.ai](https://openart.ai/workflows/dev), [https://youml.com](https://youml.com) 
    as well as through the Matrix channel.

  ![menu](https://raw.githubusercontent.com/ltdrdata/ComfyUI-extension-tutorials/Main/ComfyUI-Manager/images/share-setting.jpg)
  
  * Through the Share settings in the Manager menu, you can configure the behavior of the Share button in the Main menu or Share Output button on Context Menu.
    * `None`: hide from Main menu
    * `All`: Show a dialog where the user can select a title for sharing.


## Paths
In `ComfyUI-Manager` V3.0 and later, configuration files and dynamically generated files are located under `<USER_DIRECTORY>/default/ComfyUI-Manager/`.

* <USER_DIRECTORY>  
  * If executed without any options, the path defaults to ComfyUI/user.  
  * It can be set using --user-directory <USER_DIRECTORY>.  

* Basic config files: `<USER_DIRECTORY>/default/ComfyUI-Manager/config.ini`
* Configurable channel lists: `<USER_DIRECTORY>/default/ComfyUI-Manager/channels.ini`
* Configurable pip overrides: `<USER_DIRECTORY>/default/ComfyUI-Manager/pip_overrides.json`
* Configurable pip blacklist: `<USER_DIRECTORY>/default/ComfyUI-Manager/pip_blacklist.list`
* Configurable pip auto fix: `<USER_DIRECTORY>/default/ComfyUI-Manager/pip_auto_fix.list`
* Saved snapshot files: `<USER_DIRECTORY>/default/ComfyUI-Manager/snapshots`
* Startup script files: `<USER_DIRECTORY>/default/ComfyUI-Manager/startup-scripts`
* Component files: `<USER_DIRECTORY>/default/ComfyUI-Manager/components`


## `extra_model_paths.yaml` Configuration
The following settings are applied based on the section marked as `is_default`.

* `custom_nodes`: Path for installing custom nodes
    * Importing does not need to adhere to the path set as `is_default`, but this is the path where custom nodes are installed by the `ComfyUI Nodes Manager`.
* `download_model_base`: Path for downloading models


## Snapshot-Manager
* When you press `Save snapshot` or use `Update All` on `Manager Menu`, the current installation status snapshot is saved.
  * Snapshot file dir: `<USER_DIRECTORY>/default/ComfyUI-Manager/snapshots`
  * You can rename snapshot file.
* Press the "Restore" button to revert to the installation status of the respective snapshot.
  * However, for custom nodes not managed by Git, snapshot support is incomplete.
* When you press `Restore`, it will take effect on the next ComfyUI startup.
  * The selected snapshot file is saved in `<USER_DIRECTORY>/default/ComfyUI-Manager/startup-scripts/restore-snapshot.json`, and upon restarting ComfyUI, the snapshot is applied and then deleted.

![model-install-dialog](https://raw.githubusercontent.com/ltdrdata/ComfyUI-extension-tutorials/Main/ComfyUI-Manager/images/snapshot.jpg)


## cm-cli: command line tools for power user
* A tool is provided that allows you to use the features of ComfyUI-Manager without running ComfyUI.
* For more details, please refer to the [cm-cli documentation](docs/en/cm-cli.md).


## How to register your custom node into ComfyUI-Manager

* Add an entry to `custom-node-list.json` located in the root of ComfyUI-Manager and submit a Pull Request.
* NOTE: Before submitting the PR after making changes, please check `Use local DB` and ensure that the extension list loads without any issues in the `Install custom nodes` dialog. Occasionally, missing or extra commas can lead to JSON syntax errors.
* The remaining JSON will be updated through scripts in the future, so you don't need to worry about it.


## Custom node support guide

* **NOTICE:**
    - You should no longer assume that the GitHub repository name will match the subdirectory name under `custom_nodes`. The name of the subdirectory under `custom_nodes` will now use the normalized name from the `name` field in `pyproject.toml`.
    - Avoid relying on directory names for imports whenever possible.

* https://docs.comfy.org/registry/overview
* https://github.com/Comfy-Org/rfcs

**Special purpose files** (optional)
  * `pyproject.toml` - Spec file for comfyregistry.
  * `node_list.json` - When your custom nodes pattern of NODE_CLASS_MAPPINGS is not conventional, it is used to manually provide a list of nodes for reference. ([example](https://github.com/melMass/comfy_mtb/raw/main/node_list.json))
  * `requirements.txt` - When installing, this pip requirements will be installed automatically 
  * `install.py` - When installing, it is automatically called
  * **All scripts are executed from the root path of the corresponding custom node.**


## Component Sharing
* **Copy & Paste**
  * [Demo Page](https://ltdrdata.github.io/component-demo/)
  * When pasting a component from the clipboard, it supports text in the following JSON format. (text/plain)
    ```
    {
      "kind": "ComfyUI Components",
      "timestamp": <current timestamp>,
      "components": 
        {
          <component name>: <component nodedata>
        }
    }
    ```
  * `<current timestamp>` Ensure that the timestamp is always unique.
    * "components" should have the same structure as the content of the file stored in `<USER_DIRECTORY>/default/ComfyUI-Manager/components`.
      * `<component name>`: The name should be in the format `<prefix>::<node name>`.
        * `<compnent nodeata>`: In the nodedata of the group node.
          * `<version>`: Only two formats are allowed: `major.minor.patch` or `major.minor`. (e.g. `1.0`, `2.2.1`)
          * `<datetime>`: Saved time
          * `<packname>`: If the packname is not empty, the category becomes packname/workflow, and it is saved in the <packname>.pack file in `<USER_DIRECTORY>/default/ComfyUI-Manager/components`.
          * `<category>`: If there is neither a category nor a packname, it is saved in the components category.
          ```
              "version":"1.0",
              "datetime": 1705390656516,
              "packname": "mypack",
              "category": "util/pipe",
          ```
* **Drag & Drop**
  * Dragging and dropping a `.pack` or `.json` file will add the corresponding components.
  * Example pack: [Impact.pack](misc/Impact.pack)

* Dragging and dropping or pasting a single component will add a node. However, when adding multiple components, nodes will not be added.


## Support of missing nodes installation

![missing-menu](https://raw.githubusercontent.com/ltdrdata/ComfyUI-extension-tutorials/Main/ComfyUI-Manager/images/missing-menu.jpg)

* When you click on the ```Install Missing Custom Nodes``` button in the menu, it displays a list of extension nodes that contain nodes not currently present in the workflow.

![missing-list](https://raw.githubusercontent.com/ltdrdata/ComfyUI-extension-tutorials/Main/ComfyUI-Manager/images/missing-list.jpg)


# Config
* You can modify the `config.ini` file to apply the settings for ComfyUI-Manager.
    * The path to the `config.ini` used by ComfyUI-Manager is displayed in the startup log messages.
    * See also: [https://github.com/ltdrdata/ComfyUI-Manager#paths]
* Configuration options:
    ```
    [default]
    git_exe = <Manually specify the path to the git executable. If left empty, the default git executable path will be used.>
    use_uv = <Use uv instead of pip for dependency installation.>
    default_cache_as_channel_url = <Determines whether to retrieve the DB designated as channel_url at startup>
    bypass_ssl = <Set to True if SSL errors occur to disable SSL.>
    file_logging = <Configure whether to create a log file used by ComfyUI-Manager.>
    windows_selector_event_loop_policy = <If an event loop error occurs on Windows, set this to True.>
    model_download_by_agent = <When downloading models, use an agent instead of torchvision_download_url.>
    downgrade_blacklist = <Set a list of packages to prevent downgrades. List them separated by commas.>
    security_level = <Set the security level => strong|normal|normal-|weak>
    always_lazy_install = <Whether to perform dependency installation on restart even in environments other than Windows.>
    network_mode = <Set the network mode => public|private|offline>
    ```

    * network_mode:
      - public: An environment that uses a typical public network.
      - private: An environment that uses a closed network, where a private node DB is configured via `channel_url`. (Uses cache if available)
      - offline: An environment that does not use any external connections when using an offline network. (Uses cache if available)


## Additional Feature
* Logging to file feature
  * This feature is enabled by default and can be disabled by setting `file_logging = False` in the `config.ini`.

* Fix node(recreate): When right-clicking on a node and selecting `Fix node (recreate)`, you can recreate the node. The widget's values are reset, while the connections maintain those with the same names.
  * It is used to correct errors in nodes of old workflows created before, which are incompatible with the version changes of custom nodes.

* Double-Click Node Title: You can set the double click behavior of nodes in the ComfyUI-Manager menu.
  * `Copy All Connections`, `Copy Input Connections`: Double-clicking a node copies the connections of the nearest node.
    * This action targets the nearest node within a straight-line distance of 1000 pixels from the center of the node.
    * In the case of `Copy All Connections`, it duplicates existing outputs, but since it does not allow duplicate connections, the existing output connections of the original node are disconnected.
    * This feature copies only the input and output that match the names.
  
  * `Possible Input Connections`: It connects all outputs that match the closest type within the specified range.
    * This connection links to the closest outputs among the nodes located on the left side of the target node.
    
  * `Possible(left) + Copy(right)`: When you Double-Click on the left half of the title, it operates as `Possible Input Connections`, and when you Double-Click on the right half, it operates as `Copy All Connections`.

* Prevent downgrade of specific packages
  * List the package names in the `downgrade_blacklist` section of the `config.ini` file, separating them with commas.
    * e.g
    ```
      downgrade_blacklist = diffusers, kornia
    ```

* Custom pip mapping
  * When you create the `pip_overrides.json` file, it changes the installation of specific pip packages to installations defined by the user.
    * Please refer to the `pip_overrides.json.template` file.

* Prevent the installation of specific pip packages
  * List the package names one per line in the `pip_blacklist.list` file.

* Automatically Restoring pip Installation
 * If you list pip spec requirements in `pip_auto_fix.list`, similar to `requirements.txt`, it will automatically restore the specified versions when starting ComfyUI or when versions get mismatched during various custom node installations.
 * `--index-url` can be used.

* Use `aria2` as downloader
  * [howto](docs/en/use_aria2.md)


## Environment Variables

The following features can be configured using environment variables:

* **COMFYUI_PATH**: The installation path of ComfyUI
* **GITHUB_ENDPOINT**: Reverse proxy configuration for environments with limited access to GitHub
* **HF_ENDPOINT**: Reverse proxy configuration for environments with limited access to Hugging Face


### Example 1:
Redirecting `https://github.com/ltdrdata/ComfyUI-Impact-Pack` to `https://mirror.ghproxy.com/https://github.com/ltdrdata/ComfyUI-Impact-Pack`

```
GITHUB_ENDPOINT=https://mirror.ghproxy.com/https://github.com
```

#### Example 2:
Changing `https://huggingface.co/path/to/somewhere` to `https://some-hf-mirror.com/path/to/somewhere`

```
HF_ENDPOINT=https://some-hf-mirror.com 
```

## Scanner
When you run the `scan.sh` script:

* It updates the `extension-node-map.json`.
  * To do this, it pulls or clones the custom nodes listed in `custom-node-list.json` into `~/.tmp/default`.
  * To skip this step, add the `--skip-update` option.
  * If you want to specify a different path instead of `~/.tmp/default`, run `python scanner.py [path]` directly instead of `scan.sh`.

* It updates the `github-stats.json`.
  * This uses the GitHub API, so set your token with `export GITHUB_TOKEN=your_token_here` to avoid quickly reaching the rate limit and malfunctioning.
  * To skip this step, add the `--skip-update-stat` option.

* The `--skip-all` option applies both `--skip-update` and `--skip-stat-update`.


## Troubleshooting
* If your `git.exe` is installed in a specific location other than system git, please install ComfyUI-Manager and run ComfyUI. Then, specify the path including the file name in `git_exe = ` in the `<USER_DIRECTORY>/default/ComfyUI-Manager/config.ini` file that is generated.
* If updating ComfyUI-Manager itself fails, please go to the **ComfyUI-Manager** directory and execute the command `git update-ref refs/remotes/origin/main a361cc1 && git fetch --all && git pull`.
* If you encounter the error message `Overlapped Object has pending operation at deallocation on Comfyui Manager load` under Windows
  * Edit `config.ini` file: add `windows_selector_event_loop_policy = True`
* if `SSL: CERTIFICATE_VERIFY_FAILED` error is occured.
  * Edit `config.ini` file: add `bypass_ssl = True`


## Security policy
  * Edit `config.ini` file: add `security_level = <LEVEL>`
    * `strong`
      * doesn't allow `high` and `middle` level risky feature
    * `normal`
      * doesn't allow `high` level risky feature
      * `middle` level risky feature is available
    * `normal-`
      * doesn't allow `high` level risky feature if `--listen` is specified and not starts with `127.`
      * `middle` level risky feature is available
    * `weak`
      * all feature is available
    
  * `high` level risky features
    * `Install via git url`, `pip install`
    * Installation of custom nodes registered not in the `default channel`.
    * Fix custom nodes
  
  * `middle` level risky features
    * Uninstall/Update
    * Installation of custom nodes registered in the `default channel`.
    * Restore/Remove Snapshot
    * Restart
  
  * `low` level risky features
    * Update ComfyUI


# Disclaimer

* This extension simply provides the convenience of installing custom nodes and does not guarantee their proper functioning.


## Credit
ComfyUI/[ComfyUI](https://github.com/comfyanonymous/ComfyUI) - A powerful and modular stable diffusion GUI.

**And, for all ComfyUI custom node developers**
