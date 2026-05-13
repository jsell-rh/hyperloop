from __future__ import annotations

from pathlib import Path

import click
import yaml

from hyperloop.cli.git import find_git_root
from hyperloop.reconciliation.models.configuration import Configuration


_DEFAULT_OVERLAY_PATH = Configuration.model_fields["overlay_path"].default


def _find_base_dir() -> Path:
    import hyperloop as _pkg

    package_dir = Path(_pkg.__file__).resolve().parent
    candidate = package_dir.parent.parent / "base"
    if candidate.is_dir():
        return candidate
    raise click.ClickException(
        f"Cannot locate base templates directory (expected at {candidate})"
    )


@click.command()
def init() -> None:
    """Scaffold default Hyperloop configuration in the current repository."""
    try:
        repo_path = find_git_root()
    except click.ClickException:
        raise
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    overlay_dir = repo_path / _DEFAULT_OVERLAY_PATH
    kustomization_path = overlay_dir / "kustomization.yaml"

    if kustomization_path.exists():
        click.echo("Already initialized.")
        return

    base_dir = _find_base_dir()

    overlay_dir.mkdir(parents=True, exist_ok=True)

    content = {
        "apiVersion": "kustomize.config.k8s.io/v1beta1",
        "kind": "Kustomization",
        "resources": [str(base_dir)],
    }
    kustomization_path.write_text(
        yaml.dump(content, default_flow_style=False, sort_keys=False)
    )

    click.echo(f"Initialized hyperloop in {overlay_dir}")
