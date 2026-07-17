"""P7.B frontmatter application for dhara.

User-authorized mechanical sweep (2026-07-17). Mirrors
mahavishnu/scripts/_orphan_sweep_C1_2.py but adapted for dhara's doc layout:
- 16 in-scope content files (one plans store: docs/implementation-plans/ + superpowers/plans/
  + superpowers/specs/) plus 2 schema files copied from mahavishnu.

Per-file (status, role, topic) assignments derived from each file's body. Each
file's existing `**Status:**` line (if any) gets a trailing legacy comment so the
validator's --allow-nonstandard mode stays green.
"""
from pathlib import Path

PLAN_FM_TEMPLATE = (
    "---\n"
    "status: {status}\n"
    "role: {role}\n"
    "date: 2026-07-17\n"
    "last_reviewed: 2026-07-17\n"
    "superseded_by: {superseded_by}\n"
    "blocks_on: {blocks_on}\n"
    "topic: {topic}\n"
    "---\n"
    "\n"
)

# Per-file assignment table. superseded_by and blocks_on are YAML-encoded
# snippets (use "null" for null scalar, "[]" for empty list, "[<path>]" for a
# single-entry list, etc.).
ASSIGNMENTS: dict[str, dict[str, str]] = {
    # ---- Loose docs/ ------------------------------------------------------
    "docs/2026-07-15-async-migration-cleanup.md": {
        "status": "active",
        "role": "implementation",
        "topic": "persistence",
        "superseded_by": "null",
        "blocks_on": "[]",
    },
    "docs/BACKUP_POLICY.md": {
        "status": "active",
        "role": "canonical",
        "topic": "persistence",
        "superseded_by": "null",
        "blocks_on": "[]",
    },
    "docs/BACKUP_RECOVERY.md": {
        "status": "active",
        "role": "canonical",
        "topic": "persistence",
        "superseded_by": "null",
        "blocks_on": "[]",
    },
    "docs/LEGACY_COMPATIBILITY_AND_REMOVAL_PLAN.md": {
        "status": "complete",
        "role": "historical",
        "topic": "persistence",
        # Plan body explicitly names the active successor.
        "superseded_by": "docs/2026-07-15-async-migration-cleanup.md",
        "blocks_on": "[]",
    },
    "docs/README.md": {
        "status": "active",
        "role": "canonical",
        "topic": "persistence",
        "superseded_by": "null",
        "blocks_on": "[]",
    },
    "docs/SECRET_MANAGEMENT.md": {
        "status": "active",
        "role": "canonical",
        "topic": "auth",
        "superseded_by": "null",
        "blocks_on": "[]",
    },
    "docs/serialization-implementation.md": {
        "status": "complete",
        "role": "historical",
        "topic": "persistence",
        "superseded_by": "null",
        "blocks_on": "[]",
    },
    "docs/test_coverage_improvement.md": {
        "status": "complete",
        "role": "historical",
        "topic": "persistence",
        "superseded_by": "null",
        "blocks_on": "[]",
    },
    # ---- docs/guides/ -----------------------------------------------------
    "docs/guides/operational-modes.md": {
        "status": "active",
        "role": "canonical",
        "topic": "persistence",
        "superseded_by": "null",
        "blocks_on": "[]",
    },
    # ---- docs/reference/ --------------------------------------------------
    "docs/reference/service-dependencies.md": {
        "status": "active",
        "role": "canonical",
        "topic": "persistence",
        "superseded_by": "null",
        "blocks_on": "[]",
    },
    # ---- docs/implementation-plans/ --------------------------------------
    "docs/implementation-plans/DHARA_REMEDIATION_AND_CANONICALIZATION_PLAN.md": {
        "status": "active",
        "role": "umbrella",
        "topic": "convergence-control-plane",
        "superseded_by": "null",
        "blocks_on": "[]",
    },
    # ---- docs/superpowers/specs/ -----------------------------------------
    "docs/superpowers/specs/2026-07-15-dhara-cache-adapter-oneiric-consolidation-design.md": {
        "status": "shipped",
        "role": "canonical",
        "topic": "adapter-architecture",
        "superseded_by": "null",
        "blocks_on": "[]",
    },
    # ---- docs/superpowers/plans/ -----------------------------------------
    "docs/superpowers/plans/2026-05-31-btree-redesign-plan.md": {
        "status": "complete",
        "role": "historical",
        "topic": "persistence",
        # Plan explicitly states "Do not execute this plan" / no successor file.
        "superseded_by": "null",
        "blocks_on": "[]",
    },
    "docs/superpowers/plans/2026-05-31-dhara-async-first-plan.md": {
        "status": "active",
        "role": "implementation",
        "topic": "persistence",
        "superseded_by": "null",
        # Companion to the cleanup plan that supersedes the legacy plan.
        "blocks_on": "[docs/2026-07-15-async-migration-cleanup.md]",
    },
    "docs/superpowers/plans/2026-07-15-dhara-cache-adapter-oneiric-consolidation-plan.md": {
        "status": "shipped",
        "role": "implementation",
        "topic": "adapter-architecture",
        "superseded_by": "null",
        "blocks_on": "[]",
    },
    "docs/superpowers/plans/2026-07-15-oneiric-cache-factory-and-settings-plan.md": {
        "status": "active",
        "role": "implementation",
        "topic": "adapter-architecture",
        "superseded_by": "null",
        "blocks_on": "[]",
    },
    # ---- docs/schemas/ (copied from mahavishnu) --------------------------
    "docs/schemas/document-frontmatter-v1.md": {
        "status": "active",
        "role": "canonical",
        "topic": "lifecycle",
        "superseded_by": "null",
        "blocks_on": "[]",
    },
    "docs/schemas/topic-vocabulary-v1.md": {
        "status": "active",
        "role": "canonical",
        "topic": "lifecycle",
        "superseded_by": "null",
        "blocks_on": "[]",
    },
}


def add_legacy_comment(text: str) -> str:
    """Append the trailing HTML legacy comment on the first `**Status**` line
    (case-insensitive). Mirrors the C1.2 helper.
    """
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("**Status") and "Status" in stripped:
            original = stripped.rstrip("\n")
            if "-- see YAML frontmatter" not in original:
                lines[i] = original + "  <!-- legacy status — see YAML frontmatter -->\n"
            break
    return "".join(lines)


def main() -> None:
    repo_root = Path("/Users/les/Projects/dhara")
    results: list[tuple[str, str, str, str]] = []
    for rel_path, params in ASSIGNMENTS.items():
        path = repo_root / rel_path
        if not path.is_file():
            print(f"SKIP (missing): {rel_path}")
            continue
        original = path.read_text(encoding="utf-8")
        if original.lstrip().startswith("---\n"):
            print(f"SKIP (already has frontmatter): {rel_path}")
            continue
        frontmatter = PLAN_FM_TEMPLATE.format(**params)
        body_with_comment = add_legacy_comment(original)
        new_content = frontmatter + body_with_comment
        path.write_text(new_content, encoding="utf-8")
        results.append(
            (rel_path, params["status"], params["role"], params["topic"])
        )
    print(f"\nEdited {len(results)} files:")
    for rel, st, rl, tp in results:
        print(f"  {rel}: status={st} role={rl} topic={tp}")


if __name__ == "__main__":
    main()
