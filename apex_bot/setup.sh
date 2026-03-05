#!/usr/bin/env bash
# Одноклик-установка для Linux / macOS
set -e
echo "=== APEX BOT SETUP ==="

# Проверка Python 3.11+
PY=$(python3 --version 2>&1 | awk '{print $2}')
MAJOR=$(echo $PY | cut -d. -f1)
MINOR=$(echo $PY | cut -d. -f2)
if [ "$MAJOR" -lt 3 ] || { [ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 11 ]; }; then
    echo "❌ Требуется Python 3.11+. Установлена версия: $PY"
    exit 1
fi
echo "✅ Python $PY — OK"

# Создание venv
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✅ Виртуальное окружение создано"
fi
source venv/bin/activate

# Установка зависимостей
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo "✅ Зависимости установлены"

# Создание .env если нет
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "✅ Создан .env из .env.example"
    echo ""
    echo "⚠️  СЛЕДУЮЩИЙ ШАГ: отредактируй .env и вставь API ключи от testnet.binancefuture.com"
else
    echo "ℹ️  .env уже существует — не перезаписан"
fi

# Создание папок
mkdir -p logs data/cache
echo "✅ Папки logs/ и data/cache/ созданы"

echo ""
echo "=== ГОТОВО ==="
echo "  source venv/bin/activate"
echo "  python -m pytest tests/ -v"
echo "  python main.py --mode backtest --days 30"
echo "  python main.py --mode paper"

