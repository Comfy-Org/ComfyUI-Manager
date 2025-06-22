import concurrent.futures

from comfyui_manager.glob import manager_core as core


def check_state_of_git_node_pack(
    node_packs, do_fetch=False, do_update_check=True, do_update=False
):
    if do_fetch:
        print("Start fetching...", end="")
    elif do_update:
        print("Start updating...", end="")
    elif do_update_check:
        print("Start update check...", end="")

    def process_custom_node(item):
        core.check_state_of_git_node_pack_single(
            item, do_fetch, do_update_check, do_update
        )

    with concurrent.futures.ThreadPoolExecutor(4) as executor:
        for k, v in node_packs.items():
            if v.get("active_version") in ["unknown", "nightly"]:
                executor.submit(process_custom_node, v)

    if do_fetch:
        print("\x1b[2K\rFetching done.")
    elif do_update:
        update_exists = any(
            item.get("updatable", False) for item in node_packs.values()
        )
        if update_exists:
            print("\x1b[2K\rUpdate done.")
        else:
            print("\x1b[2K\rAll extensions are already up-to-date.")
    elif do_update_check:
        print("\x1b[2K\rUpdate check done.")


def nickname_filter(json_obj):
    preemptions_map = {}

    for k, x in json_obj.items():
        if "preemptions" in x[1]:
            for y in x[1]["preemptions"]:
                preemptions_map[y] = k
        elif k.endswith("/ComfyUI"):
            for y in x[0]:
                preemptions_map[y] = k

    updates = {}
    for k, x in json_obj.items():
        removes = set()
        for y in x[0]:
            k2 = preemptions_map.get(y)
            if k2 is not None and k != k2:
                removes.add(y)

        if len(removes) > 0:
            updates[k] = [y for y in x[0] if y not in removes]

    for k, v in updates.items():
        json_obj[k][0] = v

    return json_obj
