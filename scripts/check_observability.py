"""Offline checks for logging and LangSmith tracing wiring. No network.

    python scripts/check_observability.py

Verifies the Phase 4 gate without credentials: tracing stays off when not
requested, is forced off (with the app running normally) when requested
without an API key, and is enabled purely through environment variables when a
key is present -- never by contacting LangSmith. langsmith caches env reads
(`get_env_var` is lru_cached), so its cache is cleared between scenarios.
"""

import io
import logging
import os

from langsmith import utils as ls_utils

from customer_support.observability import configure_logging, configure_tracing

failures: list[str] = []

_TRACING_VARS = (
    "LANGSMITH_TRACING",
    "LANGCHAIN_TRACING_V2",
    "LANGSMITH_API_KEY",
    "LANGCHAIN_API_KEY",
    "LANGSMITH_PROJECT",
    "LANGCHAIN_PROJECT",
    "LANGSMITH_ENDPOINT",
    "LANGCHAIN_ENDPOINT",
)


def check(label: str, actual: object, expected: object) -> None:
    if actual == expected:
        print(f"  ok    {label}")
    else:
        failures.append(label)
        print(f"  FAIL  {label}: expected {expected!r}, got {actual!r}")


def set_env(**values: str) -> None:
    """Reset every tracing variable, then set only `values`."""
    for name in _TRACING_VARS:
        os.environ.pop(name, None)
    os.environ.update(values)
    ls_utils.get_env_var.cache_clear()


def main() -> int:
    saved = {name: os.environ.get(name) for name in _TRACING_VARS}
    try:
        print("logging:")
        stream = io.StringIO()
        configure_logging("INFO")
        logging.getLogger().addHandler(logging.StreamHandler(stream))
        probe = logging.getLogger("check.observability")
        probe.debug("hidden")
        probe.info("shown")
        check("INFO shows info", "shown" in stream.getvalue(), True)
        check("INFO filters debug", "hidden" in stream.getvalue(), False)

        configure_logging("OFF")
        before = stream.getvalue()
        probe.critical("silenced")
        check("OFF silences even critical", stream.getvalue(), before)
        configure_logging("INFO")  # restore for the rest of the run

        print("\ntracing not requested:")
        set_env()
        check("returns disabled", configure_tracing(), False)
        check("env untouched", os.environ.get("LANGSMITH_TRACING"), None)
        check("langsmith agrees", ls_utils.tracing_is_enabled(), False)

        print("\ntracing requested without an API key (the gate case):")
        set_env(LANGSMITH_TRACING="true")
        check("returns disabled", configure_tracing(), False)
        check("LANGSMITH_TRACING forced false", os.environ["LANGSMITH_TRACING"], "false")
        check("legacy var also forced false", os.environ["LANGCHAIN_TRACING_V2"], "false")
        check("langsmith agrees", ls_utils.tracing_is_enabled(), False)

        print("\nlegacy spelling without a key:")
        set_env(LANGCHAIN_TRACING_V2="true")
        check("returns disabled", configure_tracing(), False)
        check("langsmith agrees", ls_utils.tracing_is_enabled(), False)

        print("\ntracing requested with a key present (dummy; never validated):")
        set_env(LANGSMITH_TRACING="true", LANGSMITH_API_KEY="lsv2_dummy_key")
        check("returns enabled", configure_tracing(), True)
        check("project defaulted", os.environ["LANGSMITH_PROJECT"], "customer-support-agent")
        check("langsmith agrees", ls_utils.tracing_is_enabled(), True)

        print("\nnon-canonical truthy spelling is normalized:")
        set_env(LANGSMITH_TRACING="True", LANGSMITH_API_KEY="lsv2_dummy_key")
        check("returns enabled", configure_tracing(), True)
        check("normalized to literal 'true'", os.environ["LANGSMITH_TRACING"], "true")
        check("langsmith agrees", ls_utils.tracing_is_enabled(), True)

        print("\nexplicit project is respected:")
        set_env(
            LANGSMITH_TRACING="true",
            LANGSMITH_API_KEY="lsv2_dummy_key",
            LANGSMITH_PROJECT="my-project",
        )
        check("returns enabled", configure_tracing(), True)
        check("project kept", os.environ["LANGSMITH_PROJECT"], "my-project")

        print("\napplication still runs with tracing requested and no key:")
        set_env(LANGSMITH_TRACING="true")
        configure_tracing()
        from customer_support.rag.search import aggregate, confidence_for

        result = aggregate([])
        check("pipeline modules import and run", result["outcome"], "needs_escalation")
        check("confidence logic unaffected", confidence_for(0.9, 0.5), "high")
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        ls_utils.get_env_var.cache_clear()

    if failures:
        print(f"\n{len(failures)} check(s) FAILED.")
        return 1
    print("\nAll observability checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
