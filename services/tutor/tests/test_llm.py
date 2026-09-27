from tutor import llm


def use(monkeypatch, **values):
    for name, value in values.items():
        monkeypatch.setattr(llm.settings, name, value)


def test_describe_grader_reports_grader_model(monkeypatch):
    use(monkeypatch, mock_llm=False, grader_provider="ollama",
        ollama_grader_model="grader-x", ollama_tutor_model="tutor-y")
    assert llm.describe_grader() == "ollama:grader-x"


def test_describe_tutor_reports_tutor_model(monkeypatch):
    use(monkeypatch, mock_llm=False, grader_provider="ollama", tutor_provider="ollama",
        ollama_grader_model="grader-x", ollama_tutor_model="tutor-y")
    assert llm.describe_tutor() == "ollama:tutor-y"


def test_describe_mock(monkeypatch):
    use(monkeypatch, mock_llm=True)
    assert llm.describe_grader() == "mock"
    assert llm.describe_tutor() == "mock"


def test_describe_claude(monkeypatch):
    use(monkeypatch, mock_llm=False, grader_provider="claude", tutor_provider="claude", model="claude-x")
    assert llm.describe_grader() == "claude:claude-x"
    assert llm.describe_tutor() == "claude:claude-x"
