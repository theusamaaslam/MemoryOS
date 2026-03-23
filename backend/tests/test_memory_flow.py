from app.services.providers import HeuristicProvider


def test_heuristic_provider_extracts_failures_and_hints():
    provider = HeuristicProvider()
    artifact = provider.reflect(
        "\n".join(
            [
                "user: I prefer concise replies",
                "assistant: Here is a long answer",
                "user: This didn't solve my refund issue",
            ]
        )
    )

    assert artifact.preferences
    assert artifact.failures
    assert artifact.retrieval_hints
