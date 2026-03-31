@echo off
cd /d %~dp0
call venv\Scripts\activate
set PYTHONNOUSERSITE=1
echo Starting OCR Pipeline server...
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
