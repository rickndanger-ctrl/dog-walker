#!/usr/bin/env python3
"""Store or explicitly enable an optional Typesafe Jev routing key."""
import argparse
from getpass import getpass
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dog_walker.jev import CONFIG_PATH, JevError, load_config, save_config


def arguments(argv=None):
    parser = argparse.ArgumentParser(description="Configure the optional Typesafe Jev router.")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--enable", action="store_true",
                         help="opt in to sending task text and routing options to Typesafe")
    actions.add_argument("--disable", action="store_true", help="disable Jev and preserve the saved key")
    parser.add_argument("--replace-key", action="store_true", help="explicitly replace a stored API key")
    return parser.parse_args(argv)


def new_key():
    key = getpass("Typesafe API key (input hidden): ").strip()
    if not key:
        raise JevError("API key cannot be empty")
    confirm = getpass("Confirm API key (input hidden): ").strip()
    if key != confirm:
        raise JevError("API key confirmation did not match")
    return key


def main(argv=None):
    args = arguments(argv)
    exists = CONFIG_PATH.exists() or CONFIG_PATH.is_symlink()
    if args.disable:
        if args.replace_key:
            raise JevError("--replace-key cannot be combined with --disable")
        if not exists:
            print("Jev is already disabled; no config or key was created.")
            return 0
        config = load_config(CONFIG_PATH)
        save_config({"api_key": config["api_key"], "enabled": False}, CONFIG_PATH, replace=True)
        print("Jev is disabled. The saved key was preserved.")
        return 0

    if args.enable:
        print("Enabling Jev sends up to 4,000 characters of task text and routing options to TypeSafe.")
        print("This is optional. Only continue if you accept that data transfer.")
        if input("Type ENABLE to opt in: ").strip() != "ENABLE":
            print("Jev remains disabled.")
            return 1
        config = load_config(CONFIG_PATH) if exists else None
        environment_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
        if args.replace_key:
            key = new_key()
        elif config is not None and config["api_key"]:
            key = config["api_key"]
        elif environment_key:
            key = ""
        else:
            key = new_key()
        save_config({"api_key": key, "enabled": True}, CONFIG_PATH, replace=exists)
        print("Jev is enabled. The API key was not displayed.")
        return 0

    if exists and not args.replace_key:
        raise JevError("Jev config already exists; use --replace-key to rotate it or --disable to preserve it")
    key = "" if os.environ.get("TYPESAFE_API_KEY", "").strip() and not args.replace_key else new_key()
    save_config({"api_key": key, "enabled": False}, CONFIG_PATH, replace=exists)
    print("The key was saved privately and Jev remains disabled. Use --enable to opt in.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (JevError, OSError) as exc:
        print(f"Handler Jev configuration: {exc}", file=sys.stderr)
        sys.exit(1)
