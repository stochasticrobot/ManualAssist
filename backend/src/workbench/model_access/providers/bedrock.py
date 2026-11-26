"""Send text and image requests to models hosted by Amazon Bedrock.

This file handles the AWS connection, translates the application's request into
the provider's format and returns the answer and reported usage. It also checks
known model capabilities and handles connection failures. It does not decide which
manual passages to read or whether an answer is correct."""

import json
import boto3
import botocore.session
from botocore.config import Config
from botocore.exceptions import ReadTimeoutError
from botocore.tokens import ScopedEnvTokenProvider, TokenProviderChain
from workbench.model_access.model_requests_and_responses import (
    Capabilities,
    ModelError,
    Request,
    Result,
)


class BedrockModel:
    """Handle Bedrock authentication and requests for one configured model."""

    def __init__(self, model: str, region: str, token: str, capabilities: Capabilities):
        """Prepare an AWS client for this model without asking it to generate anything.

        Args:
            model: Exact Bedrock model or inference-profile ID selected in settings.
            region: AWS region through which requests will be sent.
            token: Private Bedrock bearer credential; retained in this client's session,
                never copied to global environment variables or included in logs.
            capabilities: Known image support and output limit for the selected model.
        Returns:
            None; creates a client with a 10-second connection timeout, 600-second
            read timeout, and one attempt per call. There is no automatic retry."""
        self.provider = "bedrock"
        self.model = model
        self.capabilities = capabilities
        session = botocore.session.get_session()
        session.register_component(
            "token_provider",
            TokenProviderChain(
                [
                    ScopedEnvTokenProvider(
                        session, environ={"AWS_BEARER_TOKEN_BEDROCK": token}
                    )
                ]
            ),
        )
        self.client = boto3.Session(botocore_session=session).client(
            "bedrock-runtime",
            region_name=region,
            config=Config(
                signature_version="bearer",
                connect_timeout=10,
                read_timeout=600,
                retries={"total_max_attempts": 1},
            ),
        )

    def generate(self, request: Request) -> Result:
        """Send one text/image request to Bedrock and translate its reply for the caller.

        Args:
            request: Application instructions, optional images and output-token allowance.
                If JSON fields are required, their schema is included in the instructions;
                the calling task still validates the actual reply afterward.
        Returns:
            Result containing reply text, model name, stop reason and reported usage.
            Performs one potentially billable request. On failure, raises ModelError
            with a safe AWS error code and recovery guidance for read timeouts, not
            credentials or the raw HTTP response. No failed request is retried here."""
        content = [
            {"image": {"format": im.format, "source": {"bytes": im.data}}}
            for im in request.images
        ]
        content.append({"text": request.prompt})
        system = request.system
        if request.schema:
            system += (
                "\nReturn only JSON matching this response schema:\n"
                + json.dumps(request.schema)
            )
        args = dict(
            modelId=self.model,
            messages=[{"role": "user", "content": content}],
            inferenceConfig={"maxTokens": request.max_tokens},
        )
        if system:
            args["system"] = [{"text": system}]
        try:
            response = self.client.converse(**args)
        except ReadTimeoutError:
            raise ModelError(
                f"Bedrock {self.model}: ReadTimeoutError — no reply within the "
                "600-second read timeout. Completed work is saved. Resume to retry "
                "the unfinished request; usage for the timed-out attempt is unknown."
            ) from None
        except Exception as exc:
            code = (
                (getattr(exc, "response", None) or {})
                .get("Error", {})
                .get("Code", type(exc).__name__)
            )
            raise ModelError(f"Bedrock {self.model}: {code}") from None
        blocks = response.get("output", {}).get("message", {}).get("content", [])
        usage = response.get("usage", {})
        return Result(
            text="\n".join(b["text"] for b in blocks if "text" in b),
            provider="bedrock",
            model=self.model,
            stop_reason=response.get("stopReason", "unknown"),
            input_tokens=usage.get("inputTokens"),
            output_tokens=usage.get("outputTokens"),
            raw_usage=usage,
        )


def bedrock_factory(role: str, values) -> BedrockModel:
    """Create the selected Bedrock model after checking its settings and known support.

    Args:
        role: text or vision; determines which model ID to read from configuration.
        values: Private settings containing the bearer credential, AWS region and
            model IDs. This mapping is not modified or printed.
    Returns:
        BedrockModel ready for requests. Missing credentials, unknown models and a
        text-only model selected for vision raise ModelError. No generation occurs."""
    token = (values.get("AWS_BEARER_TOKEN_BEDROCK") or "").strip()
    model = (values.get(f"BEDROCK_{role.upper()}_MODEL_ID") or "").strip()
    profiles = {
        "deepseek.v3.2": Capabilities(images=False, max_output_tokens=8000),
        "us.amazon.nova-2-lite-v1:0": Capabilities(
            images=True, max_output_tokens=64000
        ),
        "amazon.nova-2-lite-v1:0": Capabilities(images=True, max_output_tokens=64000),
    }
    if not token:
        raise ModelError("Bedrock credential is missing in .env")
    if model not in profiles:
        raise ModelError(
            "Model has no qualified capability profile in the Bedrock adapter"
        )
    if role == "vision" and not profiles[model].images:
        raise ModelError("Configured vision model does not accept images")
    return BedrockModel(
        model, values.get("AWS_REGION") or "us-east-2", token, profiles[model]
    )
