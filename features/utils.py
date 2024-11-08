import os


def expandvars(string, context):
    # TODO: @alexanderilyin: merge this with features/steps/partcad-cli/commands/init.py
    copy = os.environ.copy()
    if hasattr(context, "home_dir"):
        os.environ["HOME"] = context.home_dir
    if hasattr(context, "env"):
        os.environ.update(context.env)

    result = os.path.expandvars(string)
    os.environ = copy
    return result
