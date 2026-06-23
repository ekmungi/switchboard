# tests/test_browse.py - tests for the switchboard.browse module.
#
# These tests cover cmd_list and cmd_providers including the byte-for-byte
# markdown output guard for the /catalog slash command.  All calls to
# fetch_models are monkeypatched -- no live network.
# ---------------------------------------------------------------------------

import pytest
from switchboard import browse
from switchboard.catalog import Model

# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

_MODEL_A = Model(
    id="deepseek/deepseek-chat",
    name="DeepSeek Chat",
    context_length=131072,
    prompt_price=0.0000002,   # 0.20 per million
    completion_price=0.0000008,  # 0.80 per million
)

_MODEL_B = Model(
    id="deepseek/deepseek-r1",
    name="DeepSeek R1",
    context_length=163840,
    prompt_price=0.0000007,   # 0.70 per million
    completion_price=0.0000025,  # 2.50 per million
)

_MODELS_TWO = [_MODEL_A, _MODEL_B]


# ---------------------------------------------------------------------------
# cmd_list: markdown output -- exact byte guard for /catalog
# ---------------------------------------------------------------------------


def test_cmd_list_md_output_exact(monkeypatch, capsys):
    """cmd_list in markdown mode produces byte-for-byte identical output for /catalog.

    Sorted ascending by $IN/M: deepseek-chat (0.20) before deepseek-r1 (0.70).
    """
    monkeypatch.setattr(browse, "fetch_models", lambda: list(_MODELS_TWO))

    browse.cmd_list("deepseek", markdown=True)

    out = capsys.readouterr().out
    expected = (
        "\n"
        "2 model(s) matching 'deepseek':\n"
        "Switch in a session:         /model openrouter,<MODEL>\n"
        "Web search (append :online): /model openrouter,<MODEL>:online\n"
        "Set as default (terminal):   sb use <MODEL>\n"
        "\n"
        "| MODEL  (paste after 'openrouter,') | CTX | $IN/M | $OUT/M |\n"
        "| --- | --- | --- | --- |\n"
        "| deepseek/deepseek-chat | 131072 | 0.20 | 0.80 |\n"
        "| deepseek/deepseek-r1 | 163840 | 0.70 | 2.50 |\n"
    )
    assert out == expected


def test_cmd_list_no_query_calls_providers(monkeypatch, capsys):
    """cmd_list with empty query delegates to cmd_providers."""
    monkeypatch.setattr(browse, "fetch_models", lambda: list(_MODELS_TWO))

    browse.cmd_list("", markdown=True)

    out = capsys.readouterr().out
    # providers header line must appear; model table must not
    assert "providers," in out
    assert "MODEL  (paste after" not in out


# ---------------------------------------------------------------------------
# cmd_providers: markdown output -- exact byte guard
# ---------------------------------------------------------------------------


def test_cmd_providers_md_output_exact(capsys):
    """cmd_providers in markdown mode emits the correct header, hint, and table."""
    # Two models from same provider; one extra from a second provider.
    model_extra = Model(
        id="openai/gpt-4o",
        name="GPT-4o",
        context_length=128000,
        prompt_price=0.0000025,
        completion_price=0.000010,
    )
    models = [_MODEL_A, _MODEL_B, model_extra]

    browse.cmd_providers(models, markdown=True)

    out = capsys.readouterr().out
    # deepseek has 2 models (listed first by count desc), openai has 1
    expected = (
        "\n"
        "2 providers, 3 models total.\n"
        "See a company's models:  sb list <PROVIDER>   (e.g. sb list deepseek)\n"
        "\n"
        "| PROVIDER | MODELS |\n"
        "| --- | --- |\n"
        "| deepseek | 2 |\n"
        "| openai | 1 |\n"
    )
    assert out == expected
