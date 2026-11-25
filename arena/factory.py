"""
Component factory for Trust Fall.
Resolves implementations for Transport, Sandbox, Gate, LLM, Red, and Blue.
Falls back safely to mocks if keys or implementations are missing.
"""
import os
from pathlib import Path
import sys
import warnings
from dotenv import load_dotenv

from arena.interfaces import (
    BlueAgent,
    Gate,
    LLM,
    RedAgent,
    Sandbox,
    Transport,
)
from arena.mocks import (
    FakeSandbox,
    MockGate,
    MockLLM,
    MockTransport,
    ScriptedBlue,
    ScriptedRed,
)

load_dotenv()


def _is_mock_mode() -> bool:
    val = os.getenv("USE_MOCKS", "1").strip().lower()
    return val in {"1", "true", "yes"}


# ==============================================================================
# SECTION: NIKHIL OWNED IMPLEMENTATIONS (Agent layer, Transport, Sandbox, Blue, GateClient)
# ==============================================================================

def get_gate_client() -> Gate:
    if _is_mock_mode():
        return MockGate()
    try:
        from agents.gate_client import GateClient
        return GateClient()
    except Exception as e:
        warnings.warn(f"Failed to load GateClient ({e}), falling back to MockGate")
        return MockGate()


def get_transport() -> Transport:
    if _is_mock_mode():
        return MockTransport()

    impl = os.getenv("TRANSPORT", "mock").strip().lower()
    if impl == "loopback":
        try:
            from arena.transport_loopback import LoopbackTransport
            return LoopbackTransport()
        except Exception as e:
            warnings.warn(f"Failed to load LoopbackTransport ({e}), falling back to MockTransport")
            return MockTransport()
    elif impl == "band":
        try:
            from arena.transport_band import BandTransport
            return BandTransport()
        except Exception as e:
            warnings.warn(f"Failed to load BandTransport ({e}), falling back to MockTransport")
            return MockTransport()
    return MockTransport()


def get_sandbox() -> Sandbox:
    if _is_mock_mode():
        return FakeSandbox()

    impl = os.getenv("SANDBOX_IMPL", "fake").strip().lower()
    if impl == "agent37":
        api_key = os.getenv("AGENT37_API_KEY")
        if not api_key:
            warnings.warn("AGENT37_API_KEY missing, falling back to FakeSandbox")
            return FakeSandbox()
        try:
            from infra.agent37 import Agent37Sandbox
            return Agent37Sandbox(api_key=api_key)
        except Exception as e:
            warnings.warn(f"Failed to load Agent37Sandbox ({e}), falling back to FakeSandbox")
            return FakeSandbox(state_dir=Path("data/loopback_state"))
    return FakeSandbox(state_dir=Path("data/loopback_state"))


def get_llm() -> LLM:
    if _is_mock_mode():
        return MockLLM()

    impl = os.getenv("LLM_IMPL", "mock").strip().lower()
    if impl == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            warnings.warn("GEMINI_API_KEY missing, falling back to MockLLM")
            return MockLLM()
        try:
            from agents.llm_gemini import GeminiLLM
            return GeminiLLM(api_key=api_key)
        except Exception as e:
            warnings.warn(f"Failed to load GeminiLLM ({e}), falling back to MockLLM")
            return MockLLM()
    return MockLLM()


def get_blue() -> BlueAgent:
    if _is_mock_mode():
        return ScriptedBlue()

    blue_transport = os.getenv("BLUE_TRANSPORT", "in-process").strip().lower()
    if blue_transport == "band":
        try:
            from agents.blue_band import BandBlueClient
            return BandBlueClient()
        except Exception as e:
            warnings.warn(f"Failed to load BandBlueClient ({e}), falling back to in-process Blue")

    impl = os.getenv("BLUE_IMPL", "scripted").strip().lower()
    if impl == "llm":
        try:
            from agents.blue import LLMBlueAgent
            return LLMBlueAgent(llm=get_llm())
        except Exception as e:
            warnings.warn(f"Failed to load LLMBlueAgent ({e}), falling back to ScriptedBlue")
            return ScriptedBlue()
    elif impl == "scripted":
        try:
            from agents.blue import ScriptedBlue as RealScriptedBlue
            return RealScriptedBlue()
        except Exception:
            return ScriptedBlue()
    return ScriptedBlue()


# ==============================================================================
# SECTION: NEHAA OWNED IMPLEMENTATIONS (Gate, Red)
# ==============================================================================

def get_gate() -> Gate:
    if _is_mock_mode():
        return MockGate()

    impl = os.getenv("GATE_IMPL", "mock").strip().lower()
    if impl == "lyzr":
        api_key = os.getenv("LYZR_API_KEY")
        if not api_key:
            warnings.warn("LYZR_API_KEY missing, falling back to MockGate")
            return MockGate()
        try:
            from api.gate import LyzrGate
            return LyzrGate(api_key=api_key)
        except Exception as e:
            warnings.warn(f"Failed to load LyzrGate ({e}), falling back to MockGate")
            return MockGate()
    return MockGate()


def get_red() -> RedAgent:
    if _is_mock_mode():
        from agents.red import AdaptiveRed
        return AdaptiveRed(enable_mutation=False)

    impl = os.getenv("RED_IMPL", "scripted").strip().lower()
    if impl == "llm":
        try:
            from agents.red import AdaptiveRed
            return AdaptiveRed(llm=get_llm(), enable_mutation=True)
        except Exception as e:
            warnings.warn(f"Failed to load LLMRedAgent ({e}), falling back to ScriptedRed")
            return ScriptedRed()
    elif impl in ("scripted", "adaptive"):
        try:
            from agents.red import AdaptiveRed
            return AdaptiveRed(enable_mutation=False)
        except Exception:
            return ScriptedRed()
    return ScriptedRed()
