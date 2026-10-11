import io
import json
from unittest.mock import Mock
import pytest
from dog_walker import decisions as d
from dog_walker.workflow import WalkerError


def test_typed_decisions_and_uncertainty():
    judge = Mock()
    judge.decide.return_value = {'answers': {'context': {'choice': 'tests', 'probabilities': [.1, .1, .7, .1]}}}
    result = d.evaluate(judge, 'laya', 'context', 'Fix failing tests')
    assert result['results']['context'] == {'value': 'tests', 'confidence': .7, 'status': 'review'}
    assert result['advisory'] is True


@pytest.mark.parametrize('answer', [{}, {'choice': 'shell', 'probabilities': [1, 0, 0, 0]},
                                  {'choice': 'tests', 'probabilities': [0, 0, float('nan'), 0]}])
def test_invalid_answers(answer):
    judge = Mock()
    judge.decide.return_value = {'answers': {'context': answer}}
    assert d.evaluate(judge, 'laya', 'context', 'Task')['results']['context']['status'] == 'invalid'


def test_review_negative_and_positive():
    judge = Mock()
    judge.decide.return_value = {'answers': {'criterion_1': {'noul': .95}, 'criterion_2': {'noul': .04}}}
    result = d.evaluate(judge, 'laya', 'review', 'Evidence', ['Tests pass', 'No blockers'])
    assert result['results']['criterion_1']['value'] is True
    assert result['results']['criterion_2']['value'] is False


def test_limits_before_inference():
    judge = Mock()
    with pytest.raises(WalkerError):
        d.evaluate(judge, 'laya', 'context', 'x' * (d.LIMIT + 1))
    with pytest.raises(WalkerError):
        d.evaluate(judge, 'laya', 'review', 'evidence')
    judge.decide.assert_not_called()


def test_fractional_score():
    judge = Mock()
    judge.decide.return_value = {'answers': {'urgency': {'score': 1.8, 'probabilities': {'0': 0, '1': .2, '2': .8}}}}
    result = d.evaluate(judge, 'laya', 'triage', 'Urgent task')
    assert result['results']['urgency']['value'] == 1.8
    assert result['results']['urgency']['status'] == 'review'
    assert len(result['results']['urgency']['scale']) == 3


def test_pipe_defaults_local(monkeypatch, capsys):
    local = Mock()
    local.decide.return_value = {'answers': {}}
    monkeypatch.setattr(d, 'LocalJudge', lambda: local)
    hosted = Mock()
    monkeypatch.setattr(d, 'JevJudge', hosted)
    monkeypatch.setattr('sys.stdin', io.StringIO('A task'))
    assert d.main(['context', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['backend'] == 'laya'
    hosted.assert_not_called()


def test_explicit_hosted(monkeypatch):
    hosted = Mock()
    hosted.return_value.decide.return_value = {'answers': {}}
    monkeypatch.setattr(d, 'JevJudge', hosted)
    assert d.main(['context', 'task', '--backend', 'jev', '--json']) == 0
    hosted.assert_called_once_with(test_only=True)


def test_unavailable_and_cancel(monkeypatch, capsys):
    monkeypatch.setattr(d, 'LocalJudge', Mock(side_effect=WalkerError('Unavailable')))
    assert d.main(['context', 'task', '--json']) == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'error'
    monkeypatch.setattr(d, 'LocalJudge', Mock(side_effect=KeyboardInterrupt))
    assert d.main(['context', 'task']) == 130


def test_handoff_has_no_tools_or_history(monkeypatch):
    call = Mock(return_value=0)
    monkeypatch.setattr(d.subprocess, 'call', call)
    d.handoff('Task', {'advisory': True})
    args = call.call_args.args[0]
    assert '--no-tools' in args and '--no-session' in args and '--no-context-files' in args


def test_file_input_and_oversized_hosted(monkeypatch, tmp_path, capsys):
    source = tmp_path / 'task.txt'
    source.write_text('Inspect the tests')
    local = Mock()
    local.decide.return_value = {'answers': {}}
    monkeypatch.setattr(d, 'LocalJudge', lambda: local)
    assert d.main(['context', '--file', str(source), '--json']) == 0
    assert local.decide.call_args.args[0] == {'evidence': 'Inspect the tests'}
    source.write_text('x' * (d.LIMIT+1))
    hosted = Mock()
    monkeypatch.setattr(d, 'JevJudge', hosted)
    assert d.main(['context', '--file', str(source), '--backend', 'jev', '--json']) == 1
    hosted.assert_not_called()


def test_menu_reuses_local_judge(monkeypatch):
    local = Mock()
    local.decide.return_value = {'answers': {}}
    constructor = Mock(return_value=local)
    monkeypatch.setattr(d, 'LocalJudge', constructor)
    entries = iter(['2', '', 'Task', '.', 'n', '2', '', 'Task two', '.', 'n', 'q'])
    monkeypatch.setattr('builtins.input', lambda *args: next(entries))
    assert d.menu() == 0
    constructor.assert_called_once()
    assert local.decide.call_count == 2
