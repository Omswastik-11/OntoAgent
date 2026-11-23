import sys
if sys.platform == "win32":
    import asyncio
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

    # Windows 11 Smart App Control (SAC) / WDAC Code Integrity compatibility:
    # Unsigned C-extensions like numpy.random._pcg64 can be blocked by Application Control policy.
    # Provide stubbed type definitions for pandas._typing (which only references Generator, BitGenerator, RandomState).
    try:
        import numpy.random  # noqa: F401
    except (ImportError, OSError) as _err:
        if "Application Control" in str(_err) or "DLL load failed" in str(_err):
            import types
            try:
                import numpy
                _stub = types.ModuleType("numpy.random")
                _stub.Generator = type("Generator", (), {})
                _stub.BitGenerator = type("BitGenerator", (), {})
                _stub.RandomState = type("RandomState", (), {})
                _stub.default_rng = lambda *a, **kw: _stub.Generator()
                sys.modules["numpy.random"] = _stub
                numpy.random = _stub
            except Exception:
                pass

__version__ = "0.1.0"

