@echo off
rem Revision 4 addition. NOT executed by its authors: the first run by the user is the first test.
rem Starts start.py with the first Python that answers, newest first: py -3.14 ... py -3.10, then python.
rem No labels, no goto, no call: every line is independent. All arguments go to start.py.
rem The exit code of start.py is the exit code of this file (11 = no Python found).
cd /d "%~dp0"
py -3.14 -c "import sys" >nul 2>nul
if not errorlevel 1 py -3.14 start.py %* & exit /b
py -3.13 -c "import sys" >nul 2>nul
if not errorlevel 1 py -3.13 start.py %* & exit /b
py -3.12 -c "import sys" >nul 2>nul
if not errorlevel 1 py -3.12 start.py %* & exit /b
py -3.11 -c "import sys" >nul 2>nul
if not errorlevel 1 py -3.11 start.py %* & exit /b
py -3.10 -c "import sys" >nul 2>nul
if not errorlevel 1 py -3.10 start.py %* & exit /b
python -c "import sys" >nul 2>nul
if not errorlevel 1 python start.py %* & exit /b
echo No suitable Python found: neither the py launcher with 3.10 up to 3.14 nor python answered.
echo Install Python from https://www.python.org/downloads/ and tick Add python.exe to PATH,
echo keep the py launcher option, open a NEW cmd window and run run.cmd again.
exit /b 11
