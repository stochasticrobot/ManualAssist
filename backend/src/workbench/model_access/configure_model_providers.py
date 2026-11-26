"""Create the text and image AI connections selected in the application's settings.

The rest of the application should not need to know how each provider
authenticates or constructs a client. This file reads those choices and prepares
the appropriate connections. Creating a connection does not itself send a model
request."""

from collections.abc import Callable, Mapping
from pathlib import Path
from dotenv import dotenv_values
from workbench.config import ROOT
from workbench.model_access.model_requests_and_responses import (
    Model,
    ModelError,
    ModelService,
)
from workbench.model_access.providers.bedrock import bedrock_factory

FACTORIES: dict[str, Callable[[str, Mapping[str, str]], Model]] = {
    "bedrock": bedrock_factory
}


def register_provider(
    name: str, factory: Callable[[str, Mapping[str, str]], Model]
) -> None:
    """Make a provider available for selection in the application configuration.

    Args:
        name: Provider name used by TEXT_PROVIDER or VISION_PROVIDER, such as bedrock.
        factory: Function receiving a role and private settings, and returning a model
            client that implements generate(request). It must not send a model request.
    Returns:
        None; adds the constructor to the provider list. Raises ValueError rather
        than accidentally replacing an existing provider with the same name."""
    if name in FACTORIES:
        raise ValueError("Provider already registered")
    FACTORIES[name] = factory


def configured_service(path: Path = ROOT / ".env") -> ModelService:
    """Read the private settings and prepare the application's text and vision models.

    Args:
        path: Dotenv file containing provider names and each provider's settings.
            Values are read literally; they are not copied into process environment variables.
    Returns:
        ModelService with configured text and vision clients. Unknown provider names
        and invalid provider settings raise errors before content generation. The
        returned service can make paid requests only when a caller asks it to generate.
        The image_captioning role uses IMAGE_CAPTIONING_PROVIDER and
        BEDROCK_IMAGE_CAPTIONING_MODEL_ID overrides, defaulting to vision settings."""
    values = dotenv_values(path, interpolate=False)
    roles = {}
    for role in ("text", "vision"):
        provider = values.get(f"{role.upper()}_PROVIDER") or "bedrock"
        if provider not in FACTORIES:
            raise ModelError(f"Unregistered provider: {provider}")
        roles[role] = FACTORIES[provider](role, values)
    # A separate application role can be replaced without changing text or vision.
    caption_values = dict(values)
    caption_values["VISION_PROVIDER"] = values.get("IMAGE_CAPTIONING_PROVIDER") or values.get("VISION_PROVIDER") or "bedrock"
    caption_values["BEDROCK_VISION_MODEL_ID"] = values.get("BEDROCK_IMAGE_CAPTIONING_MODEL_ID") or values.get("BEDROCK_VISION_MODEL_ID") or ""
    provider = caption_values["VISION_PROVIDER"]
    if provider not in FACTORIES:
        raise ModelError(f"Unregistered provider: {provider}")
    roles["image_captioning"] = FACTORIES[provider]("vision", caption_values)
    return ModelService(roles)
