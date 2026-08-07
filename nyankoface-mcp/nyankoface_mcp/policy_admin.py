from __future__ import annotations
import argparse
import hashlib
import json
import uuid
from .audit import AuditStore
from .config import Settings
from .governance import PolicyActor, PolicyAdminService
from .policy import PolicyStore
def _audit_target(scope: str, scope_id: str, suffix: str) -> str:
    target = f"{scope}:{scope_id}/{suffix}"
    if len(target) <= 1024 and scope_id and all(
        ord(character) >= 32 and ord(character) != 127 for character in scope_id
    ):
        return target
    fingerprint = hashlib.sha256(scope_id.encode("utf-8")).hexdigest()
    return f"{scope}:sha256:{fingerprint}/{suffix}"
def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description="Provision NyankoFace MCP Tool policy")
    cli.add_argument("--actor-subject", required=True)
    cli.add_argument("--actor-type", default="human")
    cli.add_argument("--client-id", default="policy-admin-cli")
    commands = cli.add_subparsers(dest="command", required=True)
    for name in ("allow", "deny", "delete"):
        command = commands.add_parser(name)
        command.add_argument("scope", choices=("global", "repository", "service_account", "subject"))
        command.add_argument("scope_id")
        command.add_argument("tool")
    for name in ("read-only", "read-write"):
        command = commands.add_parser(name)
        command.add_argument("scope", choices=("global", "repository", "service_account", "subject"))
        command.add_argument("scope_id")
    return cli
def main(argv: list[str] | None = None, *, settings: Settings | None = None) -> int:
    args = parser().parse_args(argv)
    settings = settings or Settings.from_env()
    policy = PolicyStore(settings.policy_state_path)
    audit = AuditStore(settings.audit_state_path, retention_seconds=settings.audit_retention_seconds)
    service = PolicyAdminService(policy, audit)
    actor = PolicyActor(args.actor_subject, args.actor_type, args.client_id)
    request_id = f"policy:{uuid.uuid4()}"
    if args.command in {"allow", "deny", "delete"}:
        target = _audit_target(args.scope, args.scope_id, args.tool)
        metadata = {"scope": args.scope, "scope_id": args.scope_id, "tool": args.tool}
        if args.command == "delete":
            mutate = lambda: policy.delete_tool_policy(args.scope, args.scope_id, args.tool)
        else:
            metadata["effect"] = args.command
            mutate = lambda: policy.set_tool_policy(args.scope, args.scope_id, args.tool, args.command)
    else:
        enabled = args.command == "read-only"
        target = _audit_target(args.scope, args.scope_id, "read-only")
        metadata = {"scope": args.scope, "scope_id": args.scope_id, "enabled": enabled}
        mutate = lambda: policy.set_read_only(args.scope, args.scope_id, enabled)
    version = service.change(actor=actor, request_id=request_id, target=target,
                             action=args.command, mutate=mutate, metadata=metadata)
    print(json.dumps({"action": args.command, "policy_version": version}))
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
