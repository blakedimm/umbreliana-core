@echo off
:: Переключаем консоль на UTF-8, чтобы она понимала русский язык и не ломалась
chcp 65001 > nul

title Umbreliana Terminal [STABLE]
color 0A

REM Принудительный переход в папку скрипта (автозапуск)
cd /d "%~dp0"

:loop
cls
echo [SYSTEM] Запуск предполетной проверки...
python validator.py

if %errorlevel% neq 0 (
    color 0C
    echo.
    echo !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    echo [ERROR] ОБНАРУЖЕНЫ ОШИБКИ В КОДЕ ИЛИ ЗАВИСИМОСТЯХ!
    echo [ERROR] Запуск gram.py отменен для защиты системы.
    echo !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    echo.
    echo Исправь ошибки и нажми любую клавишу для повторной проверки...
    pause > nul
    goto loop
)

color 0A
echo [SYSTEM] Проверка пройдена. Запуск терминала Umbreliana...
python gram.py

echo.
echo [SYSTEM] Бот остановлен или ушел в перезагрузку. 
echo [SYSTEM] Ожидание 3 секунды перед новым циклом...
timeout /t 3 > nul
goto loop