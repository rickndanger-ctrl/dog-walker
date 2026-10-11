#!/usr/bin/env python3
"""Opt-in real local vision-chat test; isolated data, no walk or draft execution."""
import asyncio
import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def main():
    source_data = Path(os.environ.get('DOG_WALKER_DATA', Path.home()/'.local/share/dog-walker'))
    held = []
    for path in [source_data/'desktop-worker.lock', *source_data.glob('runs/*/run.lock'), *source_data.glob('chats/*/chat.lock')]:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open('a')
        fcntl.flock(handle, fcntl.LOCK_EX|fcntl.LOCK_NB)
        held.append(handle)
    artifacts = ROOT/'artifacts';artifacts.mkdir(exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix='chat-acceptance-', dir=artifacts))
    os.environ['DOG_WALKER_DATA'] = str(scratch/'data')
    from dog_walker import worker
    from dog_walker.chat import ChatWorker, Conversation, attachment, prompt_for
    worker.START_COMMAND = []  # Reuse the already loaded local model.
    conversation = Conversation.create()
    conversation.save(attachments=[attachment(ROOT/'native/cane-corso.png', conversation.path)])
    conversation.append('user', 'Describe the animal in the attached image, including its ear shape, in one sentence. Do not run tools.')
    chat = ChatWorker(lambda line: print(line, flush=True))
    await chat.ready()
    started = time.monotonic()
    reply = await asyncio.wait_for(chat.reply(conversation, prompt_for(conversation)), 180)
    assert reply.strip(), 'No local vision answer'
    conversation.append('assistant', reply)
    events = [json.loads(line) for path in conversation.path.glob('turn-*/events.jsonl') for line in path.read_text().splitlines()]
    assert any(e.get('type')=='turn.completed' for e in events)
    assert not any(e.get('item',{}).get('type') in {'command_execution','file_change','mcp_tool_call'} for e in events), 'Vision description unexpectedly used tools'
    assert not (scratch/'data/runs').exists(), 'Chat created a walk'
    report = {'local_endpoint':worker.ENDPOINT,'data':str(scratch),'reply':reply,'vision_image':str(ROOT/'native/cane-corso.png'),'duration_seconds':round(time.monotonic()-started,2),'turn_completed':True,'tools_used':False,'walk_created':False}
    (artifacts/'chat-acceptance.json').write_text(json.dumps(report, indent=2)+'\n')
    print('PASS: actual local vision chat, completed turn, no tools or walk. '+reply, flush=True)


if __name__ == '__main__':
    asyncio.run(main())
