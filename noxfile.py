from nox_poetry import session, Session


# TODO: @alexanderilyin: Move noxfile.py to the .devcontainer directory
# TODO: @alexanderilyin: Add nox support for Python 3.9
# TODO: @alexanderilyin: Add nox support for Python 3.13
# https://devguide.python.org/versions/#supported-versions
@session(python=["3.10", "3.11", "3.12"])
def pytest(session: Session) -> None:
    """Run unit tests."""

    # TODO: @alexanderilyin: Use GH Actions cache to speed up the build
    session.run_always("poetry", "install", external=True)
    session.run("pytest")
