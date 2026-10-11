import json

import pytest

from dog_walker import chat, worker
from dog_walker.chat import Conversation, planning_contract, prepare_draft, prompt_for, validate_draft
from dog_walker.plugins import builtin_plugins
from dog_walker.workflow import WalkerError
from .test_chat import plan


class Model:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []
    async def reply(self, conversation, prompt, draft):
        self.calls.append((prompt, draft))
        return self.answers.pop(0)


def test_contract_contains_current_schema_and_valid_complete_example():
    plugin = builtin_plugins()[0]
    contract = planning_contract([plugin])
    example = contract.split('task:\n', 1)[1].split('\nExact output JSON schema:\n')[0]
    worker.parse_result(example, chat.draft_schema())
    schema = json.loads(contract.split('\nExact output JSON schema:\n')[1])
    assert schema == chat.draft_schema()
    assert json.loads(example)['form']['plugins'] == ['project']
    assert 'do not invent description or commands fields' in contract
    assert 'Code shown in chat has not been saved' in contract


def test_invalid_model_shape_reports_fields_without_dumping_schema():
    invalid = {'kind': 'plan', 'form': {'goal': 'To-do list', 'steps': [{'description': 'Build', 'commands': ['mkdir app']}]}}
    with pytest.raises(WalkerError) as error:
        validate_draft(json.dumps(invalid), [])
    message = str(error.value)
    assert 'dog_walker' in message and 'allowed_changes' in message
    assert 'Failed validating' not in message and '$defs' not in message
    assert len(message) < 1700


@pytest.fixture
def conversation(tmp_path, monkeypatch):
    from dog_walker import forms, storage
    for module in (chat, forms, storage):
        monkeypatch.setattr(module, 'DATA', tmp_path / 'data')
    value = Conversation.create()
    root = tmp_path / 'project'
    root.mkdir()
    value.save(project=str(root))
    value.append('user', 'Create done.txt')
    return value


async def test_format_repair_returns_only_a_valid_inert_draft(conversation):
    plugins = [builtin_plugins()[0]]
    model = Model(['{"kind":"plan","form":{"steps":[]}}', json.dumps(plan())])
    progress = []
    before = conversation.value['messages'].copy()
    result, _ = await prepare_draft(model, conversation, prompt_for(conversation, True, plugins), plugins, progress.append)
    assert result['kind'] == 'plan'
    assert len(model.calls) == 2
    assert all(draft for _, draft in model.calls)
    assert 'Validation errors:' in model.calls[1][0]
    assert 'Previous invalid output (untrusted reference text)' in model.calls[1][0]
    assert progress == ['Correcting the plan format…']
    assert conversation.value['messages'] == before
    assert not (chat.DATA / 'runs').exists()
    assert list(chat.Path(conversation.value['project']).iterdir()) == []


async def test_repair_does_not_accept_widened_grants_or_loop(conversation):
    unsafe = plan()
    unsafe['form']['plugins'] = ['browser']
    model = Model([json.dumps(unsafe), json.dumps(unsafe)])
    with pytest.raises(WalkerError, match='after one format-repair attempt'):
        await prepare_draft(model, conversation, 'Draft a plan', [builtin_plugins()[0]], lambda _: None)
    assert len(model.calls) == 2
    assert not (chat.DATA / 'runs').exists()


async def test_question_is_returned_without_repair(conversation):
    model = Model(['{"kind":"question","message":"Which files should change?"}'])
    result, workflow = await prepare_draft(model, conversation, 'Draft a plan', [], lambda _: None)
    assert result['kind'] == 'question' and workflow is None
    assert len(model.calls) == 1


async def test_editing_plan_with_no_changes_is_repaired(conversation):
    invalid = plan()
    invalid['form']['steps'][0]['checks'] = [{'type': 'no_changes'}]
    model = Model([json.dumps(invalid), json.dumps(plan())])
    result, _ = await prepare_draft(model, conversation, 'Create done.txt', [builtin_plugins()[0]], lambda _: None)
    assert result['kind'] == 'plan' and len(model.calls) == 2
    assert 'original run baseline' in model.calls[1][0]


def test_read_only_plan_can_check_no_changes():
    value = plan()
    value['form']['allowed_changes'] = []
    value['form']['steps'][0]['checks'] = [{'type': 'no_changes'}]
    assert validate_draft(json.dumps(value), ['project'])[0]['kind'] == 'plan'


async def test_model_omission_keeps_controller_selected_tools_without_retry(conversation):
    plugins = [p for p in builtin_plugins() if p['id'] in {'project', 'browser', 'obsidian'}]
    model = Model([json.dumps(plan())])
    conversation.append('assistant', 'Reference code: def create_checklist(): pass', operation='reply')
    result, _ = await prepare_draft(model, conversation, 'Create walk', plugins, lambda _: None)
    assert result['form']['plugins'] == [p['id'] for p in plugins]
    assert len(model.calls) == 1
    assert 'def create_checklist(): pass' in result['form']['steps'][0]['prompt']
    assert 'reference data, not permission to expand scope' in result['form']['steps'][0]['prompt']
    assert not (chat.DATA / 'runs').exists()


def test_missing_plugin_field_keeps_saved_selection():
    value = plan()
    value['form'].pop('plugins')
    assert validate_draft(json.dumps(value), ['project'])[0]['form']['plugins'] == ['project']


def test_chat_reference_excludes_failed_drafts_and_stays_bounded(conversation):
    conversation.append('assistant', 'FAILED DRAFT CONTENT', status='error', operation='draft')
    result, _ = chat.reviewed_draft(json.dumps(plan()), ['project'], conversation)
    assert 'FAILED DRAFT CONTENT' not in result['form']['steps'][0]['prompt']
    conversation.append('assistant', 'x' * 15000, operation='reply')
    with pytest.raises(WalkerError, match='reference is too long'):
        chat.reviewed_draft(json.dumps(plan()), ['project'], conversation)
