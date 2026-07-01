#!/bin/bash
# Run all tests EXCEPT image mode tests
# Usage: ./run_all_tests_except_image.sh

set -e

echo "=========================================="
echo "Running All Mode Tests (Excluding Image)"
echo "=========================================="

# Change to project root
cd "$(dirname "$0")"

# Run pytest excluding image-related tests
echo ""
echo ">>> Running comprehensive mode tests..."
pytest tests/test_all_modes_comprehensive.py -v --tb=short 2>&1 || true

echo ""
echo ">>> Running input/sanitization tests..."
pytest tests/test_input_normalizer_mode_contract.py -v --tb=short 2>&1 || true

echo ""
echo ">>> Running output safety tests..."
pytest tests/test_chat_output_safety.py -v --tb=short 2>&1 || true

echo ""
echo ">>> Running auth scope tests..."
pytest tests/test_auth_scope_hardening.py -v --tb=short 2>&1 || true
pytest tests/test_admin_scope_hardening.py -v --tb=short 2>&1 || true

echo ""
echo ">>> Running crypto mode tests..."
pytest tests/test_crypto_runtime.py -v --tb=short 2>&1 || true
pytest tests/test_crypto_trade_safety.py -v --tb=short 2>&1 || true
pytest tests/test_crypto_predict_engine.py -v --tb=short 2>&1 || true

echo ""
echo ">>> Running conversation/memory tests..."
pytest tests/test_conversation_state_db.py -v --tb=short 2>&1 || true
pytest tests/test_conversation_turns.py -v --tb=short 2>&1 || true
pytest tests/test_durable_memory.py -v --tb=short 2>&1 || true

echo ""
echo ">>> Running project mode tests..."
pytest tests/test_chat_project_binding.py -v --tb=short 2>&1 || true
pytest tests/test_retrieval_project_scope.py -v --tb=short 2>&1 || true

echo ""
echo ">>> Running agent mode tests..."
pytest tests/test_agent_run.py -v --tb=short 2>&1 || true
pytest tests/test_agent_step.py -v --tb=short 2>&1 || true
pytest tests/test_agent_continue.py -v --tb=short 2>&1 || true
pytest tests/test_agent_eval_check.py -v --tb=short 2>&1 || true

echo ""
echo ">>> Running API smoke tests..."
pytest tests/test_api_smoke.py -v --tb=short 2>&1 || true

echo ""
echo ">>> Running redaction tests..."
pytest tests/test_redaction.py -v --tb=short 2>&1 || true

echo ""
echo ">>> Running session/context tests..."
pytest tests/test_session_context.py -v --tb=short 2>&1 || true

echo ""
echo "=========================================="
echo "All mode tests complete!"
echo "=========================================="
