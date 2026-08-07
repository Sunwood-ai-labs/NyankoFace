from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .lifecycle import AdminContext, LifecycleError, TokenLifecycleStore


def _pairs(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        key, separator, permission = value.partition("=")
        if not separator:
            raise argparse.ArgumentTypeError("repository permission must be owner/repo=level")
        result[key] = permission
    return result


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Offline NyankoFace credential lifecycle operator")
    root.add_argument("--registry", type=Path, required=True)
    root.add_argument("--audit", type=Path)
    root.add_argument("--actor", required=True)
    root.add_argument("--reauthenticated-at", type=int, default=int(time.time()))
    commands = root.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create-service-account")
    create.add_argument("subject_id")
    create.add_argument("--forgejo-user-id", type=int, required=True)
    create.add_argument("--forgejo-token-file", required=True)
    create.add_argument("--allowed-scope", action="append", required=True)
    create.add_argument("--repository-permission", action="append", default=[])

    disable = commands.add_parser("disable-service-account")
    disable.add_argument("subject_id")

    remap = commands.add_parser("remap-service-account")
    remap.add_argument("subject_id")
    remap.add_argument("--forgejo-user-id", type=int, required=True)
    remap.add_argument("--forgejo-token-file", required=True)
    remap.add_argument("--allowed-scope", action="append", required=True)
    remap.add_argument("--repository-permission", action="append", default=[])

    issue = commands.add_parser("issue-token")
    issue.add_argument("subject_id")
    issue.add_argument("--client-id", required=True)
    issue.add_argument("--scope", action="append", required=True)
    issue.add_argument("--repository", action="append", default=[])
    issue.add_argument("--ttl-seconds", type=int, default=30 * 24 * 60 * 60)

    rotate = commands.add_parser("rotate-token")
    rotate.add_argument("token_id")
    rotate.add_argument("--ttl-seconds", type=int, default=30 * 24 * 60 * 60)

    revoke = commands.add_parser("revoke-token")
    revoke.add_argument("token_id")
    commands.add_parser("list-tokens")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    store = TokenLifecycleStore(args.registry, args.audit)
    context = AdminContext(args.actor, True, args.reauthenticated_at)
    try:
        if args.command == "create-service-account":
            result = store.create_service_account(
                context,
                subject_id=args.subject_id,
                forgejo_user_id=args.forgejo_user_id,
                forgejo_token_file=args.forgejo_token_file,
                allowed_scopes=args.allowed_scope,
                repository_permissions=_pairs(args.repository_permission),
            )
        elif args.command == "disable-service-account":
            result = store.disable_service_account(context, args.subject_id)
        elif args.command == "remap-service-account":
            result = store.remap_service_account(
                context,
                args.subject_id,
                forgejo_user_id=args.forgejo_user_id,
                forgejo_token_file=args.forgejo_token_file,
                allowed_scopes=args.allowed_scope,
                repository_permissions=_pairs(args.repository_permission),
            )
        elif args.command == "issue-token":
            issued = store.issue(
                context,
                subject_id=args.subject_id,
                client_id=args.client_id,
                scopes=args.scope,
                repositories=args.repository,
                ttl_seconds=args.ttl_seconds,
            )
            result = {**issued.metadata, "token": issued.token}
        elif args.command == "rotate-token":
            issued = store.rotate(context, args.token_id, ttl_seconds=args.ttl_seconds)
            result = {**issued.metadata, "token": issued.token}
        elif args.command == "revoke-token":
            result = store.revoke(context, args.token_id)
        else:
            result = store.list_tokens(context)
    except LifecycleError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
