import io
import json
from unittest.mock import Mock
import pytest
from dog_walker.decision_mcp import DecisionServer
from dog_walker.helper_mcp import dispatch, run_stdio


def test_initialize_and_discovery():
    server = DecisionServer(Mock())
    result = dispatch(server, {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
        'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'test', 'version': '1'}}})
    assert result['result']['serverInfo']['name'] == 'handler-decisions'
    assert 'local-only' in result['result']['instructions']
    assert server.tools()[0]['inputSchema']['additionalProperties'] is False


def test_call_returns_structured_local_decision():
    judge = Mock()
    judge.decide.return_value = {'answers': {'context': {'choice': 'tests', 'probabilities': [0, 0, 1, 0]}}}
    server = DecisionServer(judge)
    result = server.call('decide', {'preset': 'context', 'evidence': 'Failing tests'})
    assert result['structuredContent']['backend'] == 'laya'
    assert result['structuredContent']['results']['context']['value'] == 'tests'


@pytest.mark.parametrize('args', [ {'preset': 'context', 'evidence': 'task', 'backend': 'jev'},
                                 {'preset': 'review', 'evidence': 'task'},
                                 {'preset': 'context', 'evidence': 'x'*12001},
                                 {'preset': 'shell', 'evidence': 'task'}])
def test_invalid_call_is_error_without_inference(args):
    judge = Mock()
    response = dispatch(DecisionServer(judge), {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                               'params': {'name': 'decide', 'arguments': args}})
    assert response['result']['isError'] is True
    judge.decide.assert_not_called()


def test_stdio_survives_bad_input():
    out = io.StringIO()
    run_stdio(DecisionServer(Mock()), io.StringIO('bad\n'+json.dumps({'jsonrpc':'2.0','id':2,'method':'tools/list'})+'\n'), out)
    lines = list(map(json.loads, out.getvalue().splitlines()))
    assert lines[0]['error']['code'] == -32700
    assert lines[1]['result']['tools'][0]['name'] == 'decide'
