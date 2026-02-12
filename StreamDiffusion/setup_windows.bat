@echo off
echo ========================================
echo  Vision PAL - StreamDiffusion Setup
echo  Windows 11 + RTX 2080Ti
echo ========================================
echo.

REM Python venv作成
echo [1/4] Creating virtual environment...
python -m venv .venv
call .venv\Scripts\activate.bat

REM 基本パッケージ
echo [2/4] Installing base packages...
pip install -r requirements.txt

REM PyTorch + CUDA
echo [3/4] Installing PyTorch with CUDA 11.8...
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118

REM StreamDiffusion
echo [4/4] Installing StreamDiffusion...
pip install streamdiffusion

echo.
echo ========================================
echo  Setup complete!
echo.
echo  Quick test (toon filter only, no GPU):
echo    python server.py --no-gpu --jetbot http://192.168.3.8:8554/raw
echo.
echo  Full mode (StreamDiffusion + GPU):
echo    python server.py --jetbot http://192.168.3.8:8554/raw
echo.
echo  Open browser: http://localhost:8555
echo ========================================
pause
