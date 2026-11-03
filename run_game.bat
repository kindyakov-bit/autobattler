@echo off
chcp 65001 >nul
title AutoBattler MVP

echo ========================================
echo   AutoBattler MVP - Python + Pygame
echo ========================================
echo.

cd /d "%~dp0"

if not exist "ui\game_ui.py" (
    echo Error: ui\game_ui.py not found
    echo Make sure you run this bat file from the autobattler folder
    pause
    exit /b 1
)

echo Starting game...
python run_ui.py

if %errorlevel% neq 0 (
    echo.
    echo Game exited with error code %errorlevel%.
    pause
) else (
    echo.
    echo Game finished.
)
