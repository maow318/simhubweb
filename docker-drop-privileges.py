#!/usr/local/bin/python3
import os
import pwd
import sys


def main():
    if len(sys.argv) < 3:
        raise SystemExit("usage: docker-drop-privileges <user> <command> [args...]")

    user = sys.argv[1]
    command = sys.argv[2:]
    account = pwd.getpwnam(user)

    os.initgroups(user, account.pw_gid)
    os.setgid(account.pw_gid)
    os.setuid(account.pw_uid)
    os.environ["HOME"] = account.pw_dir
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
