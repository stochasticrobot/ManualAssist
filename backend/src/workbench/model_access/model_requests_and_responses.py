"""Give the application one consistent way to ask different AI providers for help.

A request describes the text, optional images and reply limits; a result contains
the answer and reported usage. Shared checks reject requests a selected model
cannot support. Provider-specific authentication and network details remain
outside the manual-analysis code."""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Capabilities:
    """Describe what a configured model supports, including its known output limit.

    An unknown output limit is None: the application must not invent a provider
    limit. Register it from provider documentation before using fractional budgets.
    """

    images: bool = False
    tools: bool = False
    structured_output: bool = False
    max_output_tokens: int | None = None


@dataclass(frozen=True)
class Image:
    """Carry image bytes and their format without requiring an AWS-specific object."""

    data: bytes
    format: str = "png"


@dataclass(frozen=True)
class Request:
    """Describe what to ask, which images to include and how long the reply may be.

    schema describes the expected JSON fields, when needed. The caller still checks
    the reply; asking for a shape does not guarantee that a provider will follow it.
    """

    prompt: str
    system: str = ""
    images: tuple[Image, ...] = ()
    max_tokens: int = 1024
    schema: dict | None = None


@dataclass(frozen=True)
class Result:
    """Return the reply and usage in the same form for every model provider.

    None means the provider did not report a token count; it must not be counted as
    zero. The original usage fields are also retained for inspecting discrepancies.
    """

    text: str
    provider: str
    model: str
    stop_reason: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    raw_usage: dict = field(default_factory=dict)


class ModelError(RuntimeError):
    """Explain a model failure without exposing credentials or private HTTP bodies."""


class InvalidModelResponseError(ModelError):
    """A task reply remained invalid after its single model correction attempt."""


class OutputLimitError(ModelError):
    """The model reached the requested reply length before completing its answer."""


class Model(Protocol):
    """Specify the attributes and method every provider implementation must supply."""

    capabilities: Capabilities
    provider: str
    model: str

    def generate(self, request: Request) -> Result:
        """Send one application request using this provider's API.

        Args:
            request: Text, optional images, output allowance and optional JSON fields.
        Returns:
            Reply text and reported usage in the shared Result form. Implementations
            raise ModelError on failure and must keep credentials out of errors.
            Instances used for analysis must accept up to six concurrent calls
            without sharing mutable per-request state; configuration stays fixed.
        """
        ...


class ModelService:
    """Choose the configured text or image model and check requests before sending."""

    def __init__(self, models: dict[str, Model]):
        """Store the application's model choices without contacting a provider.

        Args:
            models: Mapping from roles, normally text and vision, to provider instances.
        Returns:
            None; retains the supplied choices. No automatic fallback is installed.
        """
        self.models = models

    def selected_model(self, role: str) -> Model:
        """Find the configured model so every caller handles unknown roles the same way.

        Args:
            role: Application role such as text or vision.
        Returns:
            Configured provider instance; raises ModelError if the role is absent.
            Does not send a request or expose the provider's credentials.
        """
        if role not in self.models:
            raise ModelError(f"Unconfigured model role: {role}")
        return self.models[role]

    def identity(self, role: str) -> dict:
        """Identify a model when deciding whether an old response can be reused.

        Args:
            role: Configured application role.
        Returns:
            Provider and model names only; no credentials. Unknown roles raise ModelError.
        """
        model = self.selected_model(role)
        return {"provider": model.provider, "model": model.model}

    def output_allowance(self, role: str, fraction: float) -> int:
        """Reserve a chosen fraction of the model's documented maximum reply length.

        Args:
            role: Configured text or vision model.
            fraction: Task policy between zero (exclusive) and one (inclusive).
        Returns:
            Whole-number output-token allowance, at least one token. Raises ModelError
            for an unknown model limit or invalid fraction; never makes a paid call.
        """
        maximum = self.selected_model(role).capabilities.max_output_tokens
        if maximum is None or maximum < 1 or not 0 < fraction <= 1:
            raise ModelError(
                "A known model output limit and a fraction between zero and one are required"
            )
        return max(1, int(maximum * fraction))

    def generate(self, role: str, request: Request) -> Result:
        """Check image support and reply size, then send exactly the requested task.

        Args:
            role: Configured application role; missing roles fail before any API call.
            request: Text, optional images and a positive output allowance.
        Returns:
            Provider's reply and reported usage. Raises ModelError for unsupported
            images, excessive output size or provider failure. Never switches models.
        """
        model = self.selected_model(role)
        if request.images and not model.capabilities.images:
            raise ModelError(f"Role {role} does not accept images")
        maximum = model.capabilities.max_output_tokens
        if request.max_tokens < 1 or (
            maximum is not None and request.max_tokens > maximum
        ):
            raise ModelError("Requested output exceeds the configured model allowance")
        return model.generate(request)
