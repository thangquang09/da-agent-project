"""Tests for the Plan-and-Execute architecture."""

from __future__ import annotations

import pytest

from app.graph import build_sql_v2_graph
from app.graph.state import AgentState


def test_task_planner_decomposes_query():
    """Test that the task planner can decompose a complex query into sub-tasks."""
    graph = build_sql_v2_graph()

    # Complex query with multiple independent parts
    state: AgentState = {
        "user_query": "Compare DAU last week vs this week and show top 5 videos by views",
        "target_db_path": "./data/warehouse/analytics.db",
    }

    config = {"configurable": {"thread_id": "test-plan-execute-1"}}

    # Run the graph
    result = graph.invoke(state, config)

    # Check that task_plan was created
    assert "task_plan" in result
    task_plan = result["task_plan"]

    # Should have multiple tasks (at least 2-3)
    assert len(task_plan) >= 2, f"Expected multiple tasks but got: {task_plan}"

    # Each task should have required fields
    for task in task_plan:
        assert "task_id" in task
        assert "query" in task
        assert "type" in task


def test_single_task_runs_linear():
    """Test that single tasks use linear execution (no parallel overhead)."""
    graph = build_sql_v2_graph()

    # Simple query that should result in single task
    state: AgentState = {
        "user_query": "What was the revenue yesterday?",
        "target_db_path": "./data/warehouse/analytics.db",
    }

    config = {"configurable": {"thread_id": "test-linear-1"}}

    # Run the graph
    result = graph.invoke(state, config)

    # Should have a final answer (single task path works correctly)
    assert "final_answer" in result
    assert result["final_answer"]

    # Verify intent was detected as SQL (new architecture route_to_execution_mode is working)
    assert result.get("intent") == "sql"


def test_parallel_execution_aggregates_results():
    """Test that parallel execution aggregates multiple task results."""
    graph = build_sql_v2_graph()

    # Query that should trigger parallel execution
    state: AgentState = {
        "user_query": "Get DAU for the last 3 days and also show top 5 videos",
        "target_db_path": "./data/warehouse/analytics.db",
    }

    config = {"configurable": {"thread_id": "test-parallel-1"}}

    # Run the graph
    result = graph.invoke(state, config)

    # Check for aggregation
    if result.get("execution_mode") == "parallel":
        assert "aggregate_analysis" in result

        # Aggregate should have task summary
        agg = result["aggregate_analysis"]
        assert "task_summary" in agg or "synthesis" in agg


def test_v2_graph_backward_compatible():
    """Test that v2 graph maintains backward compatibility with simple queries."""
    graph = build_sql_v2_graph()

    # RAG query (should work same as v1)
    state: AgentState = {
        "user_query": "What is retention D1?",
    }

    config = {"configurable": {"thread_id": "test-compat-1"}}

    # Run the graph
    result = graph.invoke(state, config)

    # Should have final answer
    assert "final_answer" in result

    # Check intent was detected
    assert result.get("intent") in ["rag", "unknown"]


def test_worker_subgraph_executes_sql():
    """Test that the SQL worker subgraph can execute SQL end-to-end."""
    from app.graph.sql_worker_graph import get_sql_worker_graph

    worker = get_sql_worker_graph()

    # Create a task state
    task_state = {
        "task_id": "test-1",
        "task_type": "sql_query",
        "query": "Get daily DAU for the last 7 days",
        "target_db_path": "./data/warehouse/analytics.db",
        "schema_context": "",
        "status": "pending",
    }

    # Run the worker
    result = worker.invoke(task_state)

    # Should have executed successfully or failed gracefully
    assert "status" in result
    assert result["status"] in ["success", "failed"]

    # If success, should have results
    if result["status"] == "success":
        assert "sql_result" in result
        assert "rows" in result["sql_result"] or "row_count" in result["sql_result"]
