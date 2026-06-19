"""Install / refresh elm-mcp's custom Bob modes into ~/.bob.

Single source of truth shared by two callers so they can never diverge:
  - setup.py (the installer / `setup.py --modes-only`)
  - the `install_elm_modes` MCP tool + the `update_elm_mcp` refresh

This module is PURE logic: it returns a structured result dict and prints
nothing, so the MCP tool can surface the outcome as a chat message while
setup.py can print it in its own style.

The 5 modes (🧭 Concierge, 📝 Plan, 📤 Push, 🎯 Impact Analyst,
📜 Compliance Auditor) live in `modes/custom_modes.yaml`; per-mode playbooks
live in `modes/rules/rules-<slug>/`. Bob reads modes from
~/.bob/settings/custom_modes.yaml (newer) or ~/.bob/custom_modes.yaml (older);
it loads them at startup, so a restart is always required after installing.
"""
from __future__ import annotations

from pathlib import Path
import shutil

# The slugs we own. On merge we replace exactly these and keep every other
# mode the user has, so re-running is safe and never clobbers their work.
ELM_MODE_SLUGS = (
    "concierge",
    "requirements-planner",
    "requirements-pusher",
    "impact-analyst",
    "compliance-auditor",
)


def _block_str_representer(dumper, data):
    """Force literal block style (|) for multi-line strings so the big
    roleDefinition / customInstructions markdown blocks stay readable in
    Bob's custom_modes.yaml (matches Bob's own formatting)."""
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


def bob_present(home: Path) -> bool:
    """Bob is detected if ~/.bob exists (Bob creates it on first run)."""
    return (home / ".bob").exists()


def install_modes(source_dir: Path, home: Path) -> dict:
    """Merge `<source_dir>/modes/custom_modes.yaml` into Bob's custom modes
    and copy the per-mode playbooks into ~/.bob/rules-<slug>/.

    `source_dir` is the directory CONTAINING `modes/` — i.e. the install root
    (the repo folder, or site-packages when installed as a wheel).

    Non-destructive: every mode the user has that isn't one of ours is kept,
    and the existing file is backed up (.yaml.bak) before writing.

    Returns a dict:
      ok (bool), installed (int), preserved (int), playbooks (int),
      target (str|None), reason (str|None — set on skip/failure),
      message (str — human-readable summary, safe to show the user).
    """
    result = {
        "ok": False, "installed": 0, "preserved": 0, "playbooks": 0,
        "target": None, "reason": None, "message": "",
    }

    if not bob_present(home):
        result["reason"] = "bob-not-found"
        result["message"] = (
            "Bob doesn't appear to be installed on this machine (no ~/.bob "
            "folder). Custom modes are a Bob-only feature."
        )
        return result

    modes_dir = source_dir / "modes"
    src_yaml = modes_dir / "custom_modes.yaml"
    if not src_yaml.exists():
        result["reason"] = "source-missing"
        result["message"] = (
            f"Mode definitions weren't found at {src_yaml}. Re-download/"
            f"reinstall elm-mcp so the modes/ folder is present."
        )
        return result

    try:
        import yaml
    except ImportError:
        result["reason"] = "no-yaml"
        result["message"] = "PyYAML isn't available, so modes can't be written."
        return result

    yaml.add_representer(str, _block_str_representer)

    # ── Load our modes ──────────────────────────────────────────
    try:
        our_doc = yaml.safe_load(src_yaml.read_text(encoding="utf-8")) or {}
        our_modes = our_doc.get("customModes", [])
    except Exception as e:  # noqa: BLE001
        result["reason"] = "parse-source"
        result["message"] = f"Couldn't parse the mode definitions: {e}"
        return result
    if not our_modes:
        result["reason"] = "empty-source"
        result["message"] = "No modes found in modes/custom_modes.yaml."
        return result

    # ── Locate Bob's global custom-modes file ───────────────────
    settings_dir = home / ".bob" / "settings"
    candidates = [
        settings_dir / "custom_modes.yaml",     # newer Bob
        home / ".bob" / "custom_modes.yaml",     # older Bob
    ]
    target = next((c for c in candidates if c.exists()), None)
    if target is None:
        settings_dir.mkdir(parents=True, exist_ok=True)
        target = settings_dir / "custom_modes.yaml"
        existing_modes = []
    else:
        try:
            existing_doc = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
            existing_modes = existing_doc.get("customModes", [])
        except Exception:  # noqa: BLE001 — unreadable file: back up + start fresh
            existing_modes = []

    # ── Merge: drop our slugs from existing, keep the rest, append ours ──
    kept = [m for m in existing_modes if m.get("slug") not in ELM_MODE_SLUGS]
    merged = kept + our_modes

    if target.exists():
        try:
            shutil.copy2(target, target.with_suffix(".yaml.bak"))
        except Exception:  # noqa: BLE001
            pass

    try:
        out = yaml.dump(
            {"customModes": merged},
            default_flow_style=False, sort_keys=False,
            allow_unicode=True, width=10_000,
        )
        target.write_text(out, encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        result["reason"] = "write-failed"
        result["message"] = f"Couldn't write modes to {target}: {e}"
        return result

    # ── Copy the per-mode playbooks ─────────────────────────────
    rules_src = modes_dir / "rules"
    playbooks = 0
    for slug in ELM_MODE_SLUGS:
        src = rules_src / f"rules-{slug}"
        if not src.exists():
            continue
        dst = home / ".bob" / f"rules-{slug}"
        try:
            dst.mkdir(parents=True, exist_ok=True)
            for f in src.iterdir():
                if f.is_file():
                    shutil.copy2(f, dst / f.name)
            playbooks += 1
        except Exception:  # noqa: BLE001
            pass

    result.update(
        ok=True, installed=len(our_modes), preserved=len(kept),
        playbooks=playbooks, target=str(target),
    )
    result["message"] = (
        f"Installed/updated {len(our_modes)} ELM modes in {target.name}"
        + (f" (kept your {len(kept)} other custom mode(s))" if kept else "")
        + f", plus {playbooks} mode playbook(s)."
    )
    return result
