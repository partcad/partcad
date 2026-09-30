:<<"::CMDLITERAL"
@echo off
rem
rem  The Windows half. There is nothing to resolve here, for either socket.
rem  Docker Desktop is what gives a Windows host the name "/var/run/docker.sock"
rem  -- the daemon behind it is a named pipe -- and devcontainer.json binds that
rem  name directly, so the socket the POSIX half below goes looking for is
rem  already in the container's hands. The SSH agent is a named pipe too,
rem  "\\.\pipe\openssh-ssh-agent", which is not a thing a Linux container can be
rem  handed as a unix socket; SSH_AUTH_SOCK is normally unset on Windows for
rem  that very reason, so there is nothing here to link and nothing lost by not
rem  linking it. Succeed and say nothing.
rem
rem  This file is a polyglot on purpose. "initializeCommand" runs in the host's
rem  own shell, and a failing one aborts "devcontainer up", so naming a ".sh"
rem  there would make this workspace unopenable on a Windows host, where
rem  cmd.exe cannot run one. cmd.exe reads the batch script above, because of
rem  the ".cmd" extension; /bin/sh reads the shell script below, because the
rem  line that opens this comment is a here-document to sh and a label to
rem  cmd. Both halves are terminated before the other's begins.
rem
rem  Keep this file LF-only (.gitattributes pins it): the shell half breaks on
rem  a trailing CR, and the batch half has no label the parser has to seek back
rem  to, which is where cmd.exe minds LF endings.
rem
exit /b 0
::CMDLITERAL

# The POSIX half. The work lives in a separate ".sh" so that it stays under
# shellcheck, which does not recognize a ".cmd" as a shell script.
exec "$(dirname "$0")/host-sockets-init.sh" "$@"
