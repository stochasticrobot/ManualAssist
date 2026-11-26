"""Check that different model providers can be selected without changing manual-
analysis code. Simulated connections also test unsupported image requests, finite
timeouts and error handling without real credentials."""
from fixture_source_choices import local_evidence_reply, fixture_payload

import pytest
from workbench.model_access.model_requests_and_responses import (
    Capabilities,
    Image,
    ModelError,
    ModelService,
    Request,
    Result,
)


class IndependentAdapter:
    """A non-Bedrock adapter proving the interface needs no AWS-shaped payloads."""

    provider = "independent"
    model = "fixture"
    capabilities = Capabilities(images=True, max_output_tokens=8000)

    @local_evidence_reply
    def generate(self, request):
        """Return a recognizable result without transport.

        Args:
            request: Neutral application request.
        Returns:
            Fixture result preserving the prompt; never makes a network call.
        """
        return Result(request.prompt, "independent", "fixture", "complete")


def test_provider_substitution():
    """Verify a non-AWS adapter is callable through the unchanged interface.

    Args:
        None.
    Returns:
        None; assertions fail if routing introduces vendor dependencies.
    """
    service = ModelService(
        {"text": IndependentAdapter(), "vision": IndependentAdapter()}
    )
    assert service.generate("text", Request("READY")).text == "READY"
    assert (
        service.generate("vision", Request("image", images=(Image(b"png"),))).provider
        == "independent"
    )


def test_unsupported_image_rejected_before_transport():
    """Ensure unsupported multimodal requests cannot silently become text calls.

    Args:
        None.
    Returns:
        None; assertions fail unless unsupported images and roles are rejected.
    """
    adapter = IndependentAdapter()
    adapter.capabilities = Capabilities(max_output_tokens=8000)
    service = ModelService({"text": adapter})
    with pytest.raises(ModelError, match="does not accept images"):
        service.generate("text", Request("describe", images=(Image(b"png"),)))
    with pytest.raises(ModelError, match="Unconfigured"):
        service.generate("missing", Request("hello"))


def test_provider_registry_composes_without_bedrock_credentials(tmp_path, monkeypatch):
    """Prove the real composition entry point accepts another provider independently.

    Args:
        tmp_path: Isolated config directory with no AWS credentials.
        monkeypatch: Scoped provider registry isolation.
    Returns:
        None; assertions prove registry substitution without app-interface changes.
    """
    from workbench.model_access import configure_model_providers as providers

    monkeypatch.setattr(providers, "FACTORIES", {})
    providers.register_provider(
        "independent", lambda role, values: IndependentAdapter()
    )
    config = tmp_path / ".env"
    config.write_text("TEXT_PROVIDER=independent\nVISION_PROVIDER=independent\n")
    service = providers.configured_service(config)
    assert service.generate("text", Request("READY")).text == "READY"
    assert (
        service.generate(
            "vision", Request("describe", images=(Image(b"image"),))
        ).provider
        == "independent"
    )


def test_transport_error_with_none_response_is_normalized():
    """Prevent timeout error handling from masking the original SDK error class.

    Args:
        None.
    Returns:
        None; asserts ModelError identifies the transport failure without raw secrets.
    """
    from workbench.model_access.providers.bedrock import BedrockModel

    class TransportFailure(Exception):
        """Minimal SDK-shaped failure whose response attribute is explicitly None."""

        response = None

    class BrokenClient:
        """No-network client that reproduces the observed error envelope."""

        def converse(self, **kwargs):
            """Raise the controlled failure without exposing the request.

            Args:
                **kwargs: Ignored Converse arguments.
            Returns:
                Never returns; raises TransportFailure for adapter normalization.
            """
            raise TransportFailure("private diagnostic must not escape")

    model = BedrockModel.__new__(BedrockModel)
    model.model = "fixture"
    model.client = BrokenClient()
    with pytest.raises(ModelError, match="TransportFailure") as failure:
        model.generate(Request("hello"))
    assert "private diagnostic" not in str(failure.value)


def test_bedrock_read_timeout_is_finite_actionable_and_not_retried():
    """Check timeout translation without AWS calls.

    Args:
        None.
    Returns:
        None; fails if timeout recovery text leaks details or repeats a request.
    """
    from unittest.mock import Mock
    from botocore.exceptions import ReadTimeoutError
    from workbench.model_access.providers.bedrock import BedrockModel

    model = BedrockModel.__new__(BedrockModel)
    model.model = "fixture"
    model.client = Mock()
    model.client.converse.side_effect = ReadTimeoutError(
        endpoint_url="https://private-endpoint.invalid"
    )
    with pytest.raises(ModelError, match="ReadTimeoutError") as failure:
        model.generate(Request("hello"))
    assert model.client.converse.call_count == 1
    assert "Resume" in str(failure.value)
    assert "unknown" in str(failure.value)
    assert "private-endpoint" not in str(failure.value)


def test_captioning_provider_can_change_without_text_or_vision(tmp_path, monkeypatch):
    """Keep future captioning-provider replacement independent of text and vision.

    Args:
        tmp_path: Temporary non-secret settings directory.
        monkeypatch: Isolated provider registry replacement.
    Returns:
        None; verifies the real configuration factory selects independent providers
        and maps the captioning model override without changing vision settings.
    """
    from workbench.model_access import configure_model_providers as providers
    calls=[]
    def factory(role, values):
        """Capture the role-local model setting without contacting a provider.

        Args:
            role: Factory model capability role.
            values: Local settings copied by the composition function.
        Returns:
            Independent fixture adapter; captures non-secret model identifiers.
        """
        calls.append((role,values.get('BEDROCK_VISION_MODEL_ID')))
        return IndependentAdapter()
    monkeypatch.setattr(providers,'FACTORIES',{'original':factory,'replacement':factory})
    settings=tmp_path/'settings'
    settings.write_text('TEXT_PROVIDER=original\nVISION_PROVIDER=original\nIMAGE_CAPTIONING_PROVIDER=replacement\nBEDROCK_VISION_MODEL_ID=old\nBEDROCK_IMAGE_CAPTIONING_MODEL_ID=new\n')
    service=providers.configured_service(settings)
    assert calls==[('text','old'),('vision','old'),('vision','new')]
    assert service.generate('image_captioning',Request('READY')).text=='READY'
