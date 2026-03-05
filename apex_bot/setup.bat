@echo off
REM Одноклик-установка для Windows (CMD)
REM Запускать двойным кликом или: cd apex_bot && setup.bat
echo === APEX BOT SETUP ===
echo.

REM Проверка Python 3.11+
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ОШИБКА: Python не найден в PATH.
    echo Скачай Python 3.11+ с https://python.org  (НЕ из Microsoft Store!)
    echo При установке обязательно поставь галку "Add Python to PATH"
    pause
    exit /b 1
)

REM Проверка версии через python -c
python -c "import sys; exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if %errorlevel% neq 0 (
    python --version
    echo ОШИБКА: Требуется Python 3.11 или новее.
    pause
    exit /b 1
)
echo OK: Python 3.11+ найден

REM Создание venv
if not exist "venv" (
    python -m venv venv
    if %errorlevel% neq 0 (
        echo ОШИБКА: Не удалось создать виртуальное окружение
        pause
        exit /b 1
    )
    echo OK: Виртуальное окружение создано
) else (
    echo INFO: venv уже существует
)

REM Активация venv
call venv\Scripts\activate.bat

REM Обновление pip и установка зависимостей
python -m pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
if %errorlevel% neq 0 (
    echo ОШИБКА: Не удалось установить зависимости. Проверь интернет-соединение.
    pause
    exit /b 1
)
echo OK: Зависимости установлены

REM Создание .env
if not exist ".env" (
    copy .env.example .env >nul
    echo OK: Создан .env из .env.example
    echo.
    echo *** СЛЕДУЮЩИЙ ШАГ ***
    echo Открой файл .env в Блокноте и вставь API ключи от testnet.binancefuture.com
    echo Инструкция в README.md раздел "Получение API ключей"
) else (
    echo INFO: .env уже существует - не перезаписан
)

REM Создание папок
if not exist "logs" mkdir logs
if not exist "data\cache" mkdir data\cache
if not exist "reports" mkdir reports
echo OK: Папки созданы

echo.
echo === ГОТОВО ===
echo.
echo Дальнейшие шаги (запускать из папки apex_bot\):
echo   venv\Scripts\activate
echo   python -m pytest tests\ -v
echo   python main.py --mode backtest --days 30
echo   python main.py --mode paper
echo.
pause

