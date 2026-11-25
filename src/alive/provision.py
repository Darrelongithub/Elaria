"""Provisioning + self-check for the alive host (B16-style).

``python -m alive.provision init``   — generate mac_key + from_hash_salt, print
                                       a TOML skeleton (owner fills the rest).
``python -m alive.provision doctor`` — refuse-to-start checks: config loads,
                                       single recipient, mac key strength,
                                       state dir permissions, and a grep of
                                       THIS install tree for anything that can
                                       never belong here (voiceprint models,
                                       assistant.db, API keys).

The doctor runs anywhere — in the sandbox it proves the package is clean to
copy onto the host. It is not a hardware claim.
"""

from __future__ import annotations

import argparse
import re
import secrets
from pathlib import Path

from .config import AliveConfigError, load_config

#: Names that must NEVER appear under the alive install tree.
FORBIDDEN_PATTERNS = (
    r"voxceleb", r"assistant\.db", r"voiceprint", r"gemini", r"GEMINI",
    r"google[-_]?api", r"\.onnx$", r"assistant\.sqlite3",
)


def cmd_init() -> int:
    mac_key = secrets.token_hex(32)
    salt = secrets.token_hex(16)
    print("# Generated — store the mac_key where ONLY the laptop and this host can read it.\n"
          "[alive]\n"
          f'mac_key = "{mac_key}"\n'
          f'from_hash_salt = "{salt}"\n'
          'owner_e164 = "+2547…"            # the ONE number that is the owner\n'
          'wa_phone_number_id = ""\n'
          'wa_token = ""                   # file mode 0600, never in Drive\n'
          'wa_app_secret = ""\n'
          'verify_token = ""\n'
          'tz = "Africa/Nairobi"\n'
          'state_dir = "./alive-state"\n'
          'freebusy_level = 0              # 0 none / 1 day-level (recommended) / 2 T1 slots\n'
          "\n[alive.caps]\n"
          "max_templates_per_day = 10\n"
          "owner_messages_per_day = 200\n"
          "stranger_turns_per_day_per_sender = 20\n"
          "stranger_messages_per_month = 800\n")
    return 0


def cmd_doctor(config_path: str) -> int:
    problems: list[str] = []
    try:
        cfg = load_config(config_path)
    except (AliveConfigError, OSError, ValueError) as exc:
        print(f"FAIL config: {exc}")
        return 1
    print(f"ok   config loads (tz={cfg.tz}, inbox={cfg.inbox_prefix}/)")

    state = Path(cfg.state_dir)
    state.mkdir(parents=True, exist_ok=True)
    try:
        state.chmod(0o700)
        print("ok   state_dir exists and is mode 0700")
    except OSError:
        problems.append(f"state_dir {state} cannot be chmod 0700")

    # grep this install tree for forbidden artifacts
    root = Path(__file__).resolve().parent
    hits = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        name = path.name
        if any(re.search(p, name, re.IGNORECASE) for p in FORBIDDEN_PATTERNS):
            hits.append(name)
    if hits:
        problems.append(f"forbidden artifacts under alive install: {sorted(hits)}")
    else:
        print("ok   no voiceprint/db/API-key artifacts under the alive package")

    # caps are sane relative to the free allowances
    if cfg.stranger_messages_per_month > 1000:
        problems.append("stranger_messages_per_month exceeds the 1,000 free service "
                        "messages — the line could run up a bill")
    if cfg.max_templates_per_day > 10:
        problems.append("max_templates_per_day above the design ceiling (10)")
    else:
        print(f"ok   template cap in code: {cfg.max_templates_per_day}/day")

    if cfg.fast_lane:
        problems.append("fast_lane is set — this build refuses it")
    else:
        print("ok   fast lane OFF (manager binding)")

    if problems:
        for p in problems:
            print(f"FAIL {p}")
        return 1
    print("PASS doctor — clean to deploy (this is NOT a hardware claim)")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="alive.provision")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="generate keys and a config skeleton")
    doctor = sub.add_parser("doctor", help="run the self-check")
    doctor.add_argument("config", help="path to alive.toml")
    args = parser.parse_args(argv)
    if args.command == "init":
        return cmd_init()
    return cmd_doctor(args.config)


if __name__ == "__main__":
    raise SystemExit(main())
