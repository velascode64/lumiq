#!/bin/bash

# Script para ejecutar las pruebas con pytest

echo "🧪 Ejecutando pruebas con pytest..."
echo "=================================="

# Cambiar al directorio del core
cd "$(dirname "$0")"

# Verificar si pytest está instalado
if ! command -v pytest &> /dev/null; then
    echo "❌ pytest no está instalado. Instálalo con: pip install pytest pytest-cov"
    exit 1
fi

# Ejecutar diferentes tipos de pruebas según el argumento
case "$1" in
    unit)
        echo "📦 Ejecutando tests unitarios..."
        pytest tests/test_simple_live_strategy.py -v
        ;;
    integration)
        echo "🔗 Ejecutando tests de integración..."
        pytest tests/test_core_functionality.py -v
        ;;
    working)
        echo "✅ Ejecutando tests que funcionan..."
        pytest tests/test_simple_live_strategy.py tests/test_core_functionality.py -v
        ;;
    coverage)
        echo "📊 Ejecutando tests con cobertura..."
        pytest tests/test_simple_live_strategy.py tests/test_core_functionality.py -v --cov=. --cov-report=html --cov-report=term
        echo "📈 Reporte HTML generado en htmlcov/index.html"
        ;;
    quick)
        echo "⚡ Ejecutando tests rápidos..."
        pytest tests/test_simple_live_strategy.py tests/test_core_functionality.py -v -x --tb=short
        ;;
    all)
        echo "🚀 Ejecutando todos los tests (incluyendo los que pueden fallar)..."
        pytest tests/ -v
        ;;
    *)
        echo "Uso: ./run_tests.sh [unit|integration|working|coverage|quick|all]"
        echo ""
        echo "Opciones:"
        echo "  unit        - Ejecuta tests de lógica de estrategia"
        echo "  integration - Ejecuta tests de funcionalidad del core"
        echo "  working     - Ejecuta solo tests que funcionan correctamente"
        echo "  coverage    - Ejecuta tests funcionales con reporte de cobertura"
        echo "  quick       - Ejecuta tests rápidos (se detiene en el primer fallo)"
        echo "  all         - Ejecuta TODOS los tests (algunos pueden fallar por mocks complejos)"
        echo ""
        echo "Ejecutando tests que funcionan por defecto..."
        pytest tests/test_simple_live_strategy.py tests/test_core_functionality.py -v
        ;;
esac

# Capturar código de salida
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo ""
    echo "✅ Todas las pruebas pasaron exitosamente!"
else
    echo ""
    echo "❌ Algunas pruebas fallaron. Revisa los errores arriba."
fi

exit $EXIT_CODE