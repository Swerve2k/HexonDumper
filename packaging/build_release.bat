  @echo off
  setlocal
  cd /d "%~dp0.."

  if not exist "build\Release\dxgi.dll" if not exist "prebuilt\dxgi.dll" (
    cmake -S . -B build -A x64 || exit /b 1
    cmake --build build --config Release || exit /b 1
  )

  python -m pip install --upgrade pip || exit /b 1
  python -m pip install -r requirements.txt pyinstaller || exit /b 1
  python -m PyInstaller --noconfirm --clean --distpath dist --workpath build\pyinstaller packaging\hexon.spec || exit /b 1

  set "ISCC="
  if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
  if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
  if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
  if not defined ISCC (
    echo Inno Setup 6 was not found.
    exit /b 1
  )
  "%ISCC%" installer\Hexon.iss || exit /b 1
  echo Installer written to dist-installer
