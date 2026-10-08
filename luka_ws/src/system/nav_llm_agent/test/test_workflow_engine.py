from nav_llm_agent.workflow_engine import WorkflowEngine


def test_workflow_resolves_arguments_and_advances():
    engine = WorkflowEngine(
        {
            "demo": {
                "steps": [
                    {"handler": "first", "arguments": {"floor": "$floor"}},
                    {"handler": "second", "arguments": {}},
                ]
            }
        }
    )
    engine.start("demo", {"floor": "floor_2"})
    assert engine.current()["arguments"]["floor"] == "floor_2"
    assert engine.advance() is False
    assert engine.current()["handler"] == "second"
    assert engine.advance() is True
    assert engine.active is False

