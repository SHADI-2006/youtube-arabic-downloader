@echo off
cd /d "%~dp0"
start "" http://127.0.0.1:8000
"C:\Users\USER\AppData\Local\Programs\Python\Python313\python.exe" -m uvicorn webapp.server:app --host 127.0.0.1 --port 8000
