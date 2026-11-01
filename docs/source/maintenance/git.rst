.. _git-configuration:

#################
Git Configuration
#################


PartCAD imports packages from git repositories without the ``git`` command line tool:
it speaks the git protocols itself, through the ``libgit2`` library that ships with its
dependencies. Nothing has to be installed alongside it for imports to work.

By default, PartCAD uses the system's Git configuration when importing packages
using git, which it reads from ``~/.gitconfig`` whether or not git itself is installed.
If you want to override these configurations, you can add your
overrides in ``~/.partcad/config.yaml`` as shown below:

  .. code-block:: yaml

    # ~/.partcad/config.yaml
    git:
      config:
        "user.name": "John Doe"
        "user.email": "johndoe@example.com"
        ...

Cloning over SSH is faster and more reliable because it uses an efficient
protocol with lower overhead, supports compression, and maintains stable
connections via key-based authentication. SSH avoids HTTPS rate limits,
handles firewalls better, and eliminates credential prompts, making it
ideal for large repositories or frequent interactions.

Repositories reached over SSH are authenticated with the keys held by the running SSH
agent, and then with the default key files (``~/.ssh/id_ed25519``, ``~/.ssh/id_ecdsa``,
``~/.ssh/id_rsa``). A key protected by a passphrase only works through the agent, since
PartCAD never asks for one: a repository it cannot authenticate to fails with an error
rather than waiting for a prompt that nothing would answer.

If you have SSH keys configured then you can add the following
to the ~/.partcad/config.yaml:

  .. code-block:: yaml

    # ~/.partcad/config.yaml
    dependencies:
      overrides:
        url:
          "git@github.com:": "https://github.com/"
