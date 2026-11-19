@echo off
setlocal
set PYTHON=.venv\Scripts\python.exe
if not exist "%PYTHON%" (
    set PYTHON=python
)

if "%1"=="verify" (
    %PYTHON% scripts\verify.py
) else if "%1"=="verify-fast" (
    %PYTHON% scripts\verify.py --fast
) else if "%1"=="test" (
    %PYTHON% -m pytest tests\unit tests\adversarial -v
) else if "%1"=="test-unit" (
    %PYTHON% -m pytest tests\unit -v
) else if "%1"=="lint" (
    %PYTHON% -m ruff check src tests scripts
) else if "%1"=="check-env" (
    %PYTHON% scripts\check_env.py
) else if "%1"=="kb-ingest" (
    %PYTHON% -m ontoagent.data.ingest_kb
) else if "%1"=="data-sample" (
    %PYTHON% -m ontoagent.data.make_sample
) else if "%1"=="data-build" (
    %PYTHON% -m ontoagent.data.load_postgres
    %PYTHON% -m ontoagent.data.load_neo4j
    %PYTHON% -m ontoagent.data.ingest_kb
) else (
    echo Usage: make [verify ^| verify-fast ^| test ^| test-unit ^| check-env ^| lint ^| kb-ingest ^| data-build]
    %PYTHON% scripts\verify.py
)
endlocal
