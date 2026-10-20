@echo off
rem ===========================================================================
rem  tools\pipe.cmd - the single entry point to tools\ (thin shell, T-AG420)
rem
rem  Why: one copy of tools\ must serve every repo, so people remember ONE shape:
rem      pipe <tool> [args...]   ->   python -X utf8 tools\<tool>.py [args...]
rem  This file only forwards. It parses no arguments, resolves no root, and
rem  never swallows the exit code.
rem    [root] the called tool resolves it itself (single source: tools\_repo.py);
rem           this shell does not second-guess it (--root is passed through).
rem    [utf8] -X utf8 is a house rule; hardcoded here so it cannot be forgotten.
rem  NOTE: kept ASCII-only on purpose. cmd.exe reads batch files in the OEM code
rem        page, so UTF-8 text (even in rem lines) gets mis-decoded and can leak
rem        stray '&' / '|' bytes into the command line. Tool output is unaffected
rem        (Python talks to the console through the wide-char API).
rem
rem  Usage:
rem      tools\pipe.cmd wb_daily
rem      tools\pipe.cmd wb_plan check --root D:\other\repo
rem      tools\pipe.cmd wb_daily --json
rem  Known limits (batch files, not this shell's judgement):
rem    * an embedded double quote inside an argument gets eaten / rewritten;
rem    * an empty-string argument ("") is swallowed by the shift loop.
rem ===========================================================================
setlocal EnableExtensions

rem  %0 follows `shift` too - capture the script dir NOW, or %%~dp0 turns into the
rem  directory of a shifted argument (a real bug this shell had for one round).
set "HERE=%~dp0"

set "NAME=%~1"
if not defined NAME goto :usage
if /i "%NAME%"=="-h" goto :usage
if /i "%NAME%"=="--help" goto :usage

rem accept both "wb_daily" and "wb_daily.py"
if /i "%NAME:~-3%"==".py" set "NAME=%NAME:~0,-3%"

rem only real .py files under tools\ - a typo should say so, not dump a python traceback
if not exist "%HERE%%NAME%.py" (
    echo [pipe] no such tool: tools\%NAME%.py
    echo [pipe] available tools: dir /b "%HERE%*.py"
    echo [pipe] e.g.  tools\pipe.cmd wb_daily --json
    exit /b 2
)

rem collect the rest: %* does NOT follow shift, so take "%~1" one at a time
set "ARGS="
:collect
shift
if "%~1"=="" goto :run
set "ARGS=%ARGS% "%~1""
goto :collect

:run
python -X utf8 "%HERE%%NAME%.py" %ARGS%
exit /b %ERRORLEVEL%

:usage
echo usage: tools\pipe.cmd ^<tool^> [args...]
echo   e.g.  tools\pipe.cmd wb_daily --json
echo         tools\pipe.cmd wb_plan check --root D:\other\repo
echo forwards to: python -X utf8 tools\^<tool^>.py [args...]
exit /b 2
