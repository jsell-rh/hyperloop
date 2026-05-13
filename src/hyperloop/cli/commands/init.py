from __future__ import annotations

import click
import yaml

from hyperloop.cli.git import find_git_root
from hyperloop.reconciliation.models.configuration import Configuration


_DEFAULT_OVERLAY_PATH = Configuration.model_fields["overlay_path"].default
_BASE_TEMPLATES_REPO = "https://github.com/jsell-rh/hyperloop.git"
_BASE_TEMPLATES_PATH = "base"
_BASE_TEMPLATES_REF = "main"


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

    overlay_dir.mkdir(parents=True, exist_ok=True)

    resource_url = (
        f"{_BASE_TEMPLATES_REPO}//{_BASE_TEMPLATES_PATH}?ref={_BASE_TEMPLATES_REF}"
    )
    content = {
        "apiVersion": "kustomize.config.k8s.io/v1beta1",
        "kind": "Kustomization",
        "resources": [resource_url],
    }
    kustomization_path.write_text(
        yaml.dump(content, default_flow_style=False, sort_keys=False)
    )

    click.echo(f"Initialized hyperloop in {overlay_dir}")
