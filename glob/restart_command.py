"""Build the argument vector used to restart the current ComfyUI process."""

import os


def build_restart_argv(executable: str, argv: list[str]) -> list[str]:
    """Keep each original argument intact for ``os.execv`` (which uses no shell)."""
    args = argv.copy()
    if '--windows-standalone-build' in args:
        args.remove('--windows-standalone-build')
    if not args:
        raise ValueError('Cannot restart without an entry point')

    if args[0].endswith('__main__.py'):
        module_name = os.path.basename(os.path.dirname(args[0]))
        return [executable, '-m', module_name, *args[1:]]

    return [executable, *args]
